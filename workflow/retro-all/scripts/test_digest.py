#!/usr/bin/env python3
"""Self-test for digest.py on synthetic transcripts: python3 test_digest.py"""
import contextlib, io, json, os, re, subprocess, sys, tempfile

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

# A WSL /mnt/<drive> cwd buckets like the same folder seen from Windows.
assert digest.bucket('/mnt/c/Users/k/learning/pstack/practice') == 'pstack' == digest.bucket('C:\\Users\\k\\learning\\pstack\\practice')
assert digest.bucket('/mnt/d/Dev/x') == digest.bucket('D:\\Dev\\x') == 'x'


def user(cwd, msg):
    return json.dumps({'type': 'user', 'cwd': cwd, 'timestamp': '2026-10-01T00:00:00Z', 'message': {'content': msg}}) + '\n'


with tempfile.TemporaryDirectory() as t:
    root, ledger, out = (os.path.join(t, x) for x in ('root', 'ledger', 'out'))
    os.makedirs(f'{root}/p')

    # A line still being written when digest runs is read on the next run, not skipped.
    tr = f'{root}/p/hhhh8888.jsonl'
    whole = user('Q:\\NoRepo\\Proj\\x', 'first') + user('Q:\\NoRepo\\Proj\\x', 'SECOND')
    open(tr, 'w', newline='\n').write(whole[:-20])
    run('--roots', root, '--ledger', ledger, '--out', out)
    run('--mark', out, '--ledger', ledger)
    open(tr, 'w', newline='\n').write(whole + user('Q:\\NoRepo\\Proj\\x', 'third'))
    run('--roots', root, '--ledger', ledger, '--out', out)
    body = open(f'{out}/Proj.md', encoding='utf-8').read()
    assert 'SECOND' in body and 'third' in body and 'first' not in body, body

    # Buckets differing only in case share one digest file instead of overwriting each other.
    open(f'{root}/p/iiii9999.jsonl', 'w').write(user('q:\\norepo\\proj\\y', 'lower'))
    res = run('--all', '--roots', root, '--ledger', ledger, '--out', out)
    assert 'sessions=2' in res and res.count('files=') == 1, res

    # kb= counts bytes: 25 messages of 600 CJK characters are about 44 KB, not 14.
    open(f'{root}/p/jjjj0000.jsonl', 'w', encoding='utf-8').write(''.join(user('Q:\\Big\\cjk\\z', '字' * 600) for _ in range(25)))
    res = run('--all', '--roots', root, '--ledger', ledger, '--out', out, '--session', 'jjjj')
    kb = int(re.search(r'kb=(\d+)', res).group(1))
    assert kb == os.path.getsize(f'{out}/cjk.md') // 1024 and kb > 40, res

    # recheck survives a regex that does not compile and a transcript that is gone; a BOM and a
    # `status:` line in the notes do not break or override a finding.
    os.makedirs(f'{ledger}/findings')
    with open(f'{ledger}/findings/F-1.md', 'w', encoding='utf-8-sig') as w:
        w.write('# F-1 Bad regex\nstatus: open\ncategory: skill\nrecheck-rg: until (sleep\n\nNotes.\nstatus: wontfix\n')
    with open(f'{out}/pending.tsv', 'a') as w:
        w.write(f'kkkk1111\t{root}/p/gone.jsonl\t99\t0\n')
    res = run('--ledger', ledger, 'recheck', out, mod=ledger_py)
    assert 'F-1: recheck-rg does not compile' in res and 'kkkk1111: transcript unreadable' in res, res
    run('--ledger', ledger, 'index', mod=ledger_py)
    assert '| open | skill | Bad regex |' in open(f'{ledger}/findings.md').read()

    # A worktree whose .git file holds a relative gitdir resolves to its main checkout.
    os.makedirs(f'{t}/myrepo/.git/worktrees/feat')
    os.makedirs(f'{t}/myrepo/.worktrees/feat')
    open(f'{t}/myrepo/.worktrees/feat/.git', 'w').write('gitdir: ../../.git/worktrees/feat\n')
    assert os.path.basename(digest.git_root(f'{t}/myrepo/.worktrees/feat')) == 'myrepo'
    # A live worktree under .wt/<name> buckets by its repo, not by the folder name.
    os.makedirs(f'{t}/myrepo/.git/worktrees/other')
    os.makedirs(f'{t}/.wt/other')
    open(f'{t}/.wt/other/.git', 'w').write(f'gitdir: {t}/myrepo/.git/worktrees/other\n')
    assert digest.bucket(f'{t}/.wt/other') == 'myrepo'
    # A worktree of a bare <repo>.git buckets as <repo>.
    os.makedirs(f'{t}/proj.git/worktrees/x')
    os.makedirs(f'{t}/wx')
    open(f'{t}/wx/.git', 'w').write(f'gitdir: {t}/proj.git/worktrees/x\n')
    assert digest.bucket(f'{t}/wx') == 'proj'

    # Parts of a split bucket cannot overwrite a bucket named like a part (foo split in two, plus foo-1).
    os.makedirs(f'{t}/r/q')
    for sid, cwd in (('llll0001', 'foo'), ('llll0002', 'foo'), ('llll0003', 'foo-1')):
        open(f'{t}/r/q/{sid}.jsonl', 'w').write(''.join(user(f'Q:\\NoRepo\\{cwd}\\x', f'{sid} {i} ' + 'x' * 500) for i in range(3)))
    res = run('--all', '--roots', f'{t}/r', '--ledger', ledger, '--out', f'{t}/split', '--max-kb', '2')
    assert 'files=foo.part1.md,foo.part2.md' in res and 'files=foo-1.md' in res, res
    assert 'llll0003' not in open(f'{t}/split/foo.part1.md').read() + open(f'{t}/split/foo.part2.md').read()

    # new: a fresh ledger, a literal {id} in a title, and a blank title.
    assert '0 findings' in run('--ledger', f'{t}/fresh', 'index', mod=ledger_py)
    path = run('--ledger', f'{t}/fresh', 'new', 'skill', 'expand {id} here', mod=ledger_py).splitlines()[-1]
    assert open(path).read().startswith('# F-1 expand {id} here\n')
    try:
        run('--ledger', f'{t}/fresh', 'new', 'skill', ' ', mod=ledger_py)
        raise AssertionError('a blank title must be refused')
    except SystemExit as e:
        assert 'one non-empty line' in str(e)
    assert '1 findings' in run('--ledger', f'{t}/fresh', 'index', mod=ledger_py)

help_out = subprocess.run([sys.executable, '-B', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'user-msgs.py'), '--help'],
                          capture_output=True, text=True)
assert help_out.returncode == 0 and 'session-id-prefix' in help_out.stdout, help_out
print('ok')
