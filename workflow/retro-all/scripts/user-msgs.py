#!/usr/bin/env python3
"""Print a session's own user messages: user-msgs.py <session-id-prefix> [max-chars, default 300]"""
import glob, json, os, sys

ROOTS = [os.path.expanduser('~/.claude/projects'), '/mnt/c/Users/kerati/.claude/projects']


def text(c):
    if isinstance(c, str):
        return c
    if any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in c or []):
        return ''
    return '\n'.join(b.get('text', '') for b in c or [] if isinstance(b, dict) and b.get('type') == 'text')


if len(sys.argv) < 2:
    sys.exit(__doc__)
sid, width = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 300
files = [f for r in ROOTS for f in glob.glob(f'{r}/*/{sid}*.jsonl')]
if not files:
    sys.exit(f'no transcript for {sid}')
for f in files:
    print('#', f)
    for line in open(f, encoding='utf-8', errors='replace'):
        try:
            j = json.loads(line)
        except ValueError:
            continue
        if not isinstance(j, dict) or j.get('type') != 'user' or j.get('isMeta') or j.get('isSidechain'):
            continue
        t = text((j.get('message') or {}).get('content')).strip()
        if t and not t.startswith(('<task-notification', '<local-command', 'Caveat')):
            print('-', j.get('timestamp', '')[:16], t[:width].replace('\n', ' ⏎ '))
