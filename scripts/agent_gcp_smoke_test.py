#!/usr/bin/env python3
from __future__ import annotations

"""Backward-compatible entrypoint for the renamed baseline test module."""

from scripts.agent_gcp_baseline_test import *  # noqa: F401,F403
from scripts.agent_gcp_baseline_test import main


if __name__ == "__main__":
    raise SystemExit(main())
