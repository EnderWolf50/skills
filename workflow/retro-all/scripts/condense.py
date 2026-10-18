#!/usr/bin/env python3
"""Condense one session and all its subagents into readable parts, for a retro over a session's complete history.

  condense.py <session-id8> [--out DIR] [--chunk-kb 200] [--batch-kb 600]

Writes DIR/main.NN.txt (the session, in parts of --chunk-kb), DIR/sub/<agent>.NN.txt (each subagent),
DIR/batchN.lst (the subagent parts spread over as many lists as --batch-kb needs, of even size) and
DIR/reviews.txt (the security-review sub-sessions run from the session's own checkouts, and the ones whose
findings survived). DIR is cleared of earlier parts first.
Each part starts with `# <name> [type= model= desc=]` and `tools={...}`. Line formats, times in UTC:
`[MM-DDTHH:MM] U:` user message (a subagent's first is its brief), `N:` a task notification, `A:` assistant
text, `T <tool>: <input>`, `ERR:` failed or denied tool result, `BIG-RESULT` a tool result over 25k chars.
"""
import argparse, glob, json, math, os, re, shutil, sys

from digest import LEDGER, REVIEW_PREFIXES, find_sessions, roots, text, utf8_safe_stdout

SR = re.compile(r'<system-reminder>.*?</system-reminder>', re.S)
SKIP_USER = ('<local-command', 'Caveat:')


def blocks_text(c):
    """Text of a content value: a string, or the text of every block (tool results included)."""
    if isinstance(c, str):
        return c
    return '\n'.join(b.get('text', '') if isinstance(b, dict) else str(b) for b in c or [])


def cut(s, n):
    s = s.strip()
    return s if len(s) <= n else f'{s[:n]}…[+{len(s) - n}]'


def condense(path):
    """(header, entry lines, first timestamp, last timestamp, cwds) of one transcript."""
    meta = path[:-6] + '.meta.json'
    head = f'# {os.path.basename(path)[:-6]}'
    if os.path.exists(meta):
        m = json.load(open(meta, encoding='utf-8'))
        head += f" type={m.get('agentType')} model={m.get('model')} desc={m.get('description')}"
    lines, tools, cwds, first, last = [], {}, set(), None, None
    for raw in open(path, encoding='utf-8', errors='replace'):
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(d, dict) or d.get('type') not in ('user', 'assistant'):
            continue
        if d.get('cwd'):
            cwds.add(os.path.normcase(d['cwd']))
        full = d.get('timestamp') or ''
        first, last = first or full, full or last
        ts, c = full[5:16], (d.get('message') or {}).get('content')
        if d['type'] == 'user':
            blocks = c if isinstance(c, list) else []
            if isinstance(c, str) or any(isinstance(b, dict) and b.get('type') == 'text' for b in blocks):
                s = SR.sub('', text(c)).strip()
                if s.startswith('<task-notification'):
                    lines.append(f'[{ts}] N: {cut(s, 400)}\n')
                elif s and not d.get('isMeta') and not s.startswith(SKIP_USER):
                    lines.append(f'\n[{ts}] U: {cut(s, 5000)}\n')
            for b in blocks:
                if isinstance(b, dict) and b.get('type') == 'tool_result':
                    s = blocks_text(b.get('content'))
                    if b.get('is_error'):
                        lines.append(f'[{ts}] ERR: {cut(s, 600)}\n')
                    elif len(s) > 25000:
                        lines.append(f'[{ts}] BIG-RESULT {len(s)} chars: {cut(s, 150)}\n')
        else:
            for b in c if isinstance(c, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get('type') == 'text' and b['text'].strip():
                    lines.append(f'[{ts}] A: {cut(b["text"], 1200)}\n')
                elif b.get('type') == 'tool_use':
                    tools[b['name']] = tools.get(b['name'], 0) + 1
                    lines.append(f'[{ts}] T {b["name"]}: {cut(json.dumps(b.get("input"), ensure_ascii=False), 400)}\n')
    return f'{head}\ntools={tools}\n', lines, first or '', last or '', cwds


def parts(head, lines, chunk_kb):
    """Pack whole entries into parts of at most chunk_kb; each part repeats the header."""
    out, cur, size, limit = [], [], 0, chunk_kb * 1024
    for entry in lines:
        n = len(entry.encode('utf-8'))
        if cur and size + n > limit:
            out.append(cur)
            cur, size = [], 0
        cur.append(entry)
        size += n
    out.append(cur)
    return [head + ''.join(p) for p in out]


def write_parts(out_dir, name, chunks):
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for i, p in enumerate(chunks, 1):
        f = os.path.join(out_dir, f'{name}.{i:02d}.txt')
        with open(f, 'w', encoding='utf-8', newline='\n') as w:
            w.write(p)
        files.append(f)
    return files


def balance(files, n):
    """Largest first into the lightest list: lists end up within one part's size of each other."""
    lists, sizes = [[] for _ in range(n)], [0] * n
    for f in sorted(files, key=os.path.getsize, reverse=True):
        i = sizes.index(min(sizes))
        lists[i].append(f)
        sizes[i] += os.path.getsize(f)
    return [l for l in lists if l]


def review_session(f):
    """(first timestamp, cwd, pass, findings) of a security-review sub-session, or None for any other session."""
    first = cwd = kind = None
    findings = []
    for raw in open(f, encoding='utf-8', errors='replace'):
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        c = (d.get('message') or {}).get('content')
        if kind is None and d.get('type') == 'user':
            t = text(c)
            if not t.startswith(REVIEW_PREFIXES):
                return None
            first, cwd, kind = d.get('timestamp') or '', os.path.normcase(d.get('cwd') or ''), 1 + t.startswith(REVIEW_PREFIXES[1])
        if d.get('type') == 'assistant' and isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') == 'StructuredOutput':
                    inp = b.get('input') or {}
                    findings = inp.get('survived', inp.get('findings')) or []   # pass 2 keeps only survivors
    return (first, cwd, kind, findings) if kind else None


def reviews(root, cwds, first, last):
    """Pass-1 reviews run from the session's own checkouts inside its time window, each with the findings that
    survived: a pass-2 sub-session in the same checkout replaces the findings of the pass 1 before it."""
    found = sorted((r for f in glob.glob(os.path.join(root, '*', '*.jsonl')) if (r := review_session(f))), key=lambda r: r[0] or '')
    rows = []
    for ts, cwd, kind, fs in found:
        if cwd not in cwds or not first <= ts <= last:
            continue
        if kind == 1:
            rows.append([ts, cwd, fs])
        else:
            prior = [r for r in rows if r[1] == cwd]
            if prior:
                prior[-1][2] = fs
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('session', metavar='ID8')
    ap.add_argument('--out')
    ap.add_argument('--chunk-kb', type=int, default=200, help='size of one part')
    ap.add_argument('--batch-kb', type=int, default=600, help='size of one batch list, about one analyst\'s reading')
    ap.add_argument('--roots', nargs='+', help='transcript roots (default: both sides of this machine)')
    a = ap.parse_args(argv)
    utf8_safe_stdout()
    hits = {s: p for s, p in find_sessions(a.roots or [r for r in roots() if os.path.isdir(r)]).items() if s.startswith(a.session)}
    if len(hits) != 1:
        sys.exit(f'{len(hits)} transcripts match {a.session}')
    (sid, path), = hits.items()
    out = a.out or os.path.join(LEDGER, f'full-{sid[:8]}')
    for stale in glob.glob(os.path.join(out, 'main.*.txt')) + glob.glob(os.path.join(out, 'batch*.lst')):
        os.remove(stale)
    shutil.rmtree(os.path.join(out, 'sub'), ignore_errors=True)
    head, lines, first, last, cwds = condense(path)
    main_files = write_parts(out, 'main', parts(head, lines, a.chunk_kb))
    sub_files, names = [], []
    for f in sorted(glob.glob(os.path.join(path[:-6], 'subagents', '*.jsonl'))):
        h, l, _, _, c = condense(f)
        cwds |= c
        names.append(os.path.basename(f)[:-6])
        sub_files += write_parts(os.path.join(out, 'sub'), names[-1], parts(h, l, a.chunk_kb))
    total_kb = sum(os.path.getsize(f) for f in sub_files) / 1024
    batches = balance(sub_files, max(1, math.ceil(total_kb / a.batch_kb))) if sub_files else []
    for i, b in enumerate(batches, 1):
        with open(os.path.join(out, f'batch{i}.lst'), 'w', encoding='utf-8', newline='\n') as w:
            w.write('\n'.join(b) + '\n')
    rv = reviews(os.path.dirname(os.path.dirname(path)), cwds, first, last)
    with open(os.path.join(out, 'reviews.txt'), 'w', encoding='utf-8', newline='\n') as w:
        w.write(f'{len(rv)} security reviews, {sum(1 for r in rv if r[2])} with surviving findings\n')
        for ts, cwd, fs in rv:
            if fs:
                w.write(f'{ts} {cwd}: {json.dumps(fs, ensure_ascii=False)[:600]}\n')
    print(f'# {path}\n# {first} .. {last} (UTC)')
    print(f'main parts={len(main_files)} subagents={len(names)} sub parts={len(sub_files)} '
          f'batches={len(batches)} reviews={len(rv)}')
    print(f'out={out}')


if __name__ == '__main__':
    sys.exit(main())
