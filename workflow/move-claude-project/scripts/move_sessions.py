#!/usr/bin/env python3
"""Copy Claude Code sessions and memory from one project path to another.

Usage:
  move_sessions.py OLD_PATH NEW_PATH [--from-root DIR] [--to-root DIR] [--apply] [--cleanup]
  move_sessions.py --self-test

Dry run by default: prints the plan and writes nothing. --apply copies; --cleanup deletes the
source project dirs after checking every source file has a copy (run it after --apply).
Every project dir whose sessions ran in OLD_PATH or below it (worktrees, subdirs) moves to the
matching place under NEW_PATH. Windows paths work from WSL: OLD_PATH 'D:\\Dev\\x' with
--from-root /mnt/c/Users/<you>/.claude/projects.
"""
import argparse, json, os, re, shutil, stat, sys, tempfile

HOME_ROOT = os.path.expanduser("~/.claude/projects")


def slug(path):
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def sep_of(path):
    return "\\" if re.match(r"^[A-Za-z]:\\", path) else "/"


def norm(path):
    return path.rstrip("\\/")


def under(path, root):
    """Tail of `path` below `root` ('' for root itself), or None when outside it."""
    if path == root:
        return ""
    for s in ("\\", "/"):
        if path.startswith(root + s):
            return path[len(root):]
    return None


def forms(old):
    """`old` as written by each shell: D:\\x also shows up as D:/x and Git Bash's /d/x."""
    m = re.match(r"^([A-Za-z]):\\(.*)$", old)
    if not m:
        return [old]
    rest = m.group(2).replace("\\", "/")
    return [old, f"{m.group(1)}:/{rest}", f"/{m.group(1).lower()}/{rest}"]


def map_path(path, old, new):
    for form in forms(old):
        tail = under(path, form)
        if tail is not None:
            return new + re.sub(r"[\\/]", lambda _: sep_of(new), tail)
    return None


def first_cwd(proj_dir):
    for name in sorted(os.listdir(proj_dir)):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(proj_dir, name), encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    cwd = json.loads(line).get("cwd")
                except (ValueError, AttributeError):
                    continue
                if isinstance(cwd, str):
                    return cwd
    return None


def plan(old, new, from_root, to_root):
    """[(src_dir, dst_dir)] for every project dir belonging to `old`."""
    base = slug(old)
    pairs = []
    for name in sorted(os.listdir(from_root)):
        src = os.path.join(from_root, name)
        if not os.path.isdir(src) or not (name == base or name.startswith(base + "-")):
            continue
        cwd = first_cwd(src)
        target = map_path(cwd, old, new) if cwd else (new if name == base else None)
        if target is None:  # slug prefix collision, such as D--Dev-foo vs D--Dev-foo-bar
            continue
        if cwd and slug(cwd) != name:
            print(f"warn: {name} holds cwd {cwd} (slug {slug(cwd)}); moving it anyway", file=sys.stderr)
        pairs.append((src, os.path.join(to_root, slug(target))))
    return pairs


def rewrite(value, old, new):
    if isinstance(value, str):
        mapped = map_path(value, old, new)
        if mapped is not None:
            return mapped
        for form in forms(old):
            value = value.replace(form, new)
        return value
    if isinstance(value, list):
        return [rewrite(v, old, new) for v in value]
    if isinstance(value, dict):
        return {k: rewrite(v, old, new) for k, v in value.items()}
    return value


def rewrite_jsonl(src, dst, old, new):
    with open(src, encoding="utf-8", newline="") as f, open(dst, "w", encoding="utf-8", newline="") as g:
        for line in f:
            body = line.rstrip("\r\n")
            try:
                obj = json.loads(body)
            except ValueError:
                g.write(line)  # keep a line we cannot parse exactly as it was
                continue
            g.write(json.dumps(rewrite(obj, old, new), ensure_ascii=False, separators=(",", ":")) + line[len(body):])


def copy_tree(src, dst, old, new, cross_os):
    copied = skipped = 0
    for dirpath, _, files in os.walk(src):
        out = os.path.join(dst, os.path.relpath(dirpath, src))
        os.makedirs(out, exist_ok=True)
        if cross_os:
            os.chmod(out, 0o700)
        for name in files:
            s, d = os.path.join(dirpath, name), os.path.join(out, name)
            if os.path.exists(d):
                skipped += 1
                continue
            if name.endswith(".jsonl"):
                rewrite_jsonl(s, d, old, new)
                shutil.copystat(s, d)
            else:
                shutil.copy2(s, d)
            # drvfs (/mnt/c) reports every file 0755; Claude writes its own as 0600
            os.chmod(d, 0o600 if cross_os else stat.S_IMODE(os.stat(s).st_mode))
            copied += 1
    return copied, skipped


def missing_copies(src, dst):
    return [os.path.relpath(os.path.join(dp, n), src) for dp, _, fs in os.walk(src) for n in fs
            if not os.path.exists(os.path.join(dst, os.path.relpath(os.path.join(dp, n), src)))]


def run(old, new, from_root, to_root, apply=False, cleanup=False):
    old, new = norm(old), norm(new)
    pairs = plan(old, new, from_root, to_root)
    if not pairs:
        print(f"no project dir under {from_root} matches {slug(old)}")
        return 1
    cross_os = os.path.realpath(from_root).startswith("/mnt/") != os.path.realpath(to_root).startswith("/mnt/")
    for src, dst in pairs:
        print(f"{src}\n  -> {dst}" + ("  (exists, merging)" if os.path.exists(dst) else ""))
        if apply:
            copied, skipped = copy_tree(src, dst, old, new, cross_os)
            print(f"  copied {copied}, kept {skipped} already there")
        if cleanup:
            missing = missing_copies(src, dst)
            if missing:
                print(f"  not deleting: {len(missing)} files have no copy, e.g. {missing[0]}")
            elif apply or os.path.exists(dst):
                shutil.rmtree(src)
                print("  source deleted")
    if not apply and not cleanup:
        print("dry run: rerun with --apply to copy")
    return 0


def self_test():
    with tempfile.TemporaryDirectory() as tmp:
        frm, to = os.path.join(tmp, "from"), os.path.join(tmp, "to")
        old = "D:\\Dev\\florile"
        new = "/home/u/dev/florile"
        layout = {
            slug(old): old,
            slug(old + "\\.claude\\worktrees\\agent-1"): old + "\\.claude\\worktrees\\agent-1",
            slug("D:\\Dev\\florile-two"): "D:\\Dev\\florile-two",  # prefix collision: must stay
        }
        for name, cwd in layout.items():
            os.makedirs(os.path.join(frm, name, "memory"))
            with open(os.path.join(frm, name, "s.jsonl"), "w", newline="") as f:
                f.write(json.dumps({"cwd": cwd, "msg": f"edit {old}\\a.txt", "n": 1}) + "\r\n")
                f.write(json.dumps({"cwd": "/d/Dev/florile/src", "p": "D:/Dev/florile/x"}) + "\n")
                f.write("not json\n")
            with open(os.path.join(frm, name, "memory", "MEMORY.md"), "w") as f:
                f.write("note")
        os.makedirs(to)
        assert run(old, new, frm, to) == 0 and os.listdir(to) == []  # dry run writes nothing
        assert run(old, new, frm, to, apply=True) == 0
        with open(os.path.join(to, slug(new), "s.jsonl"), newline="") as f:
            rec = json.loads(f.readline())
        assert rec["cwd"] == new and rec["msg"] == f"edit {new}\\a.txt" and rec["n"] == 1, rec
        assert sorted(os.listdir(to)) == sorted([slug(new), slug(new + "/.claude/worktrees/agent-1")])
        with open(os.path.join(to, slug(new), "s.jsonl"), newline="") as f:
            lines = f.read().split("\r\n", 1)[1].splitlines(keepends=True)
        assert lines[1] == "not json\n"
        rec = json.loads(lines[0])
        assert rec == {"cwd": new + "/src", "p": new + "/x"}, rec
        wt = json.loads(open(os.path.join(to, slug(new + "/.claude/worktrees/agent-1"), "s.jsonl")).readline())
        assert wt["cwd"] == new + "/.claude/worktrees/agent-1", wt
        assert os.path.exists(os.path.join(to, slug(new), "memory", "MEMORY.md"))
        assert len(os.listdir(frm)) == 3  # source kept until --cleanup
        assert run(old, new, frm, to, apply=True) == 0  # rerun merges, overwrites nothing
        assert run(old, new, frm, to, cleanup=True) == 0
        assert os.listdir(frm) == [slug("D:\\Dev\\florile-two")]
    print("self-test passed")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("old", nargs="?")
    p.add_argument("new", nargs="?")
    p.add_argument("--from-root", default=HOME_ROOT, help="projects dir holding OLD's sessions")
    p.add_argument("--to-root", default=HOME_ROOT, help="projects dir to copy into")
    p.add_argument("--apply", action="store_true", help="copy (default: dry run)")
    p.add_argument("--cleanup", action="store_true", help="delete the source dirs once every file has a copy")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        return self_test()
    if not (a.old and a.new):
        p.error("OLD_PATH and NEW_PATH are required")
    return run(a.old, a.new, a.from_root, a.to_root, a.apply, a.cleanup)


if __name__ == "__main__":
    sys.exit(main())
