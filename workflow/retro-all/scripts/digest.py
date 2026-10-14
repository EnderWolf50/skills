#!/usr/bin/env python3
"""Digest every Claude Code session on this machine into one markdown file per repo bucket.

  digest.py [--all] [--session ID8] [--out DIR]   write DIR/<bucket>.md + DIR/pending.tsv, print one summary line per bucket
  digest.py --mark DIR                            record DIR/pending.tsv in the ledger's sessions.tsv as reviewed

Sessions already in the ledger are skipped unless their transcript grew, and a grown one is digested
from where the last review stopped; --all ignores the ledger.
"""
import argparse, collections, datetime, glob, json, os, re, subprocess, sys

HOME = os.path.expanduser('~')


def wsl_distros():
    try:
        out = subprocess.run(['wsl.exe', '-l', '-q'], capture_output=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return out.decode('utf-16-le', errors='replace').replace('\0', '').split()


WINDOWS_SIDE = [] if os.name == 'nt' else [os.path.dirname(p) for p in glob.glob('/mnt/c/Users/*/.claude/projects')]


def roots():
    """Both sides of a Windows + WSL machine, whichever side runs this: Windows reads WSL through \\\\wsl.localhost,
    WSL reads Windows through /mnt/c. A function, not a constant: reading a stopped distro boots it, so only the
    commands that scan sessions pay for it."""
    if os.name == 'nt':
        other = [p for d in wsl_distros() for p in glob.glob(rf'\\wsl.localhost\{d}\home\*\.claude\projects')]
    else:
        other = [os.path.join(c, 'projects') for c in WINDOWS_SIDE]
    return [os.path.join(HOME, '.claude', 'projects')] + other


# One ledger per machine, on the Windows side when there is one, so both sides read and write the same file.
# ponytail: the first Windows user with a ~/.claude wins; pass --ledger on a machine shared by several.
LEDGER = os.path.join((WINDOWS_SIDE or [os.path.join(HOME, '.claude')])[0], 'retro')
# First user message of the security-guidance plugin's review sub-sessions (both its passes).
REVIEW_PREFIXES = ('Review this change for security vulnerabilities', 'You previously flagged these candidate vulnerabilities')
MAX_USER_MSGS, MAX_ERRS = 25, 6


def utf8_safe_stdout():
    """Replace what the console's code page cannot show (cp950 has no ⏎) instead of crashing on it."""
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')


def text(c):
    if isinstance(c, str):
        return c
    return '\n'.join(b.get('text', '') for b in c or [] if isinstance(b, dict) and b.get('type') == 'text')


def to_local(path, wsl=''):
    """path as this side sees it; wsl is the \\\\wsl.localhost\\<distro> a WSL session's paths live under."""
    if os.name == 'nt':
        m = re.match(r'^/mnt/([a-z])/(.*)$', path)
        if m:
            return f'{m.group(1).upper()}:\\' + m.group(2).replace('/', '\\')
        return wsl + path.replace('/', '\\') if wsl and path.startswith('/') else path
    m = re.match(r'^([A-Za-z]):[\\/]*(.*)$', path)
    return f'/mnt/{m.group(1).lower()}/' + m.group(2).replace('\\', '/') if m else path


def wsl_prefix(transcript):
    """The \\\\wsl.localhost\\<distro> a transcript read from Windows lives under, or ''."""
    m = re.match(r'^(\\\\wsl\.localhost\\[^\\]+)', transcript)
    return m.group(1) if m else ''


def git_root(path, wsl=''):
    """Main checkout of the repo holding path (a linked worktree resolves to its main checkout), or None."""
    p = to_local(path, wsl)
    while p and p not in ('/', HOME) and os.path.basename(p) != '':
        g = os.path.join(p, '.git')
        if os.path.isdir(g):
            return p
        if os.path.isfile(g):
            m = re.match(r'gitdir:\s*(.+)', open(g, errors='replace').read())
            if not m:
                return p
            gd = m.group(1).strip()
            # Absolute (either side's form) or relative to the worktree (worktree.useRelativePaths).
            gd = to_local(gd.replace('\\', '/'), wsl) if re.match(r'^([\\/]|[A-Za-z]:)', gd) else os.path.normpath(os.path.join(p, gd))
            gd = gd.replace('\\', '/')
            return os.path.dirname(gd.rsplit('/worktrees/', 1)[0]) if '/worktrees/' in gd else p
        p = os.path.dirname(p)
    return None


def bucket(cwd, wsl=''):
    """Repo name for a session's cwd, with worktrees folded into their repo."""
    parts = [x for x in re.split(r'[\\/]+', cwd or '') if x]
    if len(parts) > 1 and parts[0] == 'mnt' and len(parts[1]) == 1:
        parts = [parts[1] + ':'] + parts[2:]         # /mnt/c/... reads like C:\... from either side
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
    root = git_root(cwd or '', wsl)
    if root:
        return os.path.basename(root)
    # Not a git checkout: the second level below home or the drive root (learning/pstack/practice/x -> pstack).
    rel = parts[3:] if len(low) > 2 and low[1] == 'users' else parts[2:] if low[:1] == ['home'] else parts[1:]
    if not rel:
        return 'home'
    return (rel[1] if len(rel) > 1 else rel[0]).lstrip('.')


def complete_lines(path, start, end=None):
    """(end offset of the last complete line, the lines) from byte start on, up to end when given.
    A line still being written is left for the next run instead of being recorded as read."""
    with open(path, 'rb') as f:
        f.seek(start)
        data = f.read() if end is None else f.read(max(0, end - start))
    data = data[:data.rfind(b'\n') + 1]
    return start + len(data), data.decode('utf-8', errors='replace').splitlines()


def read_session(path, offset=0):
    """(end offset, summary of the transcript's complete lines from byte offset on); the summary is None when they
    hold no user message."""
    users, errs, skills, tools = [], [], [], collections.Counter()
    ts = cwd = None
    turns = denied = 0
    end, lines = complete_lines(path, offset)
    for line in lines:
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
            if not users and not offset and t.startswith(REVIEW_PREFIXES):
                return end, None
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
        return end, None
    return end, dict(ts=ts or '', cwd=cwd or '', offset=offset, users=users, errs=errs, skills=skills, tools=tools, turns=turns, denied=denied)


def render(sid, path, s):
    cont = f" (continued from byte {s['offset']})" if s['offset'] else ''
    out = [f"\n## {s['ts'][:16]} {os.path.basename(os.path.dirname(path))} {sid[:8]}{cont}\n",
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
        for line in open(p, encoding='utf-8-sig'):
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
    buckets, pending, names = collections.defaultdict(list), [], {}
    for sid, path in find_sessions(args.roots or [r for r in roots() if os.path.isdir(r)]).items():
        if args.session and not sid.startswith(args.session):
            continue
        prev = int(seen[sid][2]) if sid in seen else 0
        if os.path.getsize(path) <= prev:
            continue
        end, s = read_session(path, prev)
        if end <= prev:
            continue
        pending.append(f'{sid}\t{path}\t{end}\t{prev}\n')
        if s:
            b = bucket(s['cwd'], wsl_prefix(path))
            # Bucket names become file names, which Windows compares without case.
            buckets[names.setdefault(b.lower(), b)].append((s['ts'], render(sid, path, s)))
    with open(os.path.join(args.out, 'pending.tsv'), 'w', encoding='utf-8', newline='\n') as w:
        w.writelines(pending)
    summary = []
    for b, blocks in buckets.items():
        blocks.sort()
        nbytes = lambda s: len(s.encode('utf-8'))
        parts, cur = [], ''
        for _, blk in blocks:
            if cur and nbytes(cur) + nbytes(blk) > args.max_kb * 1024:
                parts.append(cur)
                cur = ''
            cur += blk
        parts.append(cur)
        files = [f'{b}.md'] if len(parts) == 1 else [f'{b}-{i}.md' for i in range(1, len(parts) + 1)]
        for n, body in zip(files, parts):
            with open(os.path.join(args.out, n), 'w', encoding='utf-8', newline='\n') as w:
                w.write(body)
        size = sum(map(nbytes, parts))
        summary.append((size, f"{b}\tsessions={len(blocks)}\tkb={size // 1024}\tfiles={','.join(files)}"))
    print(f'# {len(pending)} new or grown sessions; digests in {args.out}')
    for _, line in sorted(summary, reverse=True):
        print(line)


def mark(args):
    rows = read_ledger(args.ledger)
    now = datetime.datetime.now().isoformat(timespec='seconds')
    for line in open(os.path.join(args.mark, 'pending.tsv'), encoding='utf-8'):
        sid, path, size = line.rstrip('\n').split('\t')[:3]
        rows[sid] = [sid, path, size, now]
    os.makedirs(args.ledger, exist_ok=True)
    p = os.path.join(args.ledger, 'sessions.tsv')
    with open(p + '.tmp', 'w', encoding='utf-8', newline='\n') as w:
        w.writelines('\t'.join(r) + '\n' for r in sorted(rows.values(), key=lambda r: r[0]))
    os.replace(p + '.tmp', p)
    print(f'{len(rows)} sessions in {p}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--all', action='store_true', help='ignore the ledger and digest every session')
    ap.add_argument('--out', default=os.path.join(LEDGER, 'digests', datetime.date.today().isoformat()))
    ap.add_argument('--session', metavar='ID8', help='digest only the session whose id starts with ID8')
    ap.add_argument('--mark', metavar='DIR', help="record DIR/pending.tsv as reviewed")
    ap.add_argument('--ledger', default=LEDGER)
    ap.add_argument('--roots', nargs='+', help='transcript roots (default: both sides of this machine)')
    ap.add_argument('--max-kb', type=int, default=150, help='split a bucket into parts above this size')
    args = ap.parse_args(argv)
    utf8_safe_stdout()
    mark(args) if args.mark else digest(args)


if __name__ == '__main__':
    sys.exit(main())
