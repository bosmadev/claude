#!/usr/bin/env python3
"""Repair corrupted history.json by truncating at first valid JSON boundary."""
import json
import os
import shutil

history_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'history.json')
history_path = os.path.normpath(history_path)
backup_path = history_path + '.bak'

print(f"Reading: {history_path}")
with open(history_path, 'r', encoding='utf-8') as f:
    content = f.read()

print(f"File size: {len(content)} chars")

# Try to parse — find the valid JSON boundary
decoder = json.JSONDecoder()
try:
    obj, end_idx = decoder.raw_decode(content)
    print(f"Valid JSON ends at char: {end_idx}")
    
    # Backup the original
    shutil.copy2(history_path, backup_path)
    print(f"Backup saved to: {backup_path}")
    
    # Write only the valid portion
    valid_json = json.dumps(obj, indent=2, ensure_ascii=False)
    tmp_path = history_path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        f.write(valid_json)
    os.replace(tmp_path, history_path)
    print(f"Repaired! Written {len(valid_json)} chars")
    
    # Verify
    with open(history_path, 'r', encoding='utf-8') as f:
        verify = json.load(f)
    replies = verify.get('replies', [])
    daily = verify.get('daily_counts', {})
    print(f"Verified OK: {len(replies)} replies, daily_counts: {daily}")
except Exception as e:
    print(f"ERROR: {e}")
