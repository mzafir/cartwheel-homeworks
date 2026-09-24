#!/usr/bin/env python3
"""
Prompt Cache with Redis Backend — Store, search, and retrieve prompts efficiently.

Supports:
  - Redis backend (primary, for distributed access)
  - JSON file backend (fallback, for local dev)
  - Fuzzy search across text, names, and tags
  - Usage tracking and statistics
  - Tag-based organization
  - Import/export to text files

Usage:
  from prompt_cache import PromptCache
  cache = PromptCache(redis_host='localhost', redis_port=6379)
  cache.add("Prompt text", tags=["tag1"], name="Name")
  results = cache.search("keyword", threshold=60)
"""

import json
import uuid
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

try:
    from rapidfuzz import fuzz
except ImportError:
    try:
        from fuzzywuzzy import fuzz
    except ImportError:
        print("⚠️  No fuzzy matching library. Install with: pip install rapidfuzz")
        sys.exit(1)

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

class PromptCache:
    """Unified prompt cache with Redis or JSON backend."""
    
    SCHEMA_VERSION = "1.0"
    
    def __init__(self, 
                 backend: str = "auto",
                 redis_host: str = "localhost",
                 redis_port: int = 6379,
                 redis_password: Optional[str] = None,
                 redis_db: int = 0,
                 json_path: Optional[Path] = None):
        """
        Initialize prompt cache.
        
        Args:
            backend: "redis" (networked), "json" (local file), or "auto" (try redis, fall back to json)
            redis_host: Redis server hostname
            redis_port: Redis server port
            redis_password: Redis password (optional)
            redis_db: Redis database number
            json_path: Path to JSON database (default: ~/.copilot/prompt_cache/prompts.json)
        """
        self.backend_type = backend
        self.json_path = json_path or Path.home() / ".copilot" / "prompt_cache" / "prompts.json"
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Try to connect to Redis if requested or auto-detecting
        self.redis_client = None
        if backend in ["redis", "auto"]:
            if REDIS_AVAILABLE:
                try:
                    self.redis_client = redis.Redis(
                        host=redis_host,
                        port=redis_port,
                        password=redis_password,
                        db=redis_db,
                        decode_responses=True,
                        socket_connect_timeout=5
                    )
                    # Test connection
                    self.redis_client.ping()
                    self.backend_type = "redis"
                    print(f"✓ Connected to Redis at {redis_host}:{redis_port}")
                except Exception as e:
                    if backend == "redis":
                        raise RuntimeError(f"Redis connection failed: {e}")
                    else:
                        print(f"⚠ Redis unavailable: {e}. Falling back to JSON.")
                        self.redis_client = None
                        self.backend_type = "json"
            else:
                if backend == "redis":
                    raise ImportError("redis package not installed. Run: pip install redis")
                self.backend_type = "json"
        
        # Initialize JSON backend if needed
        if self.backend_type == "json" and not self.json_path.exists():
            self.json_path.write_text(json.dumps([]))
    
    def add(self, text: str, tags: Optional[List[str]] = None, name: Optional[str] = None) -> Dict[str, Any]:
        """Add a new prompt to cache."""
        prompt_id = str(uuid.uuid4())[:8]
        name = name or text[:50]
        tags = tags or []
        now = datetime.utcnow().isoformat()
        
        prompt = {
            "id": prompt_id,
            "name": name,
            "text": text,
            "tags": tags,
            "created_at": now,
            "uses": 0
        }
        
        if self.backend_type == "redis":
            # Store as Redis hash
            key = f"prompt:{prompt_id}"
            self.redis_client.hset(key, mapping={
                "id": prompt["id"],
                "name": prompt["name"],
                "text": prompt["text"],
                "tags": json.dumps(prompt["tags"]),
                "created_at": prompt["created_at"],
                "uses": "0"
            })
            # Add to index
            self.redis_client.lpush("prompts:list", prompt_id)
            # Index for search
            self.redis_client.lpush("prompts:search", prompt_id)
        else:
            # JSON backend
            prompts = self._read_json()
            prompts.append(prompt)
            self._write_json(prompts)
        
        return prompt
    
    def search(self, query: str, threshold: int = 60) -> List[Dict[str, Any]]:
        """
        Fuzzy search across prompt text, names, and tags.
        
        Returns list of matches sorted by score (highest first).
        """
        if self.backend_type == "redis":
            # Get all prompt IDs from index
            prompt_ids = self.redis_client.lrange("prompts:search", 0, -1)
            prompts = []
            for pid in prompt_ids:
                key = f"prompt:{pid}"
                if self.redis_client.exists(key):
                    data = self.redis_client.hgetall(key)
                    prompts.append({
                        "id": data["id"],
                        "name": data["name"],
                        "text": data["text"],
                        "tags": json.loads(data["tags"]),
                        "created_at": data["created_at"],
                        "uses": int(data["uses"])
                    })
        else:
            prompts = self._read_json()
        
        # Fuzzy match
        results = []
        for p in prompts:
            # Score: text (50%), name (30%), tags (20%)
            text_score = fuzz.partial_ratio(query.lower(), p["text"].lower())
            name_score = fuzz.ratio(query.lower(), p["name"].lower())
            tags_text = " ".join(p.get("tags", []))
            tags_score = fuzz.partial_ratio(query.lower(), tags_text.lower())
            
            combined_score = int(text_score * 0.5 + name_score * 0.3 + tags_score * 0.2)
            
            if combined_score >= threshold:
                results.append({
                    **p,
                    "score": combined_score
                })
        
        # Sort by score descending
        return sorted(results, key=lambda x: x["score"], reverse=True)
    
    def get_by_id(self, prompt_id: str) -> Optional[Dict[str, Any]]:
        """Get prompt by ID and increment usage counter."""
        if self.backend_type == "redis":
            key = f"prompt:{prompt_id}"
            if not self.redis_client.exists(key):
                return None
            
            data = self.redis_client.hgetall(key)
            # Increment uses
            self.redis_client.hincrby(key, "uses", 1)
            
            return {
                "id": data["id"],
                "name": data["name"],
                "text": data["text"],
                "tags": json.loads(data["tags"]),
                "created_at": data["created_at"],
                "uses": int(data["uses"]) + 1
            }
        else:
            prompts = self._read_json()
            for p in prompts:
                if p["id"] == prompt_id:
                    p["uses"] = p.get("uses", 0) + 1
                    self._write_json(prompts)
                    return p
            return None
    
    def list_all(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List all prompts sorted by usage (most used first)."""
        if self.backend_type == "redis":
            prompt_ids = self.redis_client.lrange("prompts:search", 0, -1)
            prompts = []
            for pid in prompt_ids:
                key = f"prompt:{pid}"
                if self.redis_client.exists(key):
                    data = self.redis_client.hgetall(key)
                    prompts.append({
                        "id": data["id"],
                        "name": data["name"],
                        "text": data["text"],
                        "tags": json.loads(data["tags"]),
                        "created_at": data["created_at"],
                        "uses": int(data["uses"])
                    })
        else:
            prompts = self._read_json()
        
        # Sort by uses descending
        sorted_prompts = sorted(prompts, key=lambda x: x.get("uses", 0), reverse=True)
        return sorted_prompts[:limit]
    
    def delete(self, prompt_id: str) -> bool:
        """Delete a prompt by ID."""
        if self.backend_type == "redis":
            key = f"prompt:{prompt_id}"
            if self.redis_client.exists(key):
                self.redis_client.delete(key)
                self.redis_client.lrem("prompts:search", 1, prompt_id)
                self.redis_client.lrem("prompts:list", 1, prompt_id)
                return True
            return False
        else:
            prompts = self._read_json()
            original_len = len(prompts)
            prompts = [p for p in prompts if p["id"] != prompt_id]
            if len(prompts) < original_len:
                self._write_json(prompts)
                return True
            return False
    
    def clear(self) -> int:
        """Clear all prompts. Returns count deleted."""
        if self.backend_type == "redis":
            count = len(self.redis_client.keys("prompt:*"))
            self.redis_client.delete("prompts:search", "prompts:list")
            for key in self.redis_client.keys("prompt:*"):
                self.redis_client.delete(key)
            return count
        else:
            prompts = self._read_json()
            count = len(prompts)
            self._write_json([])
            return count
    
    def import_from_file(self, path: Path, separator: str = "---") -> int:
        """
        Import prompts from text file.
        
        Format:
        [name: Prompt Name]
        [tags: tag1, tag2, tag3]
        Prompt text content...
        Can span multiple lines...
        ---
        [name: Next Prompt]
        ...
        """
        content = Path(path).read_text()
        prompts_text = content.split(separator)
        
        count = 0
        for block in prompts_text:
            block = block.strip()
            if not block:
                continue
            
            lines = block.split("\n")
            name = None
            tags = []
            text_lines = []
            
            for line in lines:
                if line.startswith("[name:"):
                    name = line.replace("[name:", "").replace("]", "").strip()
                elif line.startswith("[tags:"):
                    tags_str = line.replace("[tags:", "").replace("]", "").strip()
                    tags = [t.strip() for t in tags_str.split(",")]
                else:
                    text_lines.append(line)
            
            text = "\n".join(text_lines).strip()
            if text:
                self.add(text, tags=tags, name=name)
                count += 1
        
        return count
    
    def export_to_file(self, path: Path, format: str = "full") -> None:
        """
        Export prompts to file.
        
        Formats:
        - full: [name], [tags], text with "---" separators
        - json: JSON array
        - text_only: Just the prompt texts
        """
        prompts = self.list_all(limit=10000)
        
        if format == "json":
            Path(path).write_text(json.dumps(prompts, indent=2))
        elif format == "text_only":
            texts = [p["text"] for p in prompts]
            Path(path).write_text("\n\n---\n\n".join(texts))
        else:  # full
            lines = []
            for p in prompts:
                lines.append(f"[name: {p['name']}]")
                if p.get("tags"):
                    lines.append(f"[tags: {', '.join(p['tags'])}]")
                lines.append(p["text"])
                lines.append("---")
            
            Path(path).write_text("\n".join(lines))
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        prompts = self.list_all(limit=10000)
        total_uses = sum(p.get("uses", 0) for p in prompts)
        
        return {
            "backend": self.backend_type,
            "total_prompts": len(prompts),
            "total_uses": total_uses,
            "most_used": prompts[0] if prompts else None,
            "json_path": str(self.json_path) if self.backend_type == "json" else None
        }
    
    # JSON backend helpers
    def _read_json(self) -> List[Dict]:
        """Read prompts from JSON file."""
        if self.json_path.exists():
            return json.loads(self.json_path.read_text())
        return []
    
    def _write_json(self, data: List[Dict]) -> None:
        """Write prompts to JSON file."""
        self.json_path.write_text(json.dumps(data, indent=2))


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Prompt Cache — Redis-backed prompt storage with fuzzy search"
    )
    parser.add_argument("--backend", choices=["auto", "redis", "json"], default="auto",
                        help="Storage backend (default: auto, tries redis then json)")
    import os
    parser.add_argument("--redis-host", default=os.environ.get("REDIS_HOST", "localhost"), help="Redis hostname")
    parser.add_argument("--redis-port", type=int, default=int(os.environ.get("REDIS_PORT", 6379)), help="Redis port")
    parser.add_argument("--redis-password", default=os.environ.get("REDIS_PASSWORD", "prompts123"), help="Redis password")
    
    subparsers = parser.add_subparsers(dest="command")
    
    # Add
    add_parser = subparsers.add_parser("add", help="Add new prompt")
    add_parser.add_argument("text", help="Prompt text")
    add_parser.add_argument("--name", help="Prompt name")
    add_parser.add_argument("--tags", help="Comma-separated tags")
    
    # Search
    search_parser = subparsers.add_parser("search", help="Search prompts")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--threshold", type=int, default=60, help="Match threshold (0-100)")
    
    # Get
    get_parser = subparsers.add_parser("get", help="Get prompt by ID")
    get_parser.add_argument("id", help="Prompt ID")
    
    # List
    list_parser = subparsers.add_parser("list", help="List all prompts")
    list_parser.add_argument("--limit", type=int, default=50, help="Max results")
    
    # Delete
    del_parser = subparsers.add_parser("delete", help="Delete prompt")
    del_parser.add_argument("id", help="Prompt ID")
    
    # Import
    import_parser = subparsers.add_parser("import", help="Import from file")
    import_parser.add_argument("file", help="File path")
    
    # Export
    export_parser = subparsers.add_parser("export", help="Export to file")
    export_parser.add_argument("file", help="Output file path")
    export_parser.add_argument("--format", choices=["full", "json", "text_only"], 
                               default="full", help="Export format")
    
    # Clear
    subparsers.add_parser("clear", help="Clear all prompts")
    
    # Stats
    subparsers.add_parser("stats", help="Show statistics")
    
    args = parser.parse_args()
    
    # Initialize cache
    cache = PromptCache(
        backend=args.backend,
        redis_host=args.redis_host,
        redis_port=args.redis_port,
        redis_password=args.redis_password
    )
    
    if args.command == "add":
        tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
        prompt = cache.add(args.text, tags=tags, name=args.name)
        print(f"✓ Added prompt #{prompt['id']}")
    
    elif args.command == "search":
        results = cache.search(args.query, threshold=args.threshold)
        if results:
            print(f"\n🔍 Found {len(results)} matches:\n")
            for r in results[:20]:
                print(f"#{r['id']:8s} [{r['score']:3d}%] {r['name'][:60]}")
                if r.get("tags"):
                    print(f"            Tags: {', '.join(r['tags'])}")
        else:
            print("❌ No matches found")
    
    elif args.command == "get":
        prompt = cache.get_by_id(args.id)
        if prompt:
            print(f"\n{'='*70}")
            print(f"📋 {prompt['name']}")
            print(f"{'='*70}")
            print(prompt["text"])
            print(f"\n{'='*70}")
            print(f"ID: {prompt['id']} | Uses: {prompt.get('uses', 0)} | Tags: {', '.join(prompt.get('tags', []))}")
        else:
            print("❌ Not found")
    
    elif args.command == "list":
        prompts = cache.list_all(limit=args.limit)
        print(f"\n📚 Cached Prompts ({len(prompts)}):\n")
        for p in prompts:
            print(f"#{p['id']:8s} | Uses: {p.get('uses', 0):3d} | {p['name'][:60]}")
    
    elif args.command == "delete":
        if cache.delete(args.id):
            print(f"✓ Deleted prompt #{args.id}")
        else:
            print(f"❌ Not found")
    
    elif args.command == "import":
        count = cache.import_from_file(Path(args.file))
        print(f"✓ Imported {count} prompts")
    
    elif args.command == "export":
        cache.export_to_file(Path(args.file), format=args.format)
        print(f"✓ Exported to {args.file}")
    
    elif args.command == "clear":
        count = cache.clear()
        print(f"✓ Cleared {count} prompts")
    
    elif args.command == "stats":
        stats = cache.stats()
        print(f"\n📊 STATS\n")
        print(f"Backend:       {stats['backend']}")
        print(f"Total Prompts: {stats['total_prompts']}")
        print(f"Total Uses:    {stats['total_uses']}")
        if stats["most_used"]:
            print(f"Most Used:     #{stats['most_used']['id']} ({stats['most_used'].get('uses', 0)} times)")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
