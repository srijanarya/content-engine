"""Env builder for headless `claude` shell-outs — bills the FACTORY plan.

Plan routing (Srijan, 2026-07-12): all headless lanes run as srijanaryaji@
(CLAUDE_CONFIG_DIR=~/.claude-factory + keychain token claude-headless-token-factory);
the default profile (srijanaryay@) is reserved for interactive sessions. Mirrors
"content creation"/publish/claude_cli.py::_env() — the canonical pattern. Dir-exists
guard keeps this a no-op on machines without the factory profile (e.g. the server).
"""
from __future__ import annotations
import os
import subprocess
from pathlib import Path

FACTORY_CONFIG_DIR = Path.home() / ".claude-factory"


def _keychain_token(service: str = "claude-headless-token-factory") -> str | None:
    r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip() or None if r.returncode == 0 else None


def claude_env() -> dict:
    env = os.environ.copy()
    if FACTORY_CONFIG_DIR.is_dir():
        env["CLAUDE_CONFIG_DIR"] = str(FACTORY_CONFIG_DIR)
        token = _keychain_token()
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env
