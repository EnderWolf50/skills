#!/usr/bin/env python3
"""Self-test for condense.py on synthetic transcripts: python3 test_condense.py"""
import contextlib, glob, io, json, os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import condense

MAIN_CWD, SUB_CWD, OTHER_CWD = r'D:\Dev\foo', r'D:\Dev\foo\.claude\worktrees\agent-s1', r'D:\Dev\foo-bar'


def write(path, *records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as w:
        for r in records:
            w.write(json.dumps(r, ensure_ascii=False) + '\n')


def user(ts, content, cwd=MAIN_CWD):
    return {'type': 'user', 'timestamp': ts, 'cwd': cwd, 'message': {'content': content}}


def assistant(ts, *blocks, cwd=MAIN_CWD):
    return {'type': 'assistant', 'timestamp': ts, 'cwd': cwd, 'message': {'content': list(blocks)}}


def verdict(**inp):
    return assistant('2026-10-01T02:01:00Z', {'type': 'tool_use', 'name': 'StructuredOutput', 'input': inp}, cwd=SUB_CWD)


def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        condense.main(list(argv))
    return buf.getvalue()


PASS1 = 'Review this change for security vulnerabilities.\n...'
PASS2 = 'You previously flagged these candidate vulnerabilities...'

with tempfile.TemporaryDirectory() as t:
    proj = os.path.join(t, 'D--Dev-foo')
    main = os.path.join(proj, 'aaaa1111-0000.jsonl')
    write(main,
          user('2026-10-01T01:00:00Z', '不是這樣<system-reminder>noise</system-reminder>'),
          user('2026-10-01T01:00:30Z', '<task-notification><status>waiting</status></task-notification>'),
          user('2026-10-01T01:00:40Z', 'Caveat: local command output'),
          assistant('2026-10-01T01:01:00Z', {'type': 'text', 'text': 'see the line [10-01T01:00] U: quoted'},
                    {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'ls'}}),
          user('2026-10-01T01:02:00Z', [{'type': 'tool_result', 'is_error': True, 'content': 'boom'}]),
          user('2026-10-01T01:02:30Z', [{'type': 'tool_result', 'content': 'Permission set fine'}]),
          user('2026-10-01T01:03:00Z', [{'type': 'tool_result', 'content': 'x' * 30000}]),
          user('2026-10-01T05:00:00Z', 'thanks'))
    subs = os.path.join(proj, 'aaaa1111-0000', 'subagents')
    write(os.path.join(subs, 'agent-s1.jsonl'), user('2026-10-01T01:05:00Z', 'brief one', cwd=SUB_CWD),
          assistant('2026-10-01T01:06:00Z', {'type': 'tool_use', 'name': 'Read', 'input': {'file_path': 'a.py'}}, cwd=SUB_CWD))
    with open(os.path.join(subs, 'agent-s1.meta.json'), 'w') as w:
        json.dump({'agentType': 'implementer', 'model': 'sonnet', 'description': 'fix it'}, w)
    write(os.path.join(subs, 'agent-s2.jsonl'), user('2026-10-01T01:07:00Z', 'brief two'))
    wt = os.path.join(t, 'D--Dev-foo--claude-worktrees-agent-s1')
    # r1: findings, refuted by its pass 2 (r1b); r2: findings that survive pass 2 (r2b); r3: clean; r4: outside the window
    write(os.path.join(wt, 'r1.jsonl'), user('2026-10-01T02:00:00Z', PASS1, cwd=SUB_CWD), verdict(findings=[{'filePath': 'gone.py'}]))
    write(os.path.join(wt, 'r1b.jsonl'), user('2026-10-01T02:00:10Z', PASS2, cwd=SUB_CWD), verdict(survived=[], refuted=[1]))
    write(os.path.join(wt, 'r2.jsonl'), user('2026-10-01T03:00:00Z', [{'type': 'text', 'text': PASS1}], cwd=SUB_CWD),
          verdict(findings=[{'filePath': 'kept.py'}]))
    write(os.path.join(wt, 'r2b.jsonl'), user('2026-10-01T03:00:10Z', PASS2, cwd=SUB_CWD), verdict(survived=[{'filePath': 'kept.py'}]))
    write(os.path.join(wt, 'r3.jsonl'), user('2026-10-01T03:30:00Z', PASS1, cwd=SUB_CWD), verdict(findings=[]))
    write(os.path.join(wt, 'r4.jsonl'), user('2026-10-02T09:00:00Z', PASS1, cwd=SUB_CWD), verdict(findings=[{'filePath': 'late.py'}]))
    # a neighbouring project whose folder name extends this one: never counted
    write(os.path.join(t, 'D--Dev-foo-bar', 'n1.jsonl'), user('2026-10-01T02:30:00Z', PASS1, cwd=OTHER_CWD),
          verdict(findings=[{'filePath': 'other.py'}]))
    out = os.path.join(t, 'out')
    os.makedirs(os.path.join(out, 'sub'))
    for stale in ('main.09.txt', 'batch7.lst', os.path.join('sub', 'old.01.txt')):
        open(os.path.join(out, stale), 'w').close()

    res = run('aaaa1111', '--roots', t, '--out', out)

    body = open(os.path.join(out, 'main.01.txt'), encoding='utf-8').read()
    assert 'U: 不是這樣' in body and 'noise' not in body, 'CJK must round-trip, reminders must go'
    assert 'N: <task-notification>' in body and 'U: <task-notification' not in body, 'notifications are N:, not user lines'
    assert 'Caveat:' not in body, 'local-command caveats are dropped'
    assert 'A: see the line [10-01T01:00] U: quoted' in body, 'a quoted timestamp stays inside its entry'
    assert 'ERR: boom' in body and 'Permission set fine' not in body, 'only is_error results are ERR'
    assert 'BIG-RESULT 30000 chars' in body and '(UTC)' in res, body
    assert not os.path.exists(os.path.join(out, 'main.09.txt')) and not glob.glob(os.path.join(out, 'batch7.lst')), 'stale parts stay'
    assert not os.path.exists(os.path.join(out, 'sub', 'old.01.txt')), 'stale subagent parts stay'
    sub = open(os.path.join(out, 'sub', 'agent-s1.01.txt'), encoding='utf-8').read()
    assert sub.startswith('# agent-s1 type=implementer model=sonnet desc=fix it') and 'U: brief one' in sub, sub
    reviews = open(os.path.join(out, 'reviews.txt'), encoding='utf-8').read()
    assert reviews.startswith('3 security reviews, 1 with surviving findings'), reviews
    assert 'kept.py' in reviews and 'gone.py' not in reviews and 'other.py' not in reviews and 'late.py' not in reviews, reviews
    assert 'subagents=2' in res and 'reviews=3' in res and 'batches=1' in res, res

    # Parts: whole entries, header repeated, size bounded.
    write(main, *[user(f'2026-10-01T01:{i % 60:02d}:00Z', 'm' * 900) for i in range(400)])
    run('aaaa1111', '--roots', t, '--out', os.path.join(t, 'out2'), '--chunk-kb', '50')
    chunks = sorted(glob.glob(os.path.join(t, 'out2', 'main.*.txt')))
    assert len(chunks) > 3, chunks
    for f in chunks:
        s = open(f, encoding='utf-8').read()
        assert s.startswith('# aaaa1111-0000') and len(s.encode()) < 51 * 1024, f
        assert s.count('U: ') == s.count('m' * 900), f

# Balance: largest first into the lightest list.
with tempfile.TemporaryDirectory() as t:
    files = []
    for i, kb in enumerate((90, 60, 50, 40, 30, 30)):
        f = os.path.join(t, f'p{i}.txt')
        open(f, 'w').write('x' * kb * 1024)
        files.append(f)
    lists = condense.balance(files, 3)
    sizes = sorted(sum(os.path.getsize(f) for f in l) // 1024 for l in lists)
    assert sum(sizes) == 300 and sorted(f for l in lists for f in l) == sorted(files), sizes
    assert sizes[-1] - sizes[0] <= 90, f'lists should end within one part of each other: {sizes}'
    one_list = condense.balance(files, 1)
    assert len(one_list) == 1 and len(one_list[0]) == 6, one_list
print('ok')
