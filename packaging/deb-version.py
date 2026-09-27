#!/usr/bin/env python3
"""The package version and changelog entry for one build of this Set A repository.

mithro/apt-repo-action's docs/packaging.md ("Versions", Set A):

    <base>+fpgasonline<M>[~deb<R>][~pr<P>]

- ``<base>`` comes from upstream's own tags (bare ``0.9.2``, as git.m-labs.hk
  tags migen): ``<tag>-0`` when the upstream commit we build is exactly at a
  tag, otherwise ``<tag>+git<N>.g<sha7>-0`` with ``N`` upstream commits since
  it, or ``0.0+git<N>.g<sha7>-0`` with no tag at all.
- ``<M>`` counts the commits here that aren't upstream's (``upstream..HEAD``).
- ``~deb<R>`` is the suite's Debian release number (sid has none) and
  ``~pr<P>`` marks a pull request preview, exactly as the shared script does.

The shared scripts/deb-version.py implements only Set B so far
(compliance-plan.md, section 3), so this repository carries its own until it
does. build-deb runs it with only ``--write-changelog``; the suite and pull
request number come from the SUITE and PR environment variables build-deb
sets in its container.

The upstream commit is the merge base of HEAD and the ``upstream`` branch, so
a pull request that merges a newer upstream is versioned from what it merges.

Standard library only: it runs inside a bare debian:<suite> container.

    packaging/deb-version.py --suite trixie              # print the version
    SUITE=trixie PR=3 packaging/deb-version.py --write-changelog
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

OWNER_TAG = "fpgasonline"
# Codename -> Debian release number, for ~deb<R>; sid has no suffix. Keep in
# step with the shared script's table.
DEBIAN_RELEASE = {"bookworm": 12, "trixie": 13, "forky": 14}
# Where the mirror of upstream lives: a CI checkout has it as a remote branch,
# a local clone may have it as a branch of its own.
UPSTREAM_REFS = ("origin/upstream", "upstream")
BUILT_FROM = "  * Built from "


def fail(message: str) -> None:
    print(f"deb-version.py: error: {message}", file=sys.stderr)
    sys.exit(1)


def git(src: Path, *args: str, check: bool = True) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(src), *args], capture_output=True, text=True)
    except FileNotFoundError:
        fail("git is not installed")
    if r.returncode != 0:
        if check:
            fail(f"git {' '.join(args)}: {r.stderr.strip()}")
        return None
    return r.stdout.strip()


def upstream_commit(src: Path, ref: str | None) -> str:
    refs = (ref,) if ref else UPSTREAM_REFS
    for r in refs:
        if git(src, "rev-parse", "--verify", "--quiet", f"{r}^{{commit}}", check=False):
            return git(src, "merge-base", "HEAD", r)
    fail(f"no upstream branch (tried {', '.join(refs)}): the version counts our commits "
         "against it. Fetch it, e.g. `git fetch origin upstream`.")


def normalise_tag(tag: str) -> str:
    """An upstream tag as a Debian upstream version: no leading v, - becomes ."""
    return re.sub(r"^(?:migen-|v)", "", tag).replace("-", ".")


def base_version(src: Path, upstream: str) -> str:
    sha7 = upstream[:7]
    describe = git(src, "describe", "--tags", "--long", "--match", "[0-9]*", upstream, check=False)
    if describe is None:
        return f"0.0+git{git(src, 'rev-list', '--count', upstream)}.g{sha7}-0"
    m = re.fullmatch(r"(.+)-(\d+)-g[0-9a-f]+", describe)
    if not m:
        fail(f"can't parse git describe output {describe!r}")
    tag, n = normalise_tag(m.group(1)), int(m.group(2))
    return f"{tag}-0" if n == 0 else f"{tag}+git{n}.g{sha7}-0"


def version(src: Path, suite: str, pr: int | None, ref: str | None = None) -> str:
    if git(src, "rev-parse", "--is-shallow-repository") == "true":
        fail("this is a shallow clone, so the commit counts would be wrong and the "
             "version would go backwards. Check out with `fetch-depth: 0`.")
    upstream = upstream_commit(src, ref)
    ours = git(src, "rev-list", "--count", f"{upstream}..HEAD")
    out = f"{base_version(src, upstream)}+{OWNER_TAG}{ours}"
    codename = suite.removeprefix("raspbian-")
    if codename in DEBIAN_RELEASE:
        out += f"~deb{DEBIAN_RELEASE[codename]}"
    elif codename != "sid":
        fail(f"unknown suite {suite!r} (known: {', '.join([*DEBIAN_RELEASE, 'sid'])})")
    return f"{out}~pr{pr}" if pr else out


def control_field(control: str, field: str) -> str:
    source = control.split("\n\n", 1)[0]
    m = re.search(rf"^{field}:[ \t]*(.+)$", source, re.MULTILINE | re.IGNORECASE)
    if not m:
        fail(f"debian/control has no {field}: in its source paragraph")
    return m.group(1).strip()


def github_repository(src: Path) -> str:
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    url = git(src, "remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else url


def write_changelog(src: Path, ver: str, suite: str) -> None:
    """Put this build's entry above the committed changelog (read from HEAD, so
    running twice doesn't stack two entries)."""
    control = (src / "debian/control").read_text()
    old = git(src, "show", "HEAD:debian/changelog", check=False) or ""
    if BUILT_FROM in old.split("\n -- ", 1)[0]:
        fail("the committed debian/changelog starts with a build's generated entry. "
             "Commit the changelog without it: the build adds its own.")
    entry = (f"{control_field(control, 'Source')} ({ver}) {suite}; urgency=medium\n\n"
             f"{BUILT_FROM}{github_repository(src)}@{git(src, 'rev-parse', 'HEAD')}\n\n"
             f" -- {control_field(control, 'Maintainer')}  "
             f"{git(src, 'log', '-1', '--format=%cd', '--date=rfc2822')}\n")
    (src / "debian/changelog").write_text(entry + ("\n" + old + "\n" if old else ""))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--suite", default=os.environ.get("SUITE"),
                    help="bookworm, trixie, forky or sid (default: $SUITE)")
    ap.add_argument("--pr", type=int, default=int(os.environ["PR"]) if os.environ.get("PR") else None,
                    help="pull request number, for a preview build (default: $PR)")
    ap.add_argument("--upstream-ref", default=None,
                    help=f"the upstream mirror branch (default: the first of {', '.join(UPSTREAM_REFS)})")
    ap.add_argument("--source-dir", type=Path, default=Path("."))
    ap.add_argument("--write-changelog", action="store_true",
                    help="write this build's entry above the committed debian/changelog")
    args = ap.parse_args()
    if not args.suite:
        fail("no suite: pass --suite or set SUITE")
    if args.pr is not None and args.pr <= 0:
        fail(f"the pull request number must be positive, not {args.pr}")
    ver = version(args.source_dir, args.suite, args.pr, args.upstream_ref)
    if args.write_changelog:
        write_changelog(args.source_dir, ver, args.suite)
    print(ver)


if __name__ == "__main__":
    main()
