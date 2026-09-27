#!/usr/bin/env python3
"""The package version and changelog for one build: upstream's version, then ours.

    <upstream>+fpgasonline.<packaging>[~deb<R>][~pr<P>]
    0.9.2.post126+fpgasonline.0.0.post5~deb13

- ``<upstream>`` is the mirrored upstream branch's own ``git describe`` against
  upstream's tags (bare, like ``0.9.2``): the tag, then ``.post<N>`` for the N
  commits since it. ``0.0.post<N>`` if upstream has no tag.
- ``<packaging>`` is this branch's ``git describe`` against our ``vX.Y`` tags,
  the same way: ``0.0.post5`` is five commits after ``v0.0``.
- ``~deb<R>`` is the suite's Debian release number (sid has none) and
  ``~pr<P>`` marks a pull request preview; both as in apt-repo-action's
  docs/packaging.md ("Versions").

So a new upstream commit or a new packaging commit each raise the version.
This is the "patch series" form of docs/packaging.md; the shared
scripts/deb-version.py doesn't implement it yet.

--write-changelog writes the whole debian/changelog (none is committed): one
entry naming both commits, dated with the later of their committer times so
the build is reproducible (dpkg-buildpackage takes SOURCE_DATE_EPOCH from it).

    packaging/deb-version.py --source src --suite trixie
    packaging/deb-version.py --source src --suite trixie --pr 3 --write-changelog src/debian/changelog

Standard library only.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

OWNER_TAG = "fpgasonline"
# Codename -> Debian release number, for ~deb<R>; sid has no suffix. Keep in
# step with apt-repo-action's scripts/deb-version.py.
DEBIAN_RELEASE = {"bookworm": 12, "trixie": 13, "forky": 14}
HERE = Path(__file__).resolve().parent.parent


def fail(message: str) -> None:
    print(f"deb-version.py: error: {message}", file=sys.stderr)
    sys.exit(1)


def git(repo: Path, *args: str, check: bool = True) -> str | None:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if r.returncode != 0:
        if check:
            fail(f"git -C {repo} {' '.join(args)}: {r.stderr.strip()}")
        return None
    return r.stdout.strip()


def describe(repo: Path, match: str, strip: str) -> str:
    """<tag>[.post<N>] for HEAD of `repo`, against tags matching `match`."""
    if git(repo, "rev-parse", "--is-shallow-repository") == "true":
        fail(f"{repo} is a shallow clone, so the commit count would be wrong and the "
             "version would go backwards. Check out with `fetch-depth: 0`.")
    d = git(repo, "describe", "--tags", "--long", "--match", match, "HEAD", check=False)
    if d is None:
        return f"0.0.post{git(repo, 'rev-list', '--count', 'HEAD')}"
    m = re.fullmatch(r"(.+)-(\d+)-g[0-9a-f]+", d)
    if not m:
        fail(f"can't parse git describe output {d!r} in {repo}")
    tag = re.sub(strip, "", m.group(1)).replace("-", ".")
    n = int(m.group(2))
    return tag if n == 0 else f"{tag}.post{n}"


def version(source: Path, packaging: Path, suite: str, pr: int | None) -> str:
    out = (f"{describe(source, '[0-9]*', r'^(?:migen-|v)')}"
           f"+{OWNER_TAG}.{describe(packaging, 'v[0-9]*', r'^v')}")
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


def changelog(source: Path, packaging: Path, ver: str, suite: str) -> str:
    control = (packaging / "debian/control").read_text()
    repo = os.environ.get("GITHUB_REPOSITORY", "fpgas-online/migen")
    when = max(int(git(r, "log", "-1", "--format=%ct")) for r in (source, packaging))
    upstream = git(source, "describe", "--tags", "--always", "--match", "[0-9]*", "HEAD")
    return (f"{control_field(control, 'Source')} ({ver}) {suite}; urgency=medium\n\n"
            f"  * Built from {repo}: packaging@{git(packaging, 'rev-parse', 'HEAD')}\n"
            f"    and upstream@{git(source, 'rev-parse', 'HEAD')} ({upstream}).\n\n"
            f" -- {control_field(control, 'Maintainer')}  "
            f"{time.strftime('%a, %d %b %Y %H:%M:%S +0000', time.gmtime(when))}\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", type=Path, required=True,
                    help="checkout of the mirrored upstream branch")
    ap.add_argument("--packaging", type=Path, default=HERE,
                    help="checkout of the packaging branch (default: this script's)")
    ap.add_argument("--suite", required=True, help="bookworm, trixie, forky or sid")
    ap.add_argument("--pr", type=int, default=None, help="pull request number, for a preview")
    ap.add_argument("--write-changelog", type=Path, metavar="PATH",
                    help="write the whole debian/changelog for this build to PATH")
    args = ap.parse_args()
    if args.pr is not None and args.pr <= 0:
        fail(f"the pull request number must be positive, not {args.pr}")
    ver = version(args.source, args.packaging, args.suite, args.pr)
    if args.write_changelog:
        args.write_changelog.write_text(changelog(args.source, args.packaging, ver, args.suite))
    print(ver)


if __name__ == "__main__":
    main()
