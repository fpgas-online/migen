# migen, packaged for Debian

This repository builds [migen](https://git.m-labs.hk/M-Labs/migen) as the
Debian package `python3-migen` and publishes it as a signed apt repository at
<https://fpgas.online/migen/>. It follows the Set A ("someone else's code")
convention in mithro/apt-repo-action's
[docs/packaging.md](https://github.com/mithro/apt-repo-action/blob/main/docs/packaging.md).

## What it builds

| | |
|---|---|
| upstream | <https://git.m-labs.hk/M-Labs/migen>, branch `master` |
| mirrored on | this repository's `upstream` branch (fast-forward only) |
| built from | `packaging` = `upstream` + `debian/` + `packaging/` + `.github/` |
| first upstream commit packaged | `beffe83` (0.9.2-126-gbeffe83, 2026-09-17) |
| package | `python3-migen`, Architecture: all |
| suites | bookworm, trixie, forky, sid |

migen left GitHub: [m-labs/migen](https://github.com/m-labs/migen) is archived
at `e19524c` ("Repo move"), a commit git.m-labs.hk's master doesn't contain.
This repository is a GitHub fork of it, so its `master`, `legacy` and
`experimental` branches are still that archive. `upstream` was started from
git.m-labs.hk instead.

## What we change, and why

One commit changes an upstream file: `pyproject.toml` names its package
(`[tool.setuptools.packages.find] include = ["migen", "migen.*"]`).
Upstream relies on setuptools' automatic discovery, which refuses to build
once this repository's `packaging/` sits beside `migen/` ("Multiple top-level
packages discovered"). The wheel's contents are the same as upstream's (141
files, compared).

The other difference is at build time on bookworm only: upstream's `pyproject.toml` gives its licence as a PEP 639 string
(`license = "BSD-2-Clause"`), which setuptools accepts only from version 77.
Bookworm has 66, which rejects it, so `debian/rules` rewrites the field to the
older `{text = ...}` table for the build and puts it back afterwards. Newer
suites build upstream's file unchanged.

bookworm is built at all because fpgas.online's Pi NFS root is bookworm
(`.github/apt-packaging.toml`).

Upstream's test suite (`migen/test`) runs in `deb.yml`'s `test` job in each
suite's container, not in the package build: it runs `examples/` from the
source tree, which pybuild's build directory doesn't have.

## Versions

`packaging/deb-version.py` stamps each build (the shared script doesn't do
Set A yet):

```
0.9.2+git126.gbeffe83-0+fpgasonline5~deb13
^^^^^ ^^^^^^^^^^^^^^^   ^^^^^^^^^^^^^ ^^^^^
|     upstream commits  our commits    suite (none on sid); ~pr<P> on previews
upstream's newest tag   since the tag  (upstream..packaging)
```

## Updating to a new upstream

The `Sync upstream` workflow does this every Monday, and on demand from the
Actions tab:

1. it fast-forwards `upstream` to git.m-labs.hk's master and mirrors its tags;
2. it merges that into `packaging` on the branch `sync/upstream` and opens the
   pull request "Merge upstream <describe>", then builds it.

Review the pull request and merge it **with a merge commit**; that publishes
the new version. If the merge conflicts, or git.m-labs.hk rewrote its history,
the workflow stops with an error saying so (a conflict is most likely in
`pyproject.toml`, the one upstream file changed here), and the merge is done by hand the
same way: merge `upstream` into a branch off `packaging` and open a pull
request.

## Install

Key fingerprint: `FINGERPRINT-TO-BE-ADDED` (fill in when the signing key exists)

```sh
sudo install -d -m0755 /etc/apt/keyrings
curl -fsSL https://fpgas.online/migen/migen.gpg | sudo tee /etc/apt/keyrings/migen.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/migen.gpg] https://fpgas.online/migen/trixie/ ./" \
  | sudo tee /etc/apt/sources.list.d/migen.list
sudo apt update
sudo apt install python3-migen
```

For another suite, replace `trixie` with `bookworm`, `forky` or `sid`.
