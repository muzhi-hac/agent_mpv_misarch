from __future__ import annotations

import pathlib
import sys


def add_parent_to_sys_path() -> None:
    parent = str(pathlib.Path(__file__).resolve().parents[1])
    if parent not in sys.path:
        sys.path.insert(0, parent)
