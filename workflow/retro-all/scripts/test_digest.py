#!/usr/bin/env python3
"""Self-test for digest.py on synthetic transcripts: python3 test_digest.py"""
import contextlib, io, json, os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import digest, ledger as ledger_py


def session(path, cwd, *msgs, mode='w'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as w:
        for m in msgs:
            w.write(json.dumps({'type': 'user', 'cwd': cwd, 'timestamp': '2026-10-01T00:00:00Z', 'message': {'content': m}}) + '\n')
        w.write(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Skill', 'input': {'skill': 'tdd'}}]}}) + '\n')


def run(*argv, mod=digest):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod.main(list(argv))
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
    session(f'{wsl}/-home-u-dev-foo/aaaa1111.jsonl', '/home/u/dev/foo', 'it grew: until sleep 5', mode='a')
    with open(f'{wsl}/-home-u-dev-foo/aaaa1111.jsonl', 'a') as w:
        w.write(json.dumps({'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'until pgrep msbuild; do sleep 1; done'}}]}}) + '\n')
    res = run('--roots', wsl, win, '--ledger', ledger, '--out', out)
    foo = open(f'{out}/foo.md').read()
    assert res.startswith('# 1 new') and 'it grew' in foo and 'continued from byte' in foo, res
    assert 'fix the bug' not in foo, 'a grown session is digested from where the last review stopped'

    # ledger.py: split an old single-file findings.md, index it, recheck against the grown session.
    with open(f'{ledger}/findings.md', 'w') as w:
        w.write('# Retro findings\n\n## F-1 Poll loop\nstatus: fixed\ncategory: correction\nevidence: x\nfix: y\n'
                'recheck: a wait loop\nrecheck-rg: until .*sleep\n\n## F-3 Other\nstatus: wontfix\ncategory: skill\n'
                'evidence: x\nfix: -\nrecheck: -\nrecheck-rg: grew\n')
    assert 'next id F-4' in run('--ledger', ledger, 'index', mod=ledger_py)
    idx = open(f'{ledger}/findings.md').read()
    assert '| [F-1](findings/F-1.md) | fixed | correction | Poll loop |' in idx and 'Next id: F-4' in idx, idx
    assert open(f'{ledger}/findings/F-3.md').read().startswith('# F-3 Other\n')
    res = run('--ledger', ledger, 'recheck', out, mod=ledger_py)
    assert 'F-1 (fixed) aaaa1111' in res and 'F-3' not in res.split('#')[0], 'only live findings are rechecked'
    assert 'pgrep' in res and 'it grew' not in res, 'recheck matches tool calls, not the user quoting the pattern'
    open(f'{ledger}/findings/F-5.md', 'w').write('# F-5 Taken\nstatus: open\ncategory: skill\n')
    assert run('--ledger', ledger, 'new', 'navigation', 'Lost file', mod=ledger_py).rstrip().endswith('F-6.md')
    assert open(f'{ledger}/findings/F-6.md').read().startswith('# F-6 Lost file\nstatus: open\ncategory: navigation\n')
    open(f'{ledger}/findings/F-9.md', 'w').close()   # claimed by a concurrent `new`, not yet written
    assert run('--ledger', ledger, 'new', 'skill', 'a | b', mod=ledger_py).rstrip().endswith('F-7.md')
    assert '| a \\| b |' in open(f'{ledger}/findings.md').read(), 'a | in a title must not split the index row'
    os.remove(f'{ledger}/findings/F-9.md')
    other = os.path.join(t, 'other')
    os.makedirs(other)
    open(f'{other}/findings.md', 'w').write('# Retro findings\n\n## F-1 From WSL\nstatus: open\ncategory: skill\n')
    open(f'{other}/sessions.tsv', 'w').write('zzzz0000\t/x.jsonl\t9\t2026-10-01\n')
    res = run('--ledger', ledger, 'import', other, mod=ledger_py)
    assert 'F-1 -> F-8: From WSL' in res and 'imported-from: F-1' in open(f'{ledger}/findings/F-8.md').read(), res
    assert 'zzzz0000' in open(f'{ledger}/sessions.tsv').read()

    run('--mark', out, '--ledger', ledger)
    assert len(open(f'{ledger}/sessions.tsv').read().splitlines()) == 7, 'a re-marked session keeps one row (6 + the imported one)'
    assert '# 1 new' in run('--roots', wsl, win, '--ledger', ledger, '--out', out, '--all', '--session', 'bbbb')
    assert '# 6 new' in run('--all', '--roots', wsl, win, '--ledger', ledger, '--out', out)

assert digest.bucket('C:\\Users\\k\\.local\\share\\chezmoi.wt\\linux-tools') == 'chezmoi'
assert digest.bucket('D:\\Dev\\weedwolf-wt\\t4') == 'weedwolf'
assert digest.bucket('/home/k/.t3/scratch/2026-10-09-x') == 'scratch'
assert digest.bucket('/home/k') == 'home' and digest.bucket('C:\\Users\\k') == 'home'
unc = '\\\\wsl.localhost\\Ubuntu'
assert digest.wsl_prefix(unc + '\\home\\k\\.claude\\projects\\-home-k\\a.jsonl') == unc
if os.name == 'nt':
    assert digest.to_local('/home/k/dev', unc) == unc + '\\home\\k\\dev' and digest.to_local('/mnt/d/Dev/x') == 'D:\\Dev\\x'
else:
    assert digest.to_local('D:\\Dev\\x') == '/mnt/d/Dev/x' and digest.to_local('/home/k/dev', unc) == '/home/k/dev'
print('ok')
