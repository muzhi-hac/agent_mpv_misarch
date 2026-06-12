from __future__ import annotations

"""Make `python -m scripts...` work even when launched from `scripts/`."""

import pathlib
import sys


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


repo_root = str(_repo_root())
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
