#!/usr/bin/env python3
"""Offline release guard. Reports paths/rules only; never prints matched secrets."""

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_DOCS = {"README.md", "SECURITY.md", "CONTRIBUTING.md", "docs/release-readiness.md"}
PRIVATE_NAME = re.compile(rb"luna" + rb"res", re.I)
SECRETS = [
    re.compile(rb"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    re.compile(rb"(?:sk-ant-|sk-proj-|gh[pousr]_)[A-Za-z0-9_-]{20,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"(?:https?|postgres(?:ql)?|mysql)://[^\s/:]+:[^\s/@]{8,}@"),
]
DATA_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".csv", ".tsv", ".sql", ".dump",
                 ".pdf", ".docx", ".xlsx", ".zip", ".gz", ".tar", ".bak", ".log",
                 ".ses", ".wav", ".mp3", ".webm", ".ogg", ".m4a", ".onnx"}
ASSETS = {".png", ".svg", ".woff2", ".ico"}
REQUIRED = {
    "atlas_backend/app/knowledge/" + name + ".py"
    for name in ("__init__", "store", "extract", "embed", "chunk", "search")
} | {"SECURITY.md", "CONTRIBUTING.md", "LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def check(path, data):
    reasons = []
    p = Path(path)
    if (p.name.startswith(".env") and p.name != ".env.example") or any(
        part in {"private", "exports", "backups", "node_modules", ".venv", "dist"}
        for part in p.parts
    ):
        reasons.append("private/generated path")
    if (path.startswith(("atlas_backend/knowledge/", "atlas_backend/models/"))
            or p.suffix.lower() in DATA_SUFFIXES):
        reasons.append("runtime data or document export")
    if re.search(r"\.(?:db|sqlite3?)-", p.name):
        reasons.append("database sidecar")
    if PRIVATE_NAME.search(path.encode()) or (
        path not in POLICY_DOCS and PRIVATE_NAME.search(data)
    ):
        reasons.append("private habitat reference")
    if any(pattern.search(data) for pattern in SECRETS):
        reasons.append("possible credential")
    if p.suffix.lower() in ASSETS and not path.startswith("atlas_frontend/public/"):
        reasons.append("unreviewed asset location")
    if b"\0" in data and p.suffix.lower() not in ASSETS:
        reasons.append("unreviewed binary")
    return reasons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Inspect exact Git index blobs")
    parser.add_argument("--history", action="store_true", help="Also inspect all reachable commits")
    args = parser.parse_args()
    failures = []
    count = 0
    present = set()

    def inspect(path, data, label):
        nonlocal count
        count += 1
        if label != "history":
            present.add(path)
        for reason in check(path, data):
            failures.append(f"{label}: {path}: {reason}")

    if args.staged:
        for record in git("ls-files", "--stage", "-z").split(b"\0"):
            if not record:
                continue
            meta, raw_path = record.split(b"\t", 1)
            mode, oid, stage = meta.decode().split()
            path = raw_path.decode()
            if mode not in {"100644", "100755"} or stage != "0":
                failures.append(f"index: {path}: symlink, submodule or unresolved conflict")
                continue
            inspect(path, git("cat-file", "blob", oid), "index")
    else:
        paths = set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0"))
        for raw_path in sorted(filter(None, paths)):
            path = raw_path.decode()
            full = ROOT / path
            if full.is_symlink():
                failures.append(f"worktree: {path}: symlink")
            elif full.is_file():
                inspect(path, full.read_bytes(), "worktree")
            # A tracked deletion is absent from the working release candidate.

    for path in sorted(REQUIRED - present):
        failures.append(f"candidate: {path}: required release file missing")

    if args.history:
        seen = set()
        for commit in git("rev-list", "--all").decode().splitlines():
            for record in git("ls-tree", "-rz", commit).split(b"\0"):
                if not record:
                    continue
                meta, raw_path = record.split(b"\t", 1)
                mode, kind, oid = meta.decode().split()
                path = raw_path.decode()
                if (path, oid) in seen:
                    continue
                seen.add((path, oid))
                if mode not in {"100644", "100755"} or kind != "blob":
                    failures.append(f"history: {path}: symlink or submodule")
                else:
                    inspect(path, git("cat-file", "blob", oid), "history")

    if failures:
        print("Release guard FAILED:")
        print("\n".join(sorted(set(failures))))
        return 1
    print(f"Release guard passed ({count} file versions checked).")
    print("Pattern checks cannot establish data provenance; review fixtures and assets manually.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
