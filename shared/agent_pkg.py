"""The starter/solution agent-package seam (packaging P1.2; moved here in P1.4).

AGENT_PACKAGE selects WHICH agent package the rest of the system loads. For the
live spine (the commentator), that is:

    solution.commentator   the complete reference (the answer key)
    starter.commentator    the student build

Both packages mirror the same file layout (agent, prompts, config, snapshot,
tools.frame_tools), so every consumer resolves modules through agent_module()
below and works unchanged whichever package is active. (Re-aimed from Ch2, whose
seam pointed at race_engineer and whose frame tools lived in the package; the
commentator shares the vendored shared.state_client.)

WHY THIS LIVES IN shared/: every consumer needs it — the frontend (commentator
loop, state poller, agent client) AND the dev scripts (local_commentator,
test_frame_tools). shared/ is an installed package; frontend/ is not. Putting the
resolver here means `python scripts/local_commentator.py` resolves the exact same
package the frontend does, with no sys.path games.

The code default is solution.commentator so the deployed engine-mode container
(which never sources activate.sh) gets the reference. activate.sh exports the
per-session choice — starter.commentator by default for local work; instructors
override with AGENT_PACKAGE=solution.commentator.
"""
from __future__ import annotations

import importlib
import os

AGENT_PACKAGE = os.environ.get("AGENT_PACKAGE", "solution.commentator").strip()


def agent_module(sub: str = ""):
    """Import a module from the ACTIVE agent package.

    agent_module("config")           -> e.g. starter.commentator.config
    agent_module("tools.frame_tools") -> e.g. starter.commentator.tools.frame_tools
    agent_module("agent")            -> the module exposing root_agent

    Raises ImportError naming the resolved module on a typo'd or missing
    package — fail loudly, don't fall back.
    """
    name = AGENT_PACKAGE + (f".{sub}" if sub else "")
    try:
        return importlib.import_module(name)
    except ImportError as e:
        raise ImportError(
            f"AGENT_PACKAGE={AGENT_PACKAGE!r}: could not import {name!r}. "
            "Valid values are 'solution.commentator' (the reference) or "
            "'starter.commentator' (the student build). Did you run "
            "'pip install -e .' after changing packages?"
        ) from e
