#!/usr/bin/env python3
"""Self-test for digest.py on synthetic transcripts: python3 test_digest.py"""
import contextlib, io, json, os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import digest


def session(path, cwd, *msgs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as w:
        for m in msgs:
            w.write(json.dumps({'type': 'user', 'cwd': cwd, 'timestamp': '2026-10-01T00:00:00Z', 'message': {'content': m}}) + '\n')
        w.write(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Skill', 'input': {'skill': 'tdd'}}]}}) + '\n')


def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        digest.main(list(argv))
    return buf.getvalue()


with tempfile.TemporaryDirectory() as t:
    wsl, win, ledger, out = (os.path.join(t, x) for x in ('wsl', 'win', 'ledger', 'out'))
    session(f'{wsl}/-home-u-dev-foo/aaaa1111.jsonl', '/home/u/dev/foo', 'fix the bug')
    session(f'{wsl}/-home-u--t3-worktrees-foo-t3-1/bbbb2222.jsonl', '/home/u/.t3/worktrees/foo/t3-1', 'ship it')
    session(f'{wsl}/-home-u-dev-foo--claude-worktrees-agent-x/cccc3333.jsonl', '/home/u/dev/foo/.claude/worktrees/agent-x', 'subagent brief')
    session(f'{wsl}/-home-u-dev-foo/dddd4444.jsonl', '/home/u/dev/foo', 'Review this change for security vulnerabilities.\n...')
    session(f'{wsl}/-tmp-t3code-claude-title-x/eeee5555.jsonl', '/tmp/t3code-claude-title-x', 'title me')
    session(f'{wsl}/-home-u-learning-bar-practice-x/ffff6666.jsonl', '/home/u/learning/bar/practice/x', 'hi')
    session(f'{wsl}/-home-u-dev-foo/gggg7777.jsonl', '/home/u/dev/foo', 'short')
    session(f'{win}/D--Dev-foo/gggg7777.jsonl', 'D:\\Dev\\foo', 'the longer windows copy of the same session')

    res = run('--roots', wsl, win, '--ledger', ledger, '--out', out)
    foo = open(f'{out}/foo.md').read()
    assert 'sessions=4' in res and 'bar\tsessions=1' in res, res
    assert 'fix the bug' in foo and 'ship it' in foo and 'subagent brief' in foo, foo
    assert 'security' not in foo and 'title me' not in res, 'review sub-session or title dir leaked'
    assert 'longer windows copy' in foo and 'U: short' not in foo, 'dedupe should keep the larger transcript'
    assert "skills=['tdd']" in foo

    run('--mark', out, '--ledger', ledger)
    assert len(open(f'{ledger}/sessions.tsv').read().splitlines()) == 6
    assert run('--roots', wsl, win, '--ledger', ledger, '--out', out).startswith('# 0 new'), 'reviewed sessions must be skipped'
    session(f'{wsl}/-home-u-dev-foo/aaaa1111.jsonl', '/home/u/dev/foo', 'fix the bug', 'it grew')
    res = run('--roots', wsl, win, '--ledger', ledger, '--out', out)
    assert res.startswith('# 1 new') and 'it grew' in open(f'{out}/foo.md').read(), res
    assert '# 6 new' in run('--all', '--roots', wsl, win, '--ledger', ledger, '--out', out)

assert digest.bucket('C:\\Users\\k\\.local\\share\\chezmoi.wt\\linux-tools') == 'chezmoi'
assert digest.bucket('D:\\Dev\\weedwolf-wt\\t4') == 'weedwolf'
assert digest.bucket('/home/k/.t3/scratch/2026-10-09-x') == 'scratch'
assert digest.bucket('/home/k') == 'home' and digest.bucket('C:\\Users\\k') == 'home'
print('ok')
