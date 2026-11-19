"""Deletes the temp dirs of ended Claude Code sessions and lists the big build output and files the owner decides on.

    python -I scripts/sweep.py [--dry-run]

A session dir is Temp\\claude\\<project-key>\\<session-id> (a UUID name). It has ENDED when its transcript
projects\\<project-key>\\<session-id>.jsonl was last written AGE_DAYS or more ago or, without a transcript, when the newest
mtime inside it is that old. An ended dir is deleted whole, except folders holding a file named KEEP and links that
resolve outside the root, which stay with the folders around them. Links are never followed. Files of LIST_FILE or more
under dev (no .git) and cargo build dirs (a dir holding CACHEDIR.TAG) of LIST_CARGO or more under dev and under live
session dirs are listed; a build dir among them (not a Python venv: no pyvenv.cfg) whose newest file is BUILD_STALE_DAYS
or more old is deleted instead - a build cache only matters while it shortens builds. Report: logs/sweep/<date>.md (appended per run) and logs/sweep/latest.txt."""

import argparse
import datetime
import json
import os
import re
import shutil
import stat
import sys
import time

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "AppData", "Local", "Temp", "claude")
PROJECTS = os.path.join(HOME, ".claude", "projects")
LOGS = os.path.join(HOME, ".claude", "logs", "sweep")
DEV = os.path.join(HOME, "dev")


def private_folders():
    """Folders nothing may touch: `private_folders` in ~/.claude/local.json (paths, ~ allowed), none when absent."""
    try:
        with open(os.path.join(HOME, ".claude", "local.json"), encoding="utf-8") as fh:
            paths = json.load(fh).get("private_folders") or []
    except (OSError, ValueError, AttributeError):
        return ()
    return tuple(os.path.expanduser(p) for p in paths if isinstance(p, str) and p)


PRIVATE = private_folders()
NEVER = ("\\\\wsl.localhost\\", os.path.join(HOME, ".claude"), DEV, *PRIVATE)
_DRIVE = os.path.splitdrive(HOME)[0]
DRIVE = _DRIVE + os.sep if _DRIVE else HOME  # the disk that holds the home directory
DRIVE_LABEL = _DRIVE or "home disk"
AGE_DAYS = 7
GB = 1024**3
LIST_FILE = GB
LIST_CARGO = 500 * 1024**2
BUILD_STALE_DAYS = 14  # unused this long, a cache no longer shortens a build
# Off until the owner answers: whether stale build caches are deleted at all, and after how many days, is
# his decision; until then every build dir is listed with its size and days since the last build.
DELETE_STALE_BUILDS = False
BUILD_NEVER = ("\\\\wsl.localhost\\", os.path.join(HOME, ".claude"), *PRIVATE)
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def under(path, root):
    path, root = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:  # another drive or a UNC path
        return False


def deletable(path):
    return under(path, ROOT) and not any(under(path, n) for n in NEVER)


def is_link(entry):
    return entry.is_symlink() or entry.is_junction()


def measure(path, skipped, root=ROOT):
    """(bytes, newest mtime inside, protected) of a dir tree without following links. Protected: it holds a KEEP file
    or a link resolving outside root somewhere; such links go to skipped. An empty dir's newest is its own mtime."""
    size, newest, protected = 0, 0.0, False
    try:
        entries = list(os.scandir(path))
    except OSError:
        return 0, os.lstat(path).st_mtime, True
    for e in entries:
        try:
            st = e.stat(follow_symlinks=False)
            newest = max(newest, st.st_mtime)
            if is_link(e):
                if not under(e.path, root):
                    skipped.add(e.path)
                    protected = True
            elif e.is_dir(follow_symlinks=False):
                s, n, p = measure(e.path, skipped, root)
                size, newest, protected = size + s, max(newest, n), protected or p
            else:
                size += st.st_size
                protected = protected or e.name == "KEEP"
        except OSError:
            protected = True
    return size, newest or os.lstat(path).st_mtime, protected


def build_dir(path):
    """A build cache the sweep may delete wherever it sits under dev or the temp root: it holds CACHEDIR.TAG, it is not a
    Python venv (no pyvenv.cfg), and it is under no BUILD_NEVER path."""
    return (
        os.path.isfile(os.path.join(path, "CACHEDIR.TAG"))
        and not os.path.exists(os.path.join(path, "pyvenv.cfg"))
        and (under(path, DEV) or under(path, ROOT))
        and not any(under(path, n) for n in BUILD_NEVER)
    )


def remove(path, is_dir, failures):
    """Deletes one file or tree; a read-only entry gets its bit cleared and one retry. Failures are logged, not raised."""

    def retry(func, p, exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError as again:
            failures.append(f"{p}: {exc} / retry: {again}")

    if not deletable(path) and not (is_dir and build_dir(path)):
        failures.append(f"{path}: refused, outside the sweep root or under a never-delete path")
        return
    try:
        if is_dir:
            shutil.rmtree(path, onexc=retry)
        else:
            try:
                os.unlink(path)
            except OSError as exc:
                retry(os.unlink, path, exc)
    except OSError as exc:
        failures.append(f"{path}: {exc}")


def delete_tree(path, dry, out):
    """Deletes path whole, or, when it is protected, everything in it except KEEP folders and outside links."""
    skipped = set()
    size, _, protected = measure(path, skipped)
    out["skipped"] |= skipped
    if not protected:
        out["deleted"].append((path, size))
        if not dry:
            before = len(out["failures"])
            remove(path, True, out["failures"])
            if len(out["failures"]) > before and os.path.exists(path):
                size -= measure(path, set())[0]
        out["freed"] += size
        return
    if os.path.isfile(os.path.join(path, "KEEP")):
        out["kept"].append((path, size))
        return
    for e in list(os.scandir(path)):
        if is_link(e):
            if e.path not in skipped:
                out["deleted"].append((e.path, 0))
                if not dry:
                    remove(e.path, e.is_dir(), out["failures"])
        elif e.is_dir(follow_symlinks=False):
            delete_tree(e.path, dry, out)
        else:
            n = e.stat(follow_symlinks=False).st_size
            out["deleted"].append((e.path, n))
            if not dry:
                before = len(out["failures"])
                remove(e.path, False, out["failures"])
                n = 0 if len(out["failures"]) > before else n
            out["freed"] += n


def listing(path, now, files, out, root):
    """Cargo build dirs of LIST_CARGO or more (not descended further) and, when files, files of LIST_FILE or more."""
    try:
        entries = list(os.scandir(path))
    except OSError as exc:
        out["failures"].append(f"{path}: {exc}")
        return
    if any(e.name == "CACHEDIR.TAG" and e.is_file(follow_symlinks=False) for e in entries):
        size, newest, protected = measure(path, out["skipped"], root)
        days = (now - newest) / 86400
        venv = any(e.name == "pyvenv.cfg" for e in entries)
        stale = DELETE_STALE_BUILDS and days >= BUILD_STALE_DAYS
        if stale and not venv and not protected and not any(under(path, n) for n in BUILD_NEVER):
            out["builds"].append((path, size, days))
            if not out["dry"]:
                before = len(out["failures"])
                remove(path, True, out["failures"])
                size = 0 if len(out["failures"]) > before else size
            out["freed"] += size
        elif size >= LIST_CARGO:
            out["cargo"].append((path + (" (Python venv)" if venv else ""), size, days))
        return
    for e in entries:
        try:
            if is_link(e):
                if not under(e.path, root):
                    out["skipped"].add(e.path)
            elif e.is_dir(follow_symlinks=False):
                if e.name != ".git":
                    listing(e.path, now, files, out, root)
            elif files:
                st = e.stat(follow_symlinks=False)
                if st.st_size >= LIST_FILE:
                    out["files"].append((e.path, st.st_size, (now - st.st_mtime) / 86400))
        except OSError as exc:
            out["failures"].append(f"{e.path}: {exc}")


def ended(key, sid, path, now, skipped):
    transcript = os.path.join(PROJECTS, key, sid + ".jsonl")
    if os.path.isfile(transcript):
        return now - os.path.getmtime(transcript) >= AGE_DAYS * 86400
    return now - measure(path, skipped)[1] >= AGE_DAYS * 86400


def sweep(dry=False, now=None):
    now = time.time() if now is None else now
    out = {"deleted": [], "kept": [], "skipped": set(), "files": [], "cargo": [], "builds": [], "failures": []}
    out["freed"], out["dry"] = 0, dry
    out["free_before"], ended_n = shutil.disk_usage(DRIVE).free, 0
    for k in sorted(os.scandir(ROOT), key=lambda e: e.name) if os.path.isdir(ROOT) else []:
        if is_link(k):
            if not under(k.path, ROOT):
                out["skipped"].add(k.path)
            continue
        if not k.is_dir():
            continue
        removed = False
        for s in sorted(os.scandir(k.path), key=lambda e: e.name):
            if not UUID.match(s.name):
                continue
            if is_link(s):
                if not under(s.path, ROOT):
                    out["skipped"].add(s.path)
                continue
            if not s.is_dir():
                continue
            if ended(k.name, s.name, s.path, now, out["skipped"]):
                ended_n += 1
                delete_tree(s.path, dry, out)
                removed = True
            else:
                listing(s.path, now, False, out, ROOT)
        if removed and not dry and not os.listdir(k.path):
            remove(k.path, True, out["failures"])
    if os.path.isdir(DEV):
        listing(DEV, now, True, out, DEV)
    out["free_after"], out["ended"] = shutil.disk_usage(DRIVE).free, ended_n
    return out


def gb(n):
    return f"{n / GB:.1f}"


def report(out, dry, now):
    stamp = datetime.datetime.fromtimestamp(now).astimezone()
    path = os.path.join(LOGS, stamp.strftime("%Y-%m-%d") + ".md")
    listed = sum(r[1] for r in out["files"]) + sum(r[1] for r in out["cargo"])
    verb = "would delete" if dry else "deleted"
    lines = [f"# Sweep {stamp:%Y-%m-%d %H:%M}" + (" (dry run, nothing deleted)" if dry else ""), ""]
    lines += [f"{DRIVE_LABEL} free before {gb(out['free_before'])} GB, after {gb(out['free_after'])} GB.", ""]
    lines += [f"## {verb.capitalize()}: {gb(out['freed'])} GB from {out['ended']} ended session dirs", ""]
    lines += [f"- {p} ({gb(n)} GB)" for p, n in out["deleted"]] or ["- none"]
    lines += ["", f"## {verb.capitalize()}: build dirs unused {BUILD_STALE_DAYS}+ days", ""]
    lines += [f"- {p} ({gb(n)} GB, {a:.0f} days since the last build)" for p, n, a in out["builds"]] or ["- none"]
    lines += ["", "## Kept (KEEP)", ""] + ([f"- {p} ({gb(n)} GB)" for p, n in out["kept"]] or ["- none"])
    lines += ["", "## Skipped links (resolve outside the root)", ""] + (
        [f"- {p}" for p in sorted(out["skipped"])] or ["- none"]
    )
    lines += ["", f"## Listed for the owner: {gb(listed)} GB", "", "Files of 1 GB or more under dev:", ""]
    lines += [f"- {p} ({gb(n)} GB, {a:.0f} days old)" for p, n, a in out["files"]] or ["- none"]
    lines += [
        "",
        "Build dirs of 500 MB or more (dev and live session dirs), with days since the last build:",
        "",
    ]
    lines += [f"- {p} ({gb(n)} GB, last build {a:.0f} days ago)" for p, n, a in out["cargo"]] or ["- none"]
    lines += ["", "## Failures", ""] + ([f"- {f}" for f in out["failures"]] or ["- none"])
    lines += ["", f"Total {verb}: {gb(out['freed'])} GB.", "", ""]
    os.makedirs(LOGS, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    if not dry:
        with open(os.path.join(LOGS, "latest.txt"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(
                f"swept {stamp:%Y-%m-%d %H:%M}: freed {gb(out['freed'])} GB ({out['ended']} ended session dirs, "
                f"{len(out['builds'])} unused build dirs); "
                f"{gb(listed)} GB listed for the owner in {path}; {DRIVE_LABEL} {gb(out['free_after'])} GB free\n"
            )
    return path


def main():
    parser = argparse.ArgumentParser(description="Sweep ended Claude Code session temp dirs.")
    parser.add_argument("--dry-run", action="store_true", help="measure and report, delete nothing")
    args = parser.parse_args()
    now = time.time()
    path = report(sweep(args.dry_run, now), args.dry_run, now)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
