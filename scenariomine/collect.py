"""Step 3: clone each repository and archive every version of every .xosc file.

Raw evidence only: blobs are stored byte-for-byte and history.jsonl records one
line per (commit, .xosc path) change. Nothing is parsed here.

Layout, per repository:
    <out>/<repo_id>/manifest.json   written last; its presence marks completion
    <out>/<repo_id>/history.jsonl   one record per .xosc change in a commit
    <out>/<repo_id>/blobs/<aa>/<git blob sha>.xosc

Blobs are content-addressed by git blob SHA, so identical content is stored once
per repository and the SHA doubles as the content hash used for deduplication.
"""
import csv
import datetime as dt
import json
import os
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__

MSG_CAP = 4000
CLONE_TIMEOUT = 3600
# Heuristic for "source code changed in the same commit" (Step 5): programming
# language files only, not docs, data or other scenario assets.
CODE_EXTS = {".py", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".java", ".rs",
             ".go", ".cs", ".js", ".ts", ".m", ".cmake"}
CHANGE = {"A": "added", "M": "modified", "T": "modified", "D": "deleted",
          "R": "renamed"}
LOG_FORMAT = "\x01%H\x1f%P\x1f%aI\x1f%cI\x1f%s\x1f%b\x02"
ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C.UTF-8")


def repo_id(full_name):
    return full_name.replace("/", "__")


def git(args, cwd=None, **kw):
    return subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=cwd,
                          env=ENV, capture_output=True, check=True, **kw)


def is_xosc(path):
    return path.lower().endswith(".xosc")


def is_code(path):
    return os.path.splitext(path)[1].lower() in CODE_EXTS or \
        os.path.basename(path) == "CMakeLists.txt"


def parse_commit_files(text):
    """{commit: (n_files, code_changed)} from `git log --name-only` output."""
    out = {}
    for chunk in text.split("\x01")[1:]:
        sha, _, files = chunk.partition("\n")
        names = [l for l in files.splitlines() if l]
        out[sha.strip()] = (len(names), any(is_code(n) for n in names))
    return out


def parse_log(text, commit_files):
    """Yield one record per .xosc change from `git log --raw` output."""
    skipped = 0
    for chunk in text.split("\x01")[1:]:
        head, _, raw = chunk.partition("\x02")
        sha, parents, authored, committed, subject, body = head.split("\x1f", 5)
        message = (subject + "\n\n" + body.strip()).strip()[:MSG_CAP]
        changes = []
        for line in raw.splitlines():
            if not line.startswith(":"):
                continue
            meta, *paths = line.split("\t")
            old_mode, new_mode, old_sha, new_sha, status = meta[1:].split()
            if "160000" in (old_mode, new_mode):  # submodule
                continue
            if any(p.startswith('"') for p in paths):
                skipped += 1  # git C-quoted a path with control characters
                continue
            changes.append((status, old_sha, new_sha, paths))
        n_files, code_changed = commit_files.get(sha, (len(changes), False))
        for status, old_sha, new_sha, paths in changes:
            kind = status[0]
            if kind not in CHANGE:
                continue
            path, old_path = paths[-1], None
            if kind == "R":
                old_path = paths[0]
                if not is_xosc(path):
                    if not is_xosc(old_path):
                        continue
                    kind, path, old_path = "D", old_path, None
                    new_sha = "0" * 40
            elif not is_xosc(path):
                continue
            null = "0" * 40
            yield {
                "commit": sha,
                "parents": parents.split(),
                "authored_at": authored,
                "committed_at": committed,
                "path": path,
                "old_path": old_path,
                "change_type": CHANGE[kind],
                "similarity": int(status[1:]) if kind == "R" and status[1:] else None,
                "blob_sha": None if new_sha == null else new_sha,
                "prev_blob_sha": None if old_sha == null else old_sha,
                "message": message,
                "n_files_in_commit": n_files,
                "code_changed_in_commit": code_changed,
            }
    if skipped:
        yield {"_skipped_quoted_paths": skipped}


def read_blobs(gitdir, shas, dest):
    """Write each blob to dest/<aa>/<sha>.xosc; return {sha: size} or None if missing."""
    sizes = {}
    shas = sorted(shas)
    p = subprocess.Popen(["git", "cat-file", "--batch"], cwd=gitdir, env=ENV,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
    try:
        for i in range(0, len(shas), 200):  # small batches: no pipe deadlock
            batch = shas[i:i + 200]
            p.stdin.write(("\n".join(batch) + "\n").encode())
            p.stdin.flush()
            for sha in batch:
                header = p.stdout.readline().split()
                if len(header) != 3:  # "<sha> missing"
                    sizes[sha] = None
                    continue
                size = int(header[2])
                data = p.stdout.read(size)
                p.stdout.read(1)
                d = dest / sha[:2]
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{sha}.xosc").write_bytes(data)
                sizes[sha] = size
    finally:
        p.stdin.close()
        p.wait()
    return sizes


def collect_repo(row, out, since, keep_clone, force, blob_limit="1m", pin_sha=None):
    name = row["full_name"]
    rdir = Path(out) / repo_id(name)
    mpath = rdir / "manifest.json"
    if mpath.exists() and not force:
        old = json.loads(mpath.read_text())
        if old.get("status") == "complete" and old.get("since") == since:
            return old
    shutil.rmtree(rdir, ignore_errors=True)
    rdir.mkdir(parents=True)
    manifest = {
        "repo": name, "license_spdx": row["license_spdx"] or None,
        "license_class": row["license_class"],
        "license_source": row["license_source"],
        "publish_contents": row["license_class"] == "permissive",
        "since": since, "blob_limit": blob_limit, "collector_version": __version__,
        "collected_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_version": git(["--version"]).stdout.decode().strip(),
        "status": "failed", "error": None,
    }
    clone = Path(out) / ".clones" / (repo_id(name) + ".git")
    try:
        shutil.rmtree(clone, ignore_errors=True)
        clone.parent.mkdir(parents=True, exist_ok=True)
        # blob:limit keeps big non-scenario blobs out; missing .xosc blobs are
        # lazily fetched by cat-file.
        subprocess.run(["git", "clone", "--bare", "--quiet", f"--filter=blob:limit={blob_limit}",
                        f"https://github.com/{name}.git", str(clone)],
                       env=ENV, capture_output=True, check=True, timeout=CLONE_TIMEOUT)
        rev = pin_sha or "HEAD"  # pin_sha: reproduce an earlier collection exactly
        manifest["head_sha"] = git(["rev-parse", "--verify", rev + "^{commit}"],
                                   clone).stdout.decode().strip()
        manifest["pinned"] = bool(pin_sha)
        since_args = [f"--since={since}"] if since else []
        # Pass 1: .xosc history only, so rename detection never reads other blobs
        # (it would lazily fetch large unrelated blobs one at a time).
        log = git(["log", rev, "--full-history", "--raw", "--root", "-M", "--no-abbrev",
                   "--format=" + LOG_FORMAT, *since_args, "--", "*.xosc", "*.XOSC", "*.Xosc"],
                  clone).stdout.decode("utf-8", errors="replace")
        # Pass 2: file names per commit (trees only, no blobs) for the
        # code-changed-in-commit flag.
        names = git(["log", rev, "--root", "--no-renames", "--name-only",
                     "--format=%x01%H", *since_args], clone).stdout.decode("utf-8", errors="replace")
        records, skipped = [], 0
        for rec in parse_log(log, parse_commit_files(names)):
            if "_skipped_quoted_paths" in rec:
                skipped = rec["_skipped_quoted_paths"]
            else:
                records.append(rec)
        sizes = read_blobs(clone, {r["blob_sha"] for r in records if r["blob_sha"]},
                           rdir / "blobs")
        for r in records:
            r["blob_size"] = sizes.get(r["blob_sha"])
        tmp = rdir / "history.jsonl.tmp"
        with open(tmp, "w") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        tmp.rename(rdir / "history.jsonl")
        manifest.update(
            n_records=len(records),
            n_commits=len({r["commit"] for r in records}),
            n_paths=len({r["path"] for r in records}),
            n_distinct_blobs=len({r["blob_sha"] for r in records if r["blob_sha"]}),
            n_missing_blobs=sum(1 for v in sizes.values() if v is None),
            n_skipped_quoted_paths=skipped,
            status="complete")
    except subprocess.CalledProcessError as e:
        manifest["error"] = (e.stderr or b"").decode(errors="replace").strip()[-500:]
    except Exception as e:  # keep one bad repo from killing the run
        manifest["error"] = f"{type(e).__name__}: {e}"
    finally:
        if not keep_clone:
            shutil.rmtree(clone, ignore_errors=True)
    mpath.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def collect(repos_csv, out, since=None, only=None, exclude=None, limit=None, jobs=4,
            keep_clone=False, force=False, blob_limit="1m", pin_from=None):
    with open(repos_csv, newline="") as f:
        rows = list(csv.DictReader(f))
    if only:
        rows = [r for r in rows if r["full_name"] in only]
        missing = set(only) - {r["full_name"] for r in rows}
        if missing:
            raise SystemExit(f"not in {repos_csv}: {sorted(missing)}")
    if exclude:
        rows = [r for r in rows if r["full_name"] not in exclude]
    if limit:
        rows = rows[:limit]
    pins = {}
    if pin_from:
        for r in rows:
            m = Path(pin_from) / repo_id(r["full_name"]) / "manifest.json"
            if not m.exists():
                raise SystemExit(f"--pin-from: no manifest for {r['full_name']}")
            pins[r["full_name"]] = json.loads(m.read_text())["head_sha"]
    Path(out).mkdir(parents=True, exist_ok=True)
    lock, done = threading.Lock(), [0]

    def one(row):
        m = collect_repo(row, out, since, keep_clone, force, blob_limit,
                         pins.get(row["full_name"]))
        with lock:
            done[0] += 1
            detail = (f"{m['n_records']} changes, {m['n_distinct_blobs']} blobs"
                      if m["status"] == "complete" else f"FAILED {m['error']}")
            print(f"[{done[0]}/{len(rows)}] {row['full_name']}: {detail}", flush=True)
        return m

    with ThreadPoolExecutor(jobs) as ex:
        return list(ex.map(one, rows))
