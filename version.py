"""FastAccounts build identity.

VERSION file: line 1 is the semver, line 2 the release date (YYYY-MM-DD).
"""
from __future__ import annotations

import os
from pathlib import Path


_LINES = [line.strip() for line in (Path(__file__).parent / "VERSION").read_text(encoding="utf-8").splitlines() if line.strip()]
VERSION = _LINES[0] if _LINES else "0.0.0"
RELEASE_DATE = _LINES[1] if len(_LINES) > 1 else ""


def label() -> str:
    """Version chip text: v{version} · {release date}."""
    return f"v{VERSION}" + (f" · {RELEASE_DATE}" if RELEASE_DATE else "")


def detail() -> str:
    commit = os.getenv("FASTACCOUNTS_COMMIT", "").strip()
    branch = os.getenv("FASTACCOUNTS_BRANCH", "").strip() or "local"
    build_date = os.getenv("FASTACCOUNTS_BUILD_DATE", "").strip() or "development"
    return f"FastAccounts {label()}" + (f" · {commit[:7]}" if commit else "") + f" · {branch} · {build_date}"
