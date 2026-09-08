"""Subscription-only text routing: Claude, then ChatGPT-backed Codex, then configured bulk.

Account routing (Srijan, 2026-08-06 cutover): EVERYTHING runs as srijanaryay@gmail.com —
srijanaryaji@ is retired (subscription ended 2026-08-06). The factory profile
(CLAUDE_CONFIG_DIR=~/.claude-factory + keychain token claude-headless-token-factory)
is kept only as env isolation for headless lanes, same account as default. Mirrors
"content creation"/publish/claude_cli.py::_env() — the canonical Claude profile pattern.
"""
from __future__ import annotations
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

FACTORY_CONFIG_DIR = Path.home() / ".claude-factory"
CODEX_HOME = Path.home() / ".codex"
CODEX_BIN = "/Users/srijan/.npm-global/bin/codex"
CODEX_MODEL = "gpt-5.6-terra"

_ENV_KEYS = ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "USER", "LOGNAME",
             "SHELL", "TERM", "NO_COLOR")
_AUTH_FAILURE_NOTICES = (
    "401", "unauthorized", "authentication", "not logged in", "invalid api key",
    "oauth", "subscription unavailable", "subscription access disabled",
)
_QUOTA_FAILURE_NOTICES = (
    "usage limit", "session limit", "rate limit", "quota", "limit reached",
)
_BILLING_FAILURE_NOTICES = (
    "spend limit", "billing", "payment required", "credit balance",
)

# ponytail: process-local cache only; a fresh scheduled run retries each preferred provider.
_UNHEALTHY: set[str] = set()


@dataclass(frozen=True)
class TextResult:
    text: str
    provider: str


class _ProviderFailure(RuntimeError):
    """Internal provider failure carrying only a safe diagnostic category."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


def _clean_env() -> dict:
    return {name: os.environ[name] for name in _ENV_KEYS if name in os.environ}


def _failed_process_category(stdout: str | None, stderr: str | None, returncode: int) -> str:
    """Classify a process already known to have failed without retaining its raw output."""
    detail = f"{stdout or ''}\n{stderr or ''}".lower()
    if any(notice in detail for notice in _AUTH_FAILURE_NOTICES):
        return "authentication"
    if any(notice in detail for notice in _BILLING_FAILURE_NOTICES):
        return "billing"
    if any(notice in detail for notice in _QUOTA_FAILURE_NOTICES):
        return "quota"
    return "empty_output" if returncode == 0 else "execution_failure"


def _exception_category(exc: BaseException) -> str:
    if isinstance(exc, _ProviderFailure):
        return exc.category
    if isinstance(exc, FileNotFoundError):
        return "missing_cli"
    if isinstance(exc, subprocess.TimeoutExpired):
        return "timeout"
    return "execution_failure"


def _safe_log_value(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._:/-" else "_" for ch in value)
    return safe[:80] or "unknown"


def _log_selection(provider: str, failures: list[tuple[str, str]]) -> None:
    line = f"[llm] provider={_safe_log_value(provider)}"
    if failures:
        reason = ",".join(f"{name}:{category}" for name, category in failures)
        line += f" fallback_reason={reason}"
    print(line, file=sys.stderr)


def _keychain_token(service: str = "claude-headless-token-factory") -> str | None:
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def claude_env() -> dict:
    env = _clean_env()
    if FACTORY_CONFIG_DIR.is_dir():
        env["CLAUDE_CONFIG_DIR"] = str(FACTORY_CONFIG_DIR)
        token = _keychain_token()
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env


def _codex_env() -> dict:
    env = _clean_env()
    env["CODEX_HOME"] = str(CODEX_HOME)
    return env


def _full_prompt(prompt: str, system: str | None) -> str:
    return f"{system}\n\n{prompt}" if system else prompt


def _run_claude(prompt: str, system: str | None, timeout: int) -> str:
    out = subprocess.run(
        ["claude", "-p", _full_prompt(prompt, system)],
        capture_output=True, text=True, timeout=timeout, env=claude_env(),
    )
    text = (out.stdout or "").strip()
    if out.returncode != 0 or not text:
        raise _ProviderFailure(_failed_process_category(out.stdout, out.stderr, out.returncode))
    return text


def _run_codex(prompt: str, system: str | None, timeout: int) -> str:
    env = _codex_env()
    status = subprocess.run(
        [CODEX_BIN, "login", "status"], capture_output=True, text=True,
        timeout=min(timeout, 15), env=env,
    )
    status_lines = [line.strip() for line in f"{status.stdout}\n{status.stderr}".splitlines()
                    if line.strip()]
    if status.returncode != 0 or "Logged in using ChatGPT" not in status_lines:
        raise _ProviderFailure("subscription_auth")

    with tempfile.TemporaryDirectory() as td:
        output = Path(td) / "last-message.txt"
        out = subprocess.run(
            [CODEX_BIN, "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules",
             "--disable", "shell_tool", "--disable", "unified_exec",
             "--disable", "multi_agent", "--disable", "multi_agent_v2",
             "--sandbox", "read-only", "--skip-git-repo-check", "-m", CODEX_MODEL,
             "-C", td, "-o", str(output), "-"],
            input=_full_prompt(prompt, system), capture_output=True, text=True,
            timeout=timeout, env=env,
        )
        text = output.read_text().strip() if output.exists() else ""
    if out.returncode != 0 or not text:
        raise _ProviderFailure(_failed_process_category(out.stdout, out.stderr, out.returncode))
    return text


def _run_bulk(prompt: str, system: str | None) -> TextResult | None:
    base = os.environ.get("BULK_BASE_URL")
    token = os.environ.get("BULK_AUTH_TOKEN")
    model = os.environ.get("BULK_MODEL")
    if not (base and token and model):
        return None
    import anthropic
    client = anthropic.Anthropic(api_key=token, base_url=base)
    msg = client.messages.create(
        model=model, max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
        **({"system": system} if system else {}),
    )
    text = msg.content[0].text.strip()
    if not text:
        raise RuntimeError("bulk provider returned no text")
    return TextResult(text, model)


def run_text(prompt: str, system: str | None = None, timeout: int = 300) -> TextResult:
    """Return generated text and the provider actually used; never changes authentication."""
    failed: list[tuple[str, str]] = []
    legacy: list[str] = []
    if "claude-cli" not in _UNHEALTHY:
        try:
            result = TextResult(_run_claude(prompt, system, timeout), "claude-cli")
            _log_selection(result.provider, failed)
            return result
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
            _UNHEALTHY.add("claude-cli")
            failed.append(("claude-cli", _exception_category(exc)))
    else:
        failed.append(("claude-cli", "cached_unhealthy"))
    legacy.append("claude-cli")

    if "codex" not in _UNHEALTHY:
        try:
            result = TextResult(_run_codex(prompt, system, timeout), f"codex:{CODEX_MODEL}")
            _log_selection(result.provider, failed)
            return result
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
            _UNHEALTHY.add("codex")
            failed.append(("codex", _exception_category(exc)))
    else:
        failed.append(("codex", "cached_unhealthy"))
    legacy.append("codex")

    try:
        bulk = _run_bulk(prompt, system)
        if bulk:
            _log_selection(bulk.provider, failed)
            return bulk
        failed.append(("bulk", "not_configured"))
        legacy.append("bulk not configured")
    except Exception:
        failed.append(("bulk", "execution_failure"))
        legacy.append("bulk")
    _log_selection("none", failed)
    diagnostics = "; ".join(f"{name}={category}" for name, category in failed)
    raise RuntimeError(
        "text generation failed: " + "; ".join(legacy) + f" [diagnostics: {diagnostics}]"
    )
