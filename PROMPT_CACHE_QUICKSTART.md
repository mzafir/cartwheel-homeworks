# 🚀 Prompt Cache — Quick Start (5 Minutes)

Store, search, and reuse prompts with **fuzzy matching** and **file import**.

## 30-Second Setup

```bash
# 1. Install
pip install fuzzywuzzy python-Levenshtein

# 2. Import sample prompts
python3 quick_prompt.py
# Choose: 5 (Import from file) → sample_prompts.txt

# 3. Start using
python3 quick_prompt.py refund     # Search
python3 quick_prompt.py            # Interactive menu
```

## Shell Aliases (Optional but Recommended)

Add to `~/.zshrc` or `~/.bashrc`:
```bash
# Add this ONE line to your shell config:
source ~/.prompt_cache_setup
```

Then reload:
```bash
source ~/.zshrc
```

Now you can use:
```bash
psearch refund      # Search
p refund            # Quick search
plist               # List all
pget 5              # Get by ID
padd "My prompt"    # Add new
phelp               # Show commands
```

## Common Tasks

### Search for a Prompt
```bash
psearch "refund"
# Shows matching prompts with scores
```

### View a Prompt
```bash
pget 3
# Displays full prompt text
```

### Add a New Prompt
```bash
padd "Your prompt text here"
# Or use interactive menu: pcache
```

### Import Prompts from File
```bash
pimport my_prompts.txt
# File format:
# [name: Prompt Name]
# [tags: tag1, tag2]
# Prompt text...
# ---
```

### List All Prompts
```bash
plist
# Shows top 50 by usage
```

### Backup Your Prompts
```bash
pexport ~/backup.json json
```

## File Locations

- **Prompts stored at:** `~/.copilot/prompt_cache/prompts.json`
- **Sample file:** `sample_prompts.txt` (in repo)
- **Full guide:** `PROMPT_CACHE_GUIDE.md` (in repo)

## Examples

### Example 1: Find Refund Prompt
```bash
$ psearch refund
📌 Found 2 matches for 'refund':

  #1 [98%] Cartwheel HW1 Refund Query
      Tags: cartwheel, refund, homework, testing
  #3 [85%] Another Refund Prompt
      Tags: cartwheel, testing

# Copy and paste prompt #1:
$ pget 1
```

### Example 2: Add & Tag Custom Prompt
```bash
$ padd "Debug this Python error: TypeError on line 42"
# Or interactive:
$ pcache
# Choose: 4 (Add) → Enter text → Add tags

# Later search:
$ psearch "TypeError"
```

### Example 3: Organize by Tags
```bash
# File: my_homework.txt
[name: HW1 Refund Test]
[tags: homework, cartwheel, hw1]
Can I get a refund for order 4455?
---
[name: HW1 Auth Test]
[tags: homework, cartwheel, hw1]
Show me order 4127.
---

# Import:
$ pimport my_homework.txt

# Later search by tag:
$ psearch "hw1"
```

## Fuzzy Matching Explained

Fuzzy matching finds similar text even if it's not exact:
- `psearch "refund"` finds: "refund", "return", "refunds", "refund request"
- `psearch "python"` finds: "Python", "python", "PyThon", "pythonic"

**Threshold** determines how strict:
- Default: 60% match required
- Higher threshold (80%): stricter matching
- Lower threshold (40%): more results

Use with `prompt_cache.py` directly for control:
```bash
python3 prompt_cache.py --search "query" --threshold 70
```

## Troubleshooting

**Q: "No module named fuzzywuzzy"**
```bash
pip install fuzzywuzzy python-Levenshtein
```

**Q: "command not found: phelp"**
```bash
source ~/.prompt_cache_setup
# Add to ~/.zshrc or ~/.bashrc permanently
```

**Q: "No matches found"**
```bash
# Try lower threshold:
python3 prompt_cache.py --search "keyword" --threshold 40

# Or list all:
plist
```

**Q: Lost my prompts?**
```bash
# They're at: ~/.copilot/prompt_cache/prompts.json
cat ~/.copilot/prompt_cache/prompts.json

# Backup first:
pexport ~/backup.json json
```

## Tips

1. **Use consistent tags** — Makes searching easier
2. **Name prompts descriptively** — First 50 chars appear in lists
3. **Backup regularly** — Export as JSON monthly
4. **Search by tags** — Tags are searchable too
5. **Most-used prompts sort first** — Access count tracked

## What's Included

| File | Purpose |
|------|---------|
| `prompt_cache.py` | Full-featured CLI (advanced) |
| `quick_prompt.py` | Simplified CLI (beginner) |
| `sample_prompts.txt` | 10 example prompts to import |
| `PROMPT_CACHE_GUIDE.md` | Detailed guide (full reference) |
| `~/.prompt_cache_setup` | Shell aliases & functions |

## Next Steps

1. ✅ Run `pip install fuzzywuzzy python-Levenshtein`
2. ✅ Try: `python3 quick_prompt.py`
3. ✅ Import: `pimport sample_prompts.txt` (if using aliases)
4. ✅ Search: `psearch refund`
5. ✅ Read: `PROMPT_CACHE_GUIDE.md` for advanced features

---

**That's it!** You now have a searchable, persistent prompt library. Start using it today! 🎉
