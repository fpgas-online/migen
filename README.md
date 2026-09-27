# migen, packaged for Debian

This repository keeps an exact copy of [migen](https://git.m-labs.hk/M-Labs/migen)
from git.m-labs.hk and builds it as the Debian package `python3-migen`,
published as a signed apt repository at <https://fpgas.online/migen/>.

## Branches

| branch | what | history |
|---|---|---|
| `packaging` (default) | `debian/`, `packaging/` and `.github/`: the build and the sync. No migen source. | its own, unrelated to migen's |
| `master` (and any other upstream branch) | an exact copy of git.m-labs.hk's branch of the same name, and its tags | upstream's |
| `github-master`, `legacy`, `experimental` | the archived GitHub [m-labs/migen](https://github.com/m-labs/migen) this repository was forked from (`github-master` was its `master`, e19524c "Repo move") | GitHub's |

Nothing is ever committed to a mirrored branch. Changes to how migen is
packaged are pull requests against `packaging`.

## How it runs

- **Sync upstream** (`.github/workflows/sync-upstream.yml`, daily at 06:00 UTC
  and on demand) runs `packaging/sync-mirror.py`, which copies every branch
  and tag of git.m-labs.hk here under the same name, forced, so each is
  always identical to upstream's. Our own branches are never touched and
  nothing is deleted. When `master` moved, it starts **Debian packages**.
- **Debian packages** (`.github/workflows/deb.yml`, on every push to
  `packaging`, when Sync upstream starts it, and on pull requests without
  publishing) checks out `master`, adds `debian/` from `packaging`, runs
  upstream's tests in each suite, builds `python3-migen` for bookworm,
  trixie, forky and sid, install-tests each one, and publishes.

A new upstream commit is published the day it lands, with no review.

## Versions

`packaging/deb-version.py`: upstream's version, then ours.

```
0.9.2.post126+fpgasonline.0.0.post5~deb13
^^^^^^^^^^^^^             ^^^^^^^^^ ^^^^^
|                         |         suite (none on sid); ~pr<P> on previews
|                         this branch: 5 commits after v0.0
upstream: 126 commits after its 0.9.2 tag
```

Either a new upstream commit or a new packaging commit raises it.

## What the packaging changes

Nothing in upstream's files. On bookworm only, `debian/pyproject-compat.py`
adapts `pyproject.toml` to setuptools 66 while it builds, and puts upstream's
file back afterwards:
- the PEP 639 licence string (`license = "BSD-2-Clause"`) becomes the older
  `{text = ...}` table, which 66 accepts (newer setuptools deprecate it);
- the package is named (`migen`, `migen.*`), since 66's automatic discovery
  counts the build's `debian/` directory as a second package.

Newer suites build upstream's file unchanged. bookworm is built because
fpgas.online's Pi NFS root is bookworm.

Upstream's test suite runs in `deb.yml`'s `test` job rather than the package
build, since it runs `examples/` from the source tree.

## Install

Key fingerprint: `6A8D04C7B8C61FB19ADDF3768FEB36D965468C2C`

```sh
sudo install -d -m0755 /etc/apt/keyrings
curl -fsSL https://fpgas.online/migen/migen.gpg | sudo tee /etc/apt/keyrings/migen.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/migen.gpg] https://fpgas.online/migen/trixie/ ./" \
  | sudo tee /etc/apt/sources.list.d/migen.list
sudo apt update
sudo apt install python3-migen
```

For another suite, replace `trixie` with `bookworm`, `forky` or `sid`.

## Licence

migen is BSD-2-Clause (M-Labs); see `LICENSE` on `master`. The packaging here
is under the same licence (`debian/copyright`).
