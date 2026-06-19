"""Assemble the self-contained Agent Engine deployment folder (chunk 12;
P1.6 fix: agent_pkg excluded from staging, stale check matches imports only).

Why this exists: `adk deploy agent_engine` stages ONLY the folder you point
it at (source_packages = [that folder] — set unconditionally, no extra-
packages mechanism in this CLI generation). Our agent imports two top-level
repo packages (`solution.race_engineer.*`, `shared.*`) that would not exist
on the engine. So we build `build/engine_app/`:

    engine_app/
      __init__.py
      agent.py            <- sys.path bootstrap + re-exports root_agent
                             (the CLI's generated app does `from .agent
                             import root_agent`, so this name is required)
      race_engineer/      <- vendored copy of solution/race_engineer/, with
                             imports rewritten solution.race_engineer -> race_engineer
                             (renamed to avoid colliding with agent.py above)
      shared/             <- vendored verbatim (no clash, no rewrite),
                             EXCEPT agent_pkg.py: the starter/solution seam
                             is a CLIENT-side concept (frontend + dev
                             scripts choose a package); the engine IS the
                             solution agent and never imports it. Staging it
                             would ship dead code whose docstring/env-default
                             legitimately mention "solution.race_engineer".
      requirements.txt    <- engine runtime deps (CLI appends its own too)
      .env                <- engine env: Vertex mode, model location, TOOLBOX_URL

Run from the repo root:  python3 deploy/build_engine_app.py
Idempotent: wipes and rebuilds build/engine_app each time.
DEPLOY_AGENT_PACKAGE picks the source package (default
solution.race_engineer; bonus: starter.race_engineer ships your own
agent). Deliberately its OWN knob — NOT activate.sh's AGENT_PACKAGE,
whose starter default would footgun instructor deploys.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
BUILD = REPO / "build" / "engine_app"
TOOLBOX_URL = os.environ.get("TOOLBOX_URL", "")
PROJECT_ID = os.environ.get("PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT", "")

# Which agent package gets vendored onto the engine. Its OWN env knob on
# purpose: activate.sh's AGENT_PACKAGE defaults to starter for local dev,
# and inheriting that here would silently deploy stubs as the reference.
AGENT_PACKAGE = os.environ.get("DEPLOY_AGENT_PACKAGE", "solution.race_engineer")
PKG_PATH = REPO.joinpath(*AGENT_PACKAGE.split("."))

AGENT_PY = '''"""Agent Engine entrypoint shim.

The deploy CLI generates an app file that does `from .agent import
root_agent`, so this module must exist under this exact name. It bootstraps
sys.path so the vendored `race_engineer` and `shared` packages resolve as
top-level absolute imports, then re-exports the agent.
"""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from race_engineer.agent import root_agent  # noqa: E402,F401
'''

REQUIREMENTS = """google-adk[toolbox]>=1.0,<2
toolbox-core==1.1.0
google-cloud-firestore>=2.16
pydantic>=2.7
"""

ENV = f"""GOOGLE_GENAI_USE_VERTEXAI=1
GOOGLE_CLOUD_LOCATION=global
TOOLBOX_URL={TOOLBOX_URL}
PROJECT_ID={PROJECT_ID}
"""

# Rewrite the SOURCE package path to the vendored top-level name; both
# patterns parameterized on AGENT_PACKAGE so the bonus path
# (starter.race_engineer) vendors just as cleanly as the reference.
REWRITE_RE = re.compile(r"\b" + re.escape(AGENT_PACKAGE) + r"\b")
# A REAL unrewritten import of the source package path — what the stale
# check hunts for. Matches import statements only, not docstrings,
# comments, or string literals (shared/agent_pkg.py's env default taught
# us why).
STALE_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+" + re.escape(AGENT_PACKAGE) + r"\b",
    re.MULTILINE,
)


def vendor(src: pathlib.Path, dst: pathlib.Path, rewrite: bool,
           extra_ignore: tuple[str, ...] = ()) -> int:
    shutil.copytree(
        src, dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env",
                                      *extra_ignore),
    )
    rewritten = 0
    if rewrite:
        for py in dst.rglob("*.py"):
            text = py.read_text()
            new = REWRITE_RE.sub("race_engineer", text)
            if new != text:
                py.write_text(new)
                rewritten += 1
    return rewritten


def main() -> None:
    if not TOOLBOX_URL:
        sys.exit("TOOLBOX_URL is not set — run `source activate.sh` first "
                 "so the engine knows where MCP Toolbox lives.")
    if not PROJECT_ID:
        sys.exit("PROJECT_ID is not set — run `source activate.sh` first.")

    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)

    if not (PKG_PATH / "agent.py").is_file():
        sys.exit(f"DEPLOY_AGENT_PACKAGE={AGENT_PACKAGE} has no agent.py at "
                 f"{PKG_PATH} — expected a package like solution.race_engineer.")
    n = vendor(PKG_PATH, BUILD / "race_engineer", rewrite=True)
    vendor(REPO / "shared", BUILD / "shared", rewrite=False,
           extra_ignore=("agent_pkg.py",))  # client-side seam; see module docstring

    (BUILD / "__init__.py").write_text("")
    (BUILD / "agent.py").write_text(AGENT_PY)
    (BUILD / "requirements.txt").write_text(REQUIREMENTS)
    (BUILD / ".env").write_text(ENV)

    # Self-checks: no staged module may still IMPORT the old package path
    # (docstrings and string literals are fine), the seam module must not
    # have been staged, and the vendored tree must import cleanly.
    stale = [str(p) for p in BUILD.rglob("*.py")
             if STALE_IMPORT_RE.search(p.read_text())]
    assert not stale, f"unrewritten imports remain: {stale}"
    assert not (BUILD / "shared" / "agent_pkg.py").exists(), \
        "agent_pkg.py staged — it must stay client-side"
    sys.path.insert(0, str(BUILD))
    import importlib
    mod = importlib.import_module("race_engineer.prompts")  # no GCP deps at import
    assert hasattr(mod, "build_event_reaction_prompt")
    print(f"Staged {BUILD}")
    print(f"  race_engineer/: vendored from {AGENT_PACKAGE} "
          f"({n} files had imports rewritten)")
    print(f"  shared/: vendored (agent_pkg.py excluded — client-side seam)")
    print(f"  TOOLBOX_URL baked into .env: {TOOLBOX_URL}")
    print("Import self-check passed (race_engineer.prompts loads from the staged tree).")


if __name__ == "__main__":
    main()
