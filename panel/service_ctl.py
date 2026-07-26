"""
systemctl wrapper scoped to momir.service (start/stop/enable/disable/status).

Read-only queries (`is-active`/`is-enabled`) run unprivileged; the mutating
verbs run under sudo per the panel's scoped sudoers grant (see
scripts/setup_pi_ap.sh). Degrades to a "not supported" response when
systemctl isn't installed (Mac dev).
"""
import shutil
import subprocess

SERVICE = "momir.service"


def _available() -> bool:
    return shutil.which("systemctl") is not None


def _run(args: list[str], sudo: bool = False, timeout: int = 10):
    cmd = (["sudo"] if sudo else []) + args
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def status() -> dict:
    if not _available():
        return {"supported": False}
    active = _run(["systemctl", "is-active", SERVICE])
    enabled = _run(["systemctl", "is-enabled", SERVICE])
    return {
        "supported": True,
        "active": bool(active and active.stdout.strip() == "active"),
        "enabled": bool(enabled and enabled.stdout.strip() == "enabled"),
    }


def _verb(verb: str) -> None:
    if not _available():
        raise RuntimeError("systemctl not available on this platform")
    result = _run(["systemctl", verb, SERVICE], sudo=True, timeout=20)
    if result is None or result.returncode != 0:
        raise RuntimeError(f"systemctl {verb} failed: {result.stderr.strip() if result else 'error'}")


def start() -> None:
    _verb("start")


def stop() -> None:
    _verb("stop")


def enable() -> None:
    _verb("enable")


def disable() -> None:
    _verb("disable")
