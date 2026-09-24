#!/usr/bin/env python3
"""
Quick Prompt Search — Simplified CLI for prompt cache.

Usage:
  python3 quick_prompt.py                    # Interactive menu
  python3 quick_prompt.py refund             # Search for "refund"
  python3 quick_prompt.py -a "My prompt"     # Add new prompt
  python3 quick_prompt.py -l                 # List all
"""

import sys
import json
from pathlib import Path
from prompt_cache import PromptCache
from fuzzywuzzy import fuzz

def interactive_menu():
    """Interactive prompt selection menu."""
    cache = PromptCache()
    
    while True:
        print("\n" + "="*60)
        print("📌 PROMPT CACHE MANAGER")
        print("="*60)
        print("1. Search prompts")
        print("2. List all prompts")
        print("3. Get prompt by ID")
        print("4. Add new prompt")
        print("5. Import from file")
        print("6. Delete prompt")
        print("0. Exit")
        print("-"*60)
        
        choice = input("Choose: ").strip()
        
        if choice == "1":
            query = input("Search keywords: ").strip()
            if query:
                results = cache.search(query, threshold=50)
                if results:
                    print(f"\n📌 Found {len(results)} matches:\n")
                    for r in results[:15]:
                        print(f"  #{r['id']:2d} [{r['score']:3d}%] {r['name'][:50]}")
                        if r['tags']:
                            print(f"      Tags: {', '.join(r['tags'])}")
                else:
                    print("❌ No matches found")
        
        elif choice == "2":
            prompts = cache.list_all(limit=100)
            print(f"\n📚 Cached Prompts ({len(prompts)}):\n")
            for p in prompts:
                print(f"  #{p['id']:2d} | Uses: {p.get('uses', 0):2d} | {p['name'][:60]}")
        
        elif choice == "3":
            try:
                prompt_id = int(input("Prompt ID: "))
                prompt = cache.get_by_id(prompt_id)
                if prompt:
                    print(f"\n{'='*60}")
                    print(f"📋 {prompt['name']}")
                    print(f"{'='*60}")
                    print(prompt["text"])
                    print(f"\n{'='*60}")
                    print(f"Tags: {', '.join(prompt['tags']) if prompt['tags'] else '(none)'}")
                    print(f"Uses: {prompt.get('uses', 0)}")
                else:
                    print("❌ Not found")
            except ValueError:
                print("❌ Invalid ID")
        
        elif choice == "4":
            text = input("Enter prompt text (or paste): ").strip()
            if text:
                name = input("Name (optional): ").strip() or text[:50]
                tags_str = input("Tags (comma-separated, optional): ").strip()
                tags = [t.strip() for t in tags_str.split(",")] if tags_str else []
                
                prompt = cache.add(text, tags=tags, name=name)
                print(f"✓ Added prompt #{prompt['id']}")
        
        elif choice == "5":
            file_path = input("File path: ").strip()
            if file_path:
                try:
                    count = cache.import_from_file(Path(file_path))
                    print(f"✓ Imported {count} prompts")
                except FileNotFoundError:
                    print("❌ File not found")
        
        elif choice == "6":
            try:
                prompt_id = int(input("Prompt ID to delete: "))
                if input("Confirm? (y/n): ").lower() == "y":
                    cache.delete(prompt_id)
                    print(f"✓ Deleted prompt #{prompt_id}")
            except ValueError:
                print("❌ Invalid ID")
        
        elif choice == "0":
            print("Goodbye! 👋")
            break
        
        else:
            print("❌ Invalid choice")

def main():
    """CLI entry point."""
    cache = PromptCache()
    
    if len(sys.argv) < 2:
        # Interactive mode
        interactive_menu()
        return
    
    # Command mode
    arg = sys.argv[1]
    
    if arg == "-l" or arg == "--list":
        # List all
        prompts = cache.list_all(limit=100)
        print(f"\n📚 Cached Prompts ({len(prompts)}):\n")
        for p in prompts:
            print(f"#{p['id']:2d} | {p['name'][:60]}")
    
    elif arg == "-a" or arg == "--add":
        # Add
        if len(sys.argv) > 2:
            text = " ".join(sys.argv[2:])
            prompt = cache.add(text)
            print(f"✓ Added prompt #{prompt['id']}")
        else:
            print("Usage: quick_prompt.py -a 'Your prompt text'")
    
    elif arg.startswith("-"):
        print("Unknown option")
    
    else:
        # Search
        results = cache.search(arg, threshold=50)
        if results:
            print(f"\n🔍 Found {len(results)} matches for '{arg}':\n")
            for r in results[:10]:
                print(f"#{r['id']:2d} [{r['score']:3d}%] {r['name'][:60]}")
                print(f"    {r['text'][:100]}...")
                print()
        else:
            print(f"❌ No matches for '{arg}'")

if __name__ == "__main__":
    main()
