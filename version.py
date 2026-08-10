"""FastAccounts build identity."""
from __future__ import annotations

import os
from pathlib import Path


VERSION = (Path(__file__).parent / "VERSION").read_text(encoding="utf-8").strip()


def label() -> str:
    commit = os.getenv("FASTACCOUNTS_COMMIT", "").strip()
    return f"v{VERSION}" + (f" · {commit[:7]}" if commit else "")


def detail() -> str:
    branch = os.getenv("FASTACCOUNTS_BRANCH", "").strip() or "local"
    build_date = os.getenv("FASTACCOUNTS_BUILD_DATE", "").strip() or "development"
    return f"FastAccounts {label()} · {branch} · {build_date}"
