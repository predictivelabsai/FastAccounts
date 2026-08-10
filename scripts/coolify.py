#!/usr/bin/env python3
"""Run this repository's deployment through the sibling FastDevOps control plane."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = Path(os.getenv("FASTDEVOPS_DIR", ROOT.parent / "FastDevOps")).resolve()
if not (CONTROL / "cli.py").is_file():
    raise SystemExit("FastDevOps not found; set FASTDEVOPS_DIR to its checkout")
sys.path.insert(0, str(CONTROL))
from cli import catalog, load_local_env, main  # noqa: E402


for key, value in load_local_env(ROOT / ".env").items():
    if key in {"COOLIFY_API_TOKEN", "COOLIFY_BASE_URL"}:
        os.environ.setdefault(key, value)


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                            timeout=5, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _stamp_build_identity() -> None:
    stamp = {
        "FASTACCOUNTS_COMMIT": _git("rev-parse", "--short", "HEAD"),
        "FASTACCOUNTS_BRANCH": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "FASTACCOUNTS_BUILD_DATE": _git("log", "-1", "--format=%cd", "--date=short"),
    }
    if not stamp["FASTACCOUNTS_COMMIT"]:
        print("warning: no git commit available; deployment identity will be unknown")
        return
    if _git("status", "--porcelain"):
        print("warning: working tree is dirty; commit identity may not exactly match deployed files")
    env_path = ROOT / ".env"
    contents = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    for key, value in stamp.items():
        line = f"{key}={value}"
        if re.search(rf"(?m)^{key}=", contents):
            contents = re.sub(rf"(?m)^{key}=.*$", line, contents)
        else:
            contents = contents.rstrip("\n") + f"\n{line}\n"
    env_path.write_text(contents, encoding="utf-8")
    print(f"stamped build identity: {stamp['FASTACCOUNTS_COMMIT']} on {stamp['FASTACCOUNTS_BRANCH']}")


service = next((name for name, spec in catalog().items() if spec.get("local_dir") == ROOT.name), None)
if not service:
    raise SystemExit(f"{ROOT.name} is not declared in FastDevOps")
if len(sys.argv) < 2:
    raise SystemExit("usage: coolify.py validate|doctor|status|provision|env|deploy [options]")
command, *options = sys.argv[1:]
if command in {"env", "deploy"}:
    _stamp_build_identity()
sys.argv = [sys.argv[0], command, *([] if command == "validate" else [service]), *options]
main()
