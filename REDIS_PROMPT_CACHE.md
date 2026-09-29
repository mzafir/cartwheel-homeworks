# Redis Prompt Cache — Setup & Admin Interface

A fast, networked prompt storage system backed by Redis with the official Redis Insight admin interface.

## Quick Start

### 1. Start Redis + Redis Insight

```bash
docker-compose -f docker-compose-redis.yml up -d
```

This starts:
- **Redis** at `localhost:6379` (password: `prompts123`)
- **Redis Insight** (official GUI) at `http://localhost:5540`

### 2. Install Python Dependencies

```bash
pip install redis fuzzywuzzy python-Levenshtein
```

### 3. Add Some Prompts

```bash
# Add via CLI
python3 prompt_cache.py add "Your prompt text here" --name "My Prompt" --tags "tag1,tag2"

# Or import from file
python3 prompt_cache.py import sample_prompts.txt

# Verify it's in Redis
python3 prompt_cache.py list
```

### 4. View in Redis Insight

Open browser: **http://localhost:5540**

1. Click **"Add Redis Database"**
2. Enter details:
   - **Host:** `localhost`
   - **Port:** `6379`
   - **Password:** `prompts123`
   - **Database Name:** `Cartwheel Prompts`
3. Click **"Add Redis Database"**

Now you can browse all your prompts in the Redis GUI:
- `prompts:list` — All prompt IDs
- `prompts:search` — Search index
- `prompt:*` — Individual prompt hashes

---

## CLI Commands

All commands connect to Redis automatically (or fall back to JSON if Redis is unavailable).

### Add Prompts

```bash
# Simple add
python3 prompt_cache.py add "Your prompt text"

# With name and tags
python3 prompt_cache.py add "Your prompt text" --name "My Prompt" --tags "tag1,tag2,tag3"
```

### Search Prompts

```bash
# Fuzzy search (default threshold: 60%)
python3 prompt_cache.py search "refund"

# Stricter matching (threshold 80%)
python3 prompt_cache.py search "payment" --threshold 80
```

### Get Prompt by ID

```bash
python3 prompt_cache.py get abc12345
```

### List All Prompts

```bash
# Top 50 (default)
python3 prompt_cache.py list

# Top 100
python3 prompt_cache.py list --limit 100
```

### Import/Export

```bash
# Import from text file
python3 prompt_cache.py import sample_prompts.txt

# Export to JSON
python3 prompt_cache.py export backup.json --format json

# Export in full format (with names, tags)
python3 prompt_cache.py export backup.txt --format full
```

### Delete & Clear

```bash
# Delete one prompt
python3 prompt_cache.py delete abc12345

# Clear entire cache
python3 prompt_cache.py clear
```

### View Statistics

```bash
python3 prompt_cache.py stats
```

Output:
```
📊 STATS

Backend:       redis
Total Prompts: 10
Total Uses:    42
Most Used:     #abc12345 (7 times)
```

---

## Using Redis Insight

### Browse Your Prompts

1. Open **http://localhost:5540**
2. Select **"Cartwheel Prompts"** database
3. Expand **Keys** to see:
   - `prompts:list` → All prompt IDs (list)
   - `prompts:search` → Search index (list)
   - `prompt:abc12345` → Individual prompt (hash)

### Inspect a Prompt Hash

Click on `prompt:abc12345` to see:
- `id` — UUID
- `name` — Display name
- `text` — Full prompt content
- `tags` — JSON array of tags
- `created_at` — ISO timestamp
- `uses` — Usage counter (incremented on retrieval)

### Real-time Monitoring

In Redis Insight, use **Profiler** to watch:
- Incoming commands
- Key access patterns
- Performance metrics

---

## Python API Usage

Use the Redis-backed cache in your code:

```python
from prompt_cache import PromptCache

# Connect to Redis
cache = PromptCache(backend="redis", redis_host="localhost", redis_port=6379, redis_password="prompts123")

# Add
prompt = cache.add("Your prompt text", tags=["tag1"], name="My Prompt")
print(f"Added: {prompt['id']}")

# Search
results = cache.search("keyword", threshold=60)
for r in results:
    print(f"  #{r['id']} [{r['score']}%]: {r['name']}")

# Get
p = cache.get_by_id(prompt['id'])
print(p["text"])

# List
all_prompts = cache.list_all(limit=50)

# Stats
stats = cache.stats()
print(f"Backend: {stats['backend']}, Total: {stats['total_prompts']}")
```

### Backend Fallback

The cache automatically falls back to JSON if Redis is unavailable:

```python
# Try Redis, fall back to JSON
cache = PromptCache(backend="auto")

# Force JSON
cache = PromptCache(backend="json")

# Force Redis (error if unavailable)
cache = PromptCache(backend="redis", redis_host="...")
```

---

## Database Schema

### Redis Data Structure

```
Key: prompts:list
Type: List
Value: [id1, id2, id3, ...]
Purpose: All prompt IDs

Key: prompts:search
Type: List
Value: [id1, id2, id3, ...]
Purpose: Search index (same as prompts:list currently)

Key: prompt:abc12345
Type: Hash
Fields:
  id → "abc12345"
  name → "My Prompt"
  text → "Full prompt content..."
  tags → '["tag1", "tag2"]'
  created_at → "2026-09-17T10:30:00"
  uses → "7"
```

---

## Troubleshooting

### Redis Connection Error

```
ERROR: Redis connection failed: Error 61 connecting to localhost:6379
```

**Fix:**
```bash
# Start Redis
docker-compose -f docker-compose-redis.yml up -d

# Or check status
docker ps | grep redis
```

### Redis Insight Won't Connect

```
ERROR: Cannot connect to 127.0.0.1:6379
```

**Fix:**
1. Verify password: `prompts123` (set in docker-compose)
2. Check port: Should be `6379` (not `9379`)
3. Restart Redis: `docker-compose -f docker-compose-redis.yml restart redis`

### "No matches found" on Search

Try lower threshold:
```bash
python3 prompt_cache.py search "keyword" --threshold 40
```

### Export Shows Empty Results

Verify prompts exist:
```bash
python3 prompt_cache.py list --limit 5
python3 prompt_cache.py stats
```

---

## Redis CLI Access (Advanced)

For direct Redis access without GUI:

```bash
# Connect to Redis CLI
docker exec -it cartwheel-redis redis-cli -a prompts123

# Inside Redis CLI:
redis> KEYS prompt:*
redis> HGETALL prompt:abc12345
redis> LRANGE prompts:list 0 -1
redis> INFO
redis> DBSIZE
```

---

## Performance Notes

- **Fuzzy Search:** Uses Levenshtein distance (fuzzywuzzy). Scales linearly with prompt count.
- **Redis Memory:** Each prompt ≈ 500 bytes (text varies). 1000 prompts ≈ 1 MB.
- **Index:** Current implementation rescans all prompts on search. For >10k prompts, consider adding Redis search module.

---

## Stopping Services

```bash
# Stop all services
docker-compose -f docker-compose-redis.yml down

# Stop but keep data
docker-compose -f docker-compose-redis.yml down --volumes
```

---

## Next Steps

1. ✅ Start Redis: `docker-compose -f docker-compose-redis.yml up -d`
2. ✅ Open Redis Insight: http://localhost:5540
3. ✅ Add prompts: `python3 prompt_cache.py import sample_prompts.txt`
4. ✅ Search: `python3 prompt_cache.py search "refund"`
5. ✅ Monitor: Refresh Redis Insight to see live keys

**You now have a production-ready prompt cache with full admin access! 🚀**
