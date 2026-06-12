from __future__ import annotations

from . import add_parent_to_sys_path

add_parent_to_sys_path()

from agent_mcp_loop import *  # noqa: F401,F403
from agent_mcp_loop import main


if __name__ == "__main__":
    raise SystemExit(main())
