from __future__ import annotations

from . import add_parent_to_sys_path

add_parent_to_sys_path()

from agent_gcp_baseline_test import *  # noqa: F401,F403
from agent_gcp_baseline_test import main


if __name__ == "__main__":
    raise SystemExit(main())
