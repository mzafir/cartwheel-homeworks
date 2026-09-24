# Prompt Cache System — Setup & Usage Guide

A powerful prompt management system with fuzzy search, file import, and quick recall.

## Quick Start

### 1. Install Dependencies
```bash
pip install fuzzywuzzy python-Levenshtein
```

### 2. Import Sample Prompts
```bash
python3 prompt_cache.py --import sample_prompts.txt
```

### 3. Search for Prompts
```bash
python3 prompt_cache.py --search "refund"
```

### 4. Retrieve a Prompt
```bash
python3 prompt_cache.py --get 1
```

---

## Features

### 📝 Add Prompts
```bash
# Add a simple prompt
python3 prompt_cache.py --add "Your prompt text here"

# Add with name and tags
python3 prompt_cache.py --add "Your prompt text" --name "My Prompt" --tags "tag1,tag2,tag3"
```

### 🔍 Fuzzy Search
```bash
# Search by content (default threshold: 60%)
python3 prompt_cache.py --search "refund"

# Stricter matching (threshold 80%)
python3 prompt_cache.py --search "payment" --threshold 80

# Looser matching (threshold 40%)
python3 prompt_cache.py --search "help" --threshold 40
```

**Fuzzy matching scores:**
- Searches by prompt text, name, AND tags
- Returns best matches first (sorted by score)
- Useful for finding similar prompts without exact keywords

### 📚 List All Prompts
```bash
# List top 50 (sorted by most used)
python3 prompt_cache.py --list

# Show top 100
python3 prompt_cache.py --list --limit 100
```

### 📤 Import Prompts from File
```bash
# From sample file
python3 prompt_cache.py --import sample_prompts.txt

# From your own file
python3 prompt_cache.py --import my_prompts.txt
```

**File Format:**
```
[name: My Prompt Name]
[tags: tag1, tag2, tag3]
The actual prompt text goes here.
It can span multiple lines.
---
[name: Another Prompt]
[tags: tag1, tag2]
More prompt text...
---
```

Each prompt is separated by `---` on its own line.

### 📥 Export Prompts
```bash
# Export as full format (with metadata)
python3 prompt_cache.py --export my_backup.txt

# Export as JSON
python3 prompt_cache.py --export my_backup.json --export-format json

# Export text only
python3 prompt_cache.py --export prompts_text_only.txt --export-format text_only
```

### 🗑️ Delete & Clear
```bash
# Delete a specific prompt
python3 prompt_cache.py --delete 5

# Clear all prompts (warns before confirming)
python3 prompt_cache.py --clear
```

---

## Database Location

Prompts are stored in:
```
~/.copilot/prompt_cache/prompts.json
```

This location ensures:
- Persistent storage across sessions
- Easy backup (copy the JSON file)
- Portable (same location on all machines)

---

## Python API Usage

Use in your own scripts:

```python
from prompt_cache import PromptCache

# Initialize
cache = PromptCache()

# Add prompt
prompt = cache.add("Your prompt text", tags=["tag1", "tag2"], name="Prompt Name")
print(f"Added: {prompt['id']}")

# Search
results = cache.search("refund", threshold=60)
for result in results:
    print(f"  #{result['id']} [{result['score']}%]: {result['name']}")

# Get by ID
prompt = cache.get_by_id(1)
print(prompt["text"])

# List all
all_prompts = cache.list_all(limit=50)

# Import
count = cache.import_from_file(Path("sample_prompts.txt"))
print(f"Imported {count} prompts")

# Export
cache.export_to_file(Path("backup.txt"))
```

---

## Integration with Copilot Chat

### VS Code Workflow

1. **Open prompt cache when needed:**
   ```bash
   python3 prompt_cache.py --search "your keywords"
   ```

2. **Copy prompt ID and retrieve:**
   ```bash
   python3 prompt_cache.py --get 3
   ```

3. **Paste into Copilot chat** or use directly in terminal

### Creating a Shell Alias

Add to `~/.zshrc` or `~/.bashrc`:
```bash
alias prompts='python3 /path/to/prompt_cache.py'
alias psearch='python3 /path/to/prompt_cache.py --search'
```

Then use:
```bash
psearch "refund"
prompts --list
prompts --get 5
```

---

## Tag Strategy

Organize prompts with consistent tags for better discoverability:

### Suggested Tag Categories

**By Domain:**
- `cartwheel`, `python`, `javascript`, `devops`, `database`, `api`, etc.

**By Purpose:**
- `homework`, `testing`, `debugging`, `review`, `design`, `optimization`

**By Complexity:**
- `quick`, `detailed`, `comprehensive`, `minimal`

**By Status:**
- `template`, `ready-to-use`, `wip`, `deprecated`

### Example Tags
- `cartwheel,refund,homework,testing` — Cartwheel-specific refund test
- `python,debugging,analysis` — Python debugging guidance
- `code-review,quality,process` — Code review checklist
- `architecture,design,scaling` — System design template

---

## Tips & Tricks

### 1. Organize by Use Case
Create separate import files for different contexts:
```bash
# For Cartwheel homework
python3 prompt_cache.py --import cartwheel_prompts.txt

# For general coding tasks
python3 prompt_cache.py --import coding_prompts.txt
```

### 2. Backup Your Prompts
```bash
# Regular backups
python3 prompt_cache.py --export ~/backups/prompts_$(date +%Y%m%d).json --export-format json
```

### 3. Track Most-Used Prompts
```bash
# List shows usage count
python3 prompt_cache.py --list
```

The `Uses` counter increases each time you retrieve a prompt with `--get`.

### 4. Batch Import from Email/Docs
1. Copy prompts from various sources
2. Format into `sample_prompts.txt` with `---` separators
3. Import once: `python3 prompt_cache.py --import sample_prompts.txt`

---

## Troubleshooting

### Issue: "fuzzywuzzy not installed"
```bash
pip install fuzzywuzzy python-Levenshtein
```

### Issue: Database locked
This shouldn't happen with normal usage, but if it does:
```bash
# Delete the lock file (if one exists)
rm ~/.copilot/prompt_cache/.lock
```

### Issue: Need to migrate database
```bash
# Export all prompts as JSON
python3 prompt_cache.py --export prompts_backup.json --export-format json

# Clear cache
python3 prompt_cache.py --clear

# Manually edit JSON or re-import from text
```

---

## Examples

### Example 1: Homework Prompts
```bash
# Import HW prompts
python3 prompt_cache.py --import sample_prompts.txt

# Search for refund-related
python3 prompt_cache.py --search "refund"

# Retrieve by ID
python3 prompt_cache.py --get 1
```

### Example 2: Quick Coding Template
```bash
# Search for code review
python3 prompt_cache.py --search "code review"

# Get the result and copy to chat
python3 prompt_cache.py --get 4
```

### Example 3: Backup & Restore
```bash
# Backup before cleanup
python3 prompt_cache.py --export ~/prompts_backup.json --export-format json

# View file to pick what to keep
cat ~/prompts_backup.json

# Clear and re-import selectively
python3 prompt_cache.py --clear
python3 prompt_cache.py --import curated_prompts.txt
```

---

## File Format Reference

### Full Format (with metadata)
```
[name: Display Name]
[tags: tag1, tag2, tag3]
Prompt text content here...
Can be multiple lines...
---
[name: Another Prompt]
Minimal format (no tags)...
---
```

### JSON Format (in database)
```json
[
  {
    "id": 1,
    "name": "Prompt Name",
    "text": "Full prompt text",
    "tags": ["tag1", "tag2"],
    "created_at": "2026-09-17T10:30:00",
    "uses": 5
  }
]
```

---

## Next Steps

1. ✅ Install dependencies
2. ✅ Import `sample_prompts.txt`
3. ✅ Try searching: `python3 prompt_cache.py --search "refund"`
4. ✅ Create alias in shell config
5. ✅ Build your own prompt library

**Happy prompting! 🚀**
