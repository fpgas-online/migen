#!/usr/bin/env python3
"""Adapt upstream's pyproject.toml to an older setuptools for the build, then undo it.

    debian/pyproject-compat.py apply     # before dh_auto_configure
    debian/pyproject-compat.py restore   # after dh_clean

Only what this suite's setuptools needs is changed, each detected directly
rather than guessed from a version number:

- A PEP 639 licence string (license = "BSD-2-Clause") needs setuptools 77;
  older ones reject it, so it becomes the older {text = "..."} table.
- setuptools' flat-layout discovery learnt to ignore a debian/ directory only
  in later releases; older ones stop with "Multiple top-level packages
  discovered". Then the packages are named: migen and its subpackages.

`apply` keeps the original as debian/pyproject.toml.orig and `restore` puts
it back byte for byte. On a setuptools that needs neither, nothing changes.
"""
import re
import shutil
import sys
from pathlib import Path

import setuptools
from setuptools.discovery import FlatLayoutPackageFinder

PYPROJECT = Path("pyproject.toml")
BACKUP = Path("debian/pyproject.toml.orig")
PACKAGES = '\n[tool.setuptools.packages.find]\ninclude = ["migen", "migen.*"]\n'


def apply() -> None:
    text = PYPROJECT.read_text()
    new = text
    if int(setuptools.__version__.split(".")[0]) < 77:
        new = re.sub(r'^license = "([^"]*)"$', r'license = {text = "\1"}', new, flags=re.MULTILINE)
    if "debian" not in FlatLayoutPackageFinder.DEFAULT_EXCLUDE and "[tool.setuptools.packages" not in new:
        new += PACKAGES
    if new == text:
        print(f"pyproject-compat: setuptools {setuptools.__version__} needs no changes")
        return
    shutil.copy2(PYPROJECT, BACKUP)
    PYPROJECT.write_text(new)
    print(f"pyproject-compat: adapted pyproject.toml for setuptools {setuptools.__version__}")


def restore() -> None:
    if BACKUP.exists():
        shutil.move(BACKUP, PYPROJECT)
        print("pyproject-compat: restored upstream's pyproject.toml")


if __name__ == "__main__":
    {"apply": apply, "restore": restore}[sys.argv[1]]()
