#!/usr/bin/env python3
"""Digest every Claude Code session on this machine into one markdown file per repo bucket.

  digest.py [--all] [--out DIR]   write DIR/<bucket>.md + DIR/pending.tsv, print one summary line per bucket
  digest.py --mark DIR            record DIR/pending.tsv in the ledger's sessions.tsv as reviewed

Sessions already in the ledger are skipped unless their transcript grew; --all ignores the ledger.
"""
import argparse, collections, datetime, glob, json, os, re, sys

HOME = os.path.expanduser('~')
ROOTS = [os.path.join(HOME, '.claude/projects'), '/mnt/c/Users/kerati/.claude/projects']
LEDGER = os.path.join(HOME, '.claude/retro')
# First user message of the security-guidance plugin's review sub-sessions (both its passes).
REVIEW_PREFIXES = ('Review this change for security vulnerabilities', 'You previously flagged these candidate vulnerabilities')
MAX_USER_MSGS, MAX_ERRS = 25, 6


def text(c):
    if isinstance(c, str):
        return c
    return '\n'.join(b.get('text', '') for b in c or [] if isinstance(b, dict) and b.get('type') == 'text')


def to_local(path):
    m = re.match(r'^([A-Za-z]):[\\/]*(.*)$', path)
    return f'/mnt/{m.group(1).lower()}/' + m.group(2).replace('\\', '/') if m else path


def git_root(path):
    """Main checkout of the repo holding path (a linked worktree resolves to its main checkout), or None."""
    p = to_local(path)
    while p and p not in ('/', HOME) and os.path.basename(p) != '':
        g = os.path.join(p, '.git')
        if os.path.isdir(g):
            return p
        if os.path.isfile(g):
            m = re.match(r'gitdir:\s*(.+)', open(g, errors='replace').read())
            if m and '/worktrees/' in m.group(1).replace('\\', '/'):
                return os.path.dirname(to_local(m.group(1).strip().replace('\\', '/').rsplit('/worktrees/', 1)[0]))
            return p
        p = os.path.dirname(p)
    return None


def bucket(cwd):
    """Repo name for a session's cwd, with worktrees folded into their repo."""
    parts = [x for x in re.split(r'[\\/]+', cwd or '') if x]
    low = [x.lower() for x in parts]
    for i, x in enumerate(low):
        nxt = low[i + 1] if i + 1 < len(low) else ''
        if x == '.claude' and nxt == 'worktrees' and i:
            return parts[i - 1]                      # <repo>/.claude/worktrees/<name>
        if x == '.t3' and nxt == 'worktrees' and i + 2 < len(parts):
            return parts[i + 2]                      # ~/.t3/worktrees/<repo>/<name>
        if x == '.t3' and nxt == 'scratch' or x in ('tmp', 'temp', 'scratch-workspaces'):
            return 'scratch'
        if x == '.wt' and nxt:
            return parts[i + 1]                      # .wt/<repo>
        if len(x) > 3 and x.endswith(('.wt', '-wt')):
            return parts[i][:-3]                     # <repo>.wt/<name>, <repo>-wt/<name>
    root = git_root(cwd or '')
    if root:
        return os.path.basename(root)
    # Not a git checkout: the second level below home or the drive root (learning/pstack/practice/x -> pstack).
    rel = parts[3:] if len(low) > 2 and low[1] == 'users' else parts[2:] if low[:1] == ['home'] else parts[1:]
    if not rel:
        return 'home'
    return (rel[1] if len(rel) > 1 else rel[0]).lstrip('.')


def read_session(path):
    users, errs, skills, tools = [], [], [], collections.Counter()
    ts = cwd = None
    turns = denied = 0
    for line in open(path, encoding='utf-8', errors='replace'):
        try:
            j = json.loads(line)
        except ValueError:
            continue
        if not isinstance(j, dict):
            continue
        ts = ts or j.get('timestamp')
        cwd = cwd or j.get('cwd')
        m = j.get('message') or {}
        if j.get('type') == 'user' and not j.get('isMeta') and not j.get('isSidechain'):
            c = m.get('content')
            if isinstance(c, list) and any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in c):
                for b in c:
                    if isinstance(b, dict) and b.get('type') == 'tool_result' and b.get('is_error'):
                        t = text(b.get('content'))
                        denied += 'denied' in t or 'rejected' in t
                        errs.append(t[:200].replace('\n', ' '))
                continue
            t = text(c).strip()
            if not t or t.startswith(('<local-command', 'Caveat:', '<task-notification')) or '<system-reminder>' in t[:30]:
                continue
            if not users and t.startswith(REVIEW_PREFIXES):
                return None
            t = re.sub(r'<command-message>.*?</command-message>', '', t, flags=re.S)
            users.append(t[:600].replace('\n', ' ⏎ '))
        elif j.get('type') == 'assistant':
            turns += 1
            for b in m.get('content') or []:
                if isinstance(b, dict) and b.get('type') == 'tool_use':
                    tools[b.get('name')] += 1
                    if b.get('name') == 'Skill':
                        skills.append((b.get('input') or {}).get('skill'))
    if not users:
        return None
    return dict(ts=ts or '', cwd=cwd or '', users=users, errs=errs, skills=skills, tools=tools, turns=turns, denied=denied)


def render(sid, path, s):
    out = [f"\n## {s['ts'][:16]} {os.path.basename(os.path.dirname(path))} {sid[:8]}\n",
           f"cwd={s['cwd']} turns={s['turns']} tools={dict(s['tools'].most_common(8))} skills={s['skills']} "
           f"errors={len(s['errs'])} denied={s['denied']}\n"]
    out += [f'- U: {u}\n' for u in s['users'][:MAX_USER_MSGS]]
    if len(s['users']) > MAX_USER_MSGS:
        out.append(f"- ... {len(s['users']) - MAX_USER_MSGS} more user msgs; last: {s['users'][-1]}\n")
    out += [f'  ERR: {e}\n' for e in s['errs'][:MAX_ERRS]]
    return ''.join(out)


def read_ledger(ledger):
    rows = {}
    p = os.path.join(ledger, 'sessions.tsv')
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            f = line.rstrip('\n').split('\t')
            if len(f) >= 3 and f[2].isdigit():
                rows[f[0]] = f
    return rows


def find_sessions(roots):
    """session id -> transcript path; a session id under two roots keeps the larger transcript."""
    found = {}
    for root in roots:
        for f in glob.glob(os.path.join(root, '*', '*.jsonl')):
            if 'claude-title' in os.path.basename(os.path.dirname(f)):
                continue
            sid = os.path.basename(f)[:-6]
            if sid not in found or os.path.getsize(f) > os.path.getsize(found[sid]):
                found[sid] = f
    return found


def digest(args):
    seen = {} if args.all else read_ledger(args.ledger)
    os.makedirs(args.out, exist_ok=True)
    buckets, pending = collections.defaultdict(list), []
    for sid, path in find_sessions(args.roots).items():
        size = os.path.getsize(path)
        if sid in seen and size <= int(seen[sid][2]):
            continue
        pending.append(f'{sid}\t{path}\t{size}\n')
        s = read_session(path)
        if s:
            buckets[bucket(s['cwd'])].append((s['ts'], render(sid, path, s)))
    with open(os.path.join(args.out, 'pending.tsv'), 'w', encoding='utf-8') as w:
        w.writelines(pending)
    summary = []
    for b, blocks in buckets.items():
        blocks.sort()
        parts, cur = [], ''
        for _, blk in blocks:
            if cur and len(cur) + len(blk) > args.max_kb * 1024:
                parts.append(cur)
                cur = ''
            cur += blk
        parts.append(cur)
        names = [f'{b}.md'] if len(parts) == 1 else [f'{b}-{i}.md' for i in range(1, len(parts) + 1)]
        for n, body in zip(names, parts):
            with open(os.path.join(args.out, n), 'w', encoding='utf-8') as w:
                w.write(body)
        summary.append((sum(map(len, parts)), f"{b}\tsessions={len(blocks)}\tkb={sum(map(len, parts)) // 1024}\tfiles={','.join(names)}"))
    print(f'# {len(pending)} new or grown sessions; digests in {args.out}')
    for _, line in sorted(summary, reverse=True):
        print(line)


def mark(args):
    rows = read_ledger(args.ledger)
    now = datetime.datetime.now().isoformat(timespec='seconds')
    for line in open(os.path.join(args.mark, 'pending.tsv'), encoding='utf-8'):
        sid, path, size = line.rstrip('\n').split('\t')
        rows[sid] = [sid, path, size, now]
    os.makedirs(args.ledger, exist_ok=True)
    p = os.path.join(args.ledger, 'sessions.tsv')
    with open(p + '.tmp', 'w', encoding='utf-8') as w:
        w.writelines('\t'.join(r) + '\n' for r in sorted(rows.values(), key=lambda r: r[0]))
    os.replace(p + '.tmp', p)
    print(f'{len(rows)} sessions in {p}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--all', action='store_true', help='ignore the ledger and digest every session')
    ap.add_argument('--out', default=os.path.join(LEDGER, 'digests', datetime.date.today().isoformat()))
    ap.add_argument('--mark', metavar='DIR', help="record DIR/pending.tsv as reviewed")
    ap.add_argument('--ledger', default=LEDGER)
    ap.add_argument('--roots', nargs='+', default=[r for r in ROOTS if os.path.isdir(r)])
    ap.add_argument('--max-kb', type=int, default=150, help='split a bucket into parts above this size')
    args = ap.parse_args(argv)
    mark(args) if args.mark else digest(args)


if __name__ == '__main__':
    sys.exit(main())
