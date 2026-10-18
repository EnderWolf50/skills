#!/usr/bin/env python3
"""Self-test for condense.py on synthetic transcripts: python3 test_condense.py"""
import contextlib, glob, io, json, os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import condense


def write(path, *records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as w:
        for r in records:
            w.write(json.dumps(r) + '\n')


def user(ts, content):
    return {'type': 'user', 'timestamp': ts, 'message': {'content': content}}


def assistant(ts, *blocks):
    return {'type': 'assistant', 'timestamp': ts, 'message': {'content': list(blocks)}}


with tempfile.TemporaryDirectory() as t:
    proj = os.path.join(t, 'D--Dev-foo')
    main = os.path.join(proj, 'aaaa1111-0000.jsonl')
    write(main,
          user('2026-10-01T01:00:00Z', 'fix the bug<system-reminder>noise</system-reminder>'),
          assistant('2026-10-01T01:01:00Z', {'type': 'text', 'text': 'On it.'},
                    {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'ls'}}),
          user('2026-10-01T01:02:00Z', [{'type': 'tool_result', 'is_error': True, 'content': 'boom'}]),
          user('2026-10-01T01:03:00Z', [{'type': 'tool_result', 'content': 'x' * 30000}]),
          user('2026-10-01T05:00:00Z', 'thanks'))
    write(os.path.join(proj, 'aaaa1111-0000', 'subagents', 'agent-s1.jsonl'),
          user('2026-10-01T01:05:00Z', 'brief one'),
          assistant('2026-10-01T01:06:00Z', {'type': 'tool_use', 'name': 'Read', 'input': {'file_path': 'a.py'}}))
    with open(os.path.join(proj, 'aaaa1111-0000', 'subagents', 'agent-s1.meta.json'), 'w') as w:
        json.dump({'agentType': 'implementer', 'model': 'sonnet', 'description': 'fix it'}, w)
    write(os.path.join(proj, 'aaaa1111-0000', 'subagents', 'agent-s2.jsonl'), user('2026-10-01T01:07:00Z', 'brief two'))
    review = [user('2026-10-01T02:00:00Z', 'Review this change for security vulnerabilities.\n...')]
    write(os.path.join(t, 'D--Dev-foo--claude-worktrees-agent-s1', 'r1.jsonl'), *review,
          assistant('2026-10-01T02:01:00Z', {'type': 'tool_use', 'name': 'StructuredOutput', 'input': {'findings': [{'filePath': 'a.py'}]}}))
    write(os.path.join(t, 'D--Dev-foo--claude-worktrees-agent-s1', 'r2.jsonl'), *review,
          assistant('2026-10-01T02:01:00Z', {'type': 'tool_use', 'name': 'StructuredOutput', 'input': {'findings': []}}))
    write(os.path.join(t, 'D--Dev-foo--claude-worktrees-agent-s1', 'r3.jsonl'),
          user('2026-10-02T09:00:00Z', 'Review this change for security vulnerabilities.\nlater'))   # outside the window
    out = os.path.join(t, 'out')

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        condense.main(['aaaa1111', '--roots', t, '--out', out, '--batches', '2'])
    res = buf.getvalue()

    body = open(os.path.join(out, 'main.01.txt'), encoding='utf-8').read()
    assert 'U: fix the bug' in body and 'noise' not in body, body
    assert 'A: On it.' in body and 'T Bash: {"command": "ls"}' in body, body
    assert 'ERR: boom' in body and 'BIG-RESULT 30000 chars' in body, body
    sub = open(os.path.join(out, 'sub', 'agent-s1.01.txt'), encoding='utf-8').read()
    assert sub.startswith('# agent-s1 type=implementer model=sonnet desc=fix it') and 'U: brief one' in sub, sub
    lists = sorted(glob.glob(os.path.join(out, 'batch*.lst')))
    assert len(lists) == 2 and all(open(f).read().strip() for f in lists), lists
    reviews = open(os.path.join(out, 'reviews.txt'), encoding='utf-8').read()
    assert reviews.startswith('2 security-review sub-sessions, 1 with findings') and 'a.py' in reviews, reviews
    assert 'subagents=2' in res and 'reviews=2' in res, res

    # A long session splits on entry boundaries and repeats the header in every part.
    write(main, *[user(f'2026-10-01T01:{i % 60:02d}:00Z', 'm' * 900) for i in range(400)])
    with contextlib.redirect_stdout(io.StringIO()):
        condense.main(['aaaa1111', '--roots', t, '--out', os.path.join(t, 'out2'), '--chunk-kb', '50'])
    chunks = sorted(glob.glob(os.path.join(t, 'out2', 'main.*.txt')))
    assert len(chunks) > 3, chunks
    for f in chunks:
        s = open(f, encoding='utf-8').read()
        assert s.startswith('# aaaa1111-0000') and len(s.encode()) < 55 * 1024, f
        assert s.count('U: ') == s.count('m' * 900), f   # no message cut in half
print('ok')
