"""Sanity checks for scripts in this repo.

Use at the top of any script that depends on the project venv:

    from shared.script_env import require_venv
    require_venv()
"""
from __future__ import annotations

import os
import sys


def require_venv() -> None:
    """Fail fast with a friendly message if the project venv isn't active.

    Catches the common "forgot to source activate.sh in a new tab" failure
    mode — produces a clear error instead of a downstream ModuleNotFoundError.
    """
    if "VIRTUAL_ENV" not in os.environ:
        msg = (
            "\n"
            "ERROR: The project virtual environment is not active.\n"
            "\n"
            "  Fix: source activate.sh (from the repo root)\n"
            "\n"
            "This script needs the venv to import shared/, agent/, "
            "google-cloud-firestore, etc.\n"
        )
        print(msg, file=sys.stderr)
        sys.exit(1)