#!/usr/bin/env python3
"""Make this repository's copies of upstream's branches and tags exact.

Every branch and tag of the upstream repository is pushed here under the same
name, forced: a mirrored branch is always identical to upstream's, even if
upstream rewrites it. Our own branches (OURS) are never touched, and nothing
here is ever deleted (a branch upstream deletes stays, with a warning).

Prints what changed. With $GITHUB_OUTPUT set it also writes
``build=true|false``: whether BUILD_BRANCH (the branch the package is built
from) changed, so the workflow knows to build and publish.

    packaging/sync-mirror.py                       # from a checkout whose origin is this repo
    packaging/sync-mirror.py --dry-run             # show what would be pushed

Standard library only.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

UPSTREAM = "https://git.m-labs.hk/M-Labs/migen.git"
BUILD_BRANCH = "master"
# Branches that are ours, not upstream's: the packaging, and the archived
# GitHub m-labs/migen branches this fork started from.
OURS = {"packaging", "github-master", "legacy", "experimental"}


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(args), flush=True)
    r = subprocess.run(args, capture_output=True, text=True)
    if r.stdout.strip():
        print(r.stdout.rstrip())
    if r.stderr.strip():
        print(r.stderr.rstrip(), file=sys.stderr)
    if check and r.returncode != 0:
        sys.exit(f"sync-mirror.py: {' '.join(args)} failed ({r.returncode})")
    return r


def refs(remote: str) -> dict[str, str]:
    """ref name -> object id, for branches and tags (peeled tag lines skipped)."""
    out = run("git", "ls-remote", "--heads", "--tags", remote).stdout
    result = {}
    for line in out.splitlines():
        sha, name = line.split("\t")
        if not name.endswith("^{}"):
            result[name] = sha
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--upstream", default=UPSTREAM)
    ap.add_argument("--remote", default="origin", help="this repository's remote")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    theirs = refs(args.upstream)
    ours = refs(args.remote)
    if f"refs/heads/{BUILD_BRANCH}" not in theirs:
        sys.exit(f"sync-mirror.py: {args.upstream} has no {BUILD_BRANCH} branch")

    changed = [name for name, sha in sorted(theirs.items())
               if ours.get(name) != sha
               and name.removeprefix("refs/heads/") not in OURS]
    skipped = sorted(n for n in theirs if n.removeprefix("refs/heads/") in OURS)
    for name in skipped:
        print(f"::warning::upstream has {name}, which is one of ours here: not mirrored")
    for name in sorted(set(ours) - set(theirs)):
        if name.startswith("refs/heads/") and name.removeprefix("refs/heads/") not in OURS:
            print(f"::warning::{name} is gone upstream; left here as it is")

    if changed:
        # Fetch exactly the objects upstream's refs point at, into a private
        # namespace, then push each one to the same name here.
        run("git", "fetch", "--no-tags", args.upstream,
            *[f"+{n}:refs/mirror/{n.removeprefix('refs/')}" for n in changed])
        specs = [f"+refs/mirror/{n.removeprefix('refs/')}:{n}" for n in changed]
        if args.dry_run:
            print("dry run, would push:", *specs, sep="\n  ")
        else:
            run("git", "push", "--atomic", args.remote, *specs)
    for name in changed:
        print(f"mirrored {name}: {ours.get(name, '(new)')[:12]} -> {theirs[name][:12]}")
    if not changed:
        print("every mirrored branch and tag already matches upstream")

    build = f"refs/heads/{BUILD_BRANCH}" in changed
    print(f"build={'true' if build else 'false'}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"build={'true' if build else 'false'}\n")


if __name__ == "__main__":
    main()
