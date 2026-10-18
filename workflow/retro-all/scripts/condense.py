#!/usr/bin/env python3
"""Condense one session and all its subagents into readable parts, for a retro over a session's complete history.

  condense.py <session-id8> [--out DIR] [--chunk-kb 200] [--batches 5]

Writes DIR/main.NN.txt (the session, in parts of --chunk-kb), DIR/sub/<agent>.NN.txt (each subagent),
DIR/batchN.lst (the subagent parts spread over --batches lists of even size) and DIR/reviews.txt (the
security-review sub-sessions run during the session: count and the ones that reported findings).
Line formats: `[MM-DDTHH:MM] U:` user message (a subagent's first is its brief), `A:` assistant text,
`T <tool>: <input>`, `ERR:` failed or denied tool result, `BIG-RESULT` a tool result over 25k chars.
"""
import argparse, glob, json, os, re, sys

from digest import LEDGER, REVIEW_PREFIXES, find_sessions, roots, utf8_safe_stdout

SR = re.compile(r'<system-reminder>.*?</system-reminder>', re.S)
DENIED = re.compile(r"doesn't want to proceed|denied|rejected|Permission")


def text(c):
    if isinstance(c, str):
        return c
    return '\n'.join(b.get('text', '') if isinstance(b, dict) else str(b) for b in c or [])


def cut(s, n):
    s = s.strip()
    return s if len(s) <= n else f'{s[:n]}…[+{len(s) - n}]'


def condense(path):
    """(header, body, first timestamp, last timestamp) of one transcript."""
    meta = path[:-6] + '.meta.json'
    head = f'# {os.path.basename(path)[:-6]}'
    if os.path.exists(meta):
        m = json.load(open(meta, encoding='utf-8'))
        head += f" type={m.get('agentType')} model={m.get('model')} desc={m.get('description')}"
    lines, tools, first, last = [], {}, None, None
    for raw in open(path, encoding='utf-8', errors='replace'):
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(d, dict) or d.get('type') not in ('user', 'assistant'):
            continue
        full = d.get('timestamp') or ''
        first, last = first or full, full or last
        ts, c = full[5:16], (d.get('message') or {}).get('content')
        if d['type'] == 'user':
            blocks = c if isinstance(c, list) else []
            if isinstance(c, str) or any(isinstance(b, dict) and b.get('type') == 'text' for b in blocks):
                s = SR.sub('', text(c)).strip()
                if s and not d.get('isMeta'):
                    lines.append(f'\n[{ts}] U: {cut(s, 5000)}\n')
            for b in blocks:
                if isinstance(b, dict) and b.get('type') == 'tool_result':
                    s = text(b.get('content'))
                    if b.get('is_error') or DENIED.search(s[:300]):
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
    return f'{head}\ntools={tools}\n', ''.join(lines), first or '', last or ''


def parts(head, body, chunk_kb):
    """Split on line starts so no entry is cut in half; each part repeats the header."""
    out, cur, limit = [], '', chunk_kb * 1024
    for entry in re.split(r'(?=\n?\[\d\d-\d\dT)', body):
        if cur and len((cur + entry).encode('utf-8')) > limit:
            out.append(cur)
            cur = ''
        cur += entry
    out.append(cur)
    return [head + p for p in out]


def write_parts(out_dir, name, chunks):
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for i, p in enumerate(chunks, 1):
        f = os.path.join(out_dir, f'{name}.{i:02d}.txt')
        with open(f, 'w', encoding='utf-8', newline='\n') as w:
            w.write(p)
        files.append(f)
    return files


def reviews(main_path, first, last):
    """Security-review sub-sessions of the same project that ran inside the session's time window."""
    proj = os.path.basename(os.path.dirname(main_path))
    root = os.path.dirname(os.path.dirname(main_path))
    rows = []
    for f in glob.glob(os.path.join(root, proj + '*', '*.jsonl')):
        fu = findings = None
        for raw in open(f, encoding='utf-8', errors='replace'):
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            c = (d.get('message') or {}).get('content')
            if fu is None and d.get('type') == 'user':
                fu = (d.get('timestamp') or '', text(c) if isinstance(c, str) else '')
            if d.get('type') == 'assistant' and isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') == 'StructuredOutput':
                        findings = (b.get('input') or {}).get('findings')
        if fu and fu[1].startswith(REVIEW_PREFIXES) and first <= fu[0] <= last:
            rows.append((fu[0], f, findings or []))
    return sorted(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('session', metavar='ID8')
    ap.add_argument('--out')
    ap.add_argument('--chunk-kb', type=int, default=200)
    ap.add_argument('--batches', type=int, default=5)
    ap.add_argument('--roots', nargs='+', help='transcript roots (default: both sides of this machine)')
    a = ap.parse_args(argv)
    utf8_safe_stdout()
    hits = {s: p for s, p in find_sessions(a.roots or [r for r in roots() if os.path.isdir(r)]).items() if s.startswith(a.session)}
    if len(hits) != 1:
        sys.exit(f'{len(hits)} transcripts match {a.session}')
    (sid, path), = hits.items()
    out = a.out or os.path.join(LEDGER, f'full-{sid[:8]}')
    head, body, first, last = condense(path)
    main_files = write_parts(out, 'main', parts(head, body, a.chunk_kb))
    sub_files = []
    for f in sorted(glob.glob(os.path.join(path[:-6], 'subagents', '*.jsonl'))):
        h, b, _, _ = condense(f)
        sub_files += write_parts(os.path.join(out, 'sub'), os.path.basename(f)[:-6], parts(h, b, a.chunk_kb))
    # Largest first into the lightest batch: batches end up within one part's size of each other.
    batches, sizes = [[] for _ in range(max(1, a.batches))], [0] * max(1, a.batches)
    for f in sorted(sub_files, key=os.path.getsize, reverse=True):
        i = sizes.index(min(sizes))
        batches[i].append(f)
        sizes[i] += os.path.getsize(f)
    batches = [b for b in batches if b]
    for i, b in enumerate(batches, 1):
        with open(os.path.join(out, f'batch{i}.lst'), 'w', encoding='utf-8', newline='\n') as w:
            w.write('\n'.join(b) + '\n')
    rv = reviews(path, first, last)
    with open(os.path.join(out, 'reviews.txt'), 'w', encoding='utf-8', newline='\n') as w:
        w.write(f'{len(rv)} security-review sub-sessions, {sum(1 for r in rv if r[2])} with findings\n')
        for ts, f, fs in rv:
            if fs:
                w.write(f'{ts} {f}: {json.dumps(fs, ensure_ascii=False)[:600]}\n')
    print(f'# {path}\n# {first} .. {last}')
    print(f'main parts={len(main_files)} subagents={len(set(os.path.basename(f).rsplit(".", 2)[0] for f in sub_files))} '
          f'sub parts={len(sub_files)} batches={len(batches)} reviews={len(rv)}')
    print(f'out={out}')


if __name__ == '__main__':
    sys.exit(main())
