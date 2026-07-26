"""
nmcli wrapper for wlan0 client/AP switching and eth0 status.

Every mutating call passes argument lists straight to subprocess (never a
shell string) since SSIDs/passwords are user-supplied. Every function
degrades to a "not supported" response when nmcli isn't installed, so the
panel can still run (for UI iteration) on a Mac dev machine.

`connection.autoconnect-priority` on each saved nmcli Wi-Fi profile is the
single source of truth for join order — there's no separate priority list
to keep in sync.
"""
import shutil
import subprocess

AP_CONN_NAME = "momir-ap"
WIFI_IFACE = "wlan0"
ETH_IFACE = "eth0"
WIFI_CONN_PREFIX = "momir-wifi-"


def _available() -> bool:
    return shutil.which("nmcli") is not None


def _run(args: list[str], sudo: bool = False, timeout: int = 10):
    cmd = (["sudo"] if sudo else []) + args
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def _get_field(conn_name: str, field: str) -> str | None:
    result = _run(["nmcli", "-t", "-g", field, "connection", "show", conn_name])
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip()


def eth_connected() -> bool:
    if not _available():
        return False
    result = _run(["nmcli", "-t", "-f", "DEVICE,STATE", "device", "status"])
    if result is None or result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        device, _, state = line.partition(":")
        if device == ETH_IFACE:
            return state.strip() == "connected"
    return False


def current_wlan_connection() -> str | None:
    """Active connection name on wlan0, or None if disconnected/idle."""
    if not _available():
        return None
    result = _run(["nmcli", "-t", "-f", "DEVICE,STATE,CONNECTION", "device", "status"])
    if result is None or result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[0] == WIFI_IFACE:
            state = parts[1]
            conn = ":".join(parts[2:])
            if state == "connected" and conn and conn != "--":
                return conn
    return None


def scan_wifi(rescan: bool = True) -> list[str]:
    """SSIDs currently visible to wlan0 (deduped, order as reported)."""
    if not _available():
        return []
    args = ["nmcli", "-t", "-f", "SSID", "device", "wifi", "list", "ifname", WIFI_IFACE]
    if rescan:
        args += ["--rescan", "yes"]
    result = _run(args, timeout=15)
    if result is None or result.returncode != 0:
        return []
    ssids: list[str] = []
    for line in result.stdout.splitlines():
        ssid = line.strip()
        if ssid and ssid not in ssids:
            ssids.append(ssid)
    return ssids


def _wifi_connection_names() -> list[str]:
    result = _run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    if result is None or result.returncode != 0:
        return []
    names = []
    for line in result.stdout.splitlines():
        name, _, conn_type = line.rpartition(":")
        if conn_type == "802-11-wireless" and name:
            names.append(name)
    return names


def list_saved_wifi() -> list[dict]:
    """Saved client Wi-Fi profiles (excludes the AP profile), highest
    priority first, each flagged with whether it's currently in range."""
    if not _available():
        return []
    visible = set(scan_wifi(rescan=False))
    entries = []
    for name in _wifi_connection_names():
        if name == AP_CONN_NAME:
            continue
        ssid = _get_field(name, "802-11-wireless.ssid") or ""
        try:
            priority = int(_get_field(name, "connection.autoconnect-priority") or "0")
        except ValueError:
            priority = 0
        entries.append({
            "id": name,
            "ssid": ssid,
            "priority": priority,
            "in_range": ssid in visible,
        })
    entries.sort(key=lambda e: e["priority"], reverse=True)
    return entries


def add_wifi(ssid: str, password: str) -> str:
    if not _available():
        raise RuntimeError("nmcli not available on this platform")
    conn_name = f"{WIFI_CONN_PREFIX}{ssid}"
    _run(["nmcli", "connection", "delete", conn_name], sudo=True)  # clear any stale same-name profile

    added = _run([
        "nmcli", "connection", "add", "type", "wifi", "ifname", WIFI_IFACE,
        "con-name", conn_name, "autoconnect", "yes", "ssid", ssid,
    ], sudo=True)
    if added is None or added.returncode != 0:
        raise RuntimeError(f"failed to add network: {added.stderr.strip() if added else 'nmcli error'}")

    existing_priorities = [e["priority"] for e in list_saved_wifi() if e["id"] != conn_name]
    next_priority = (min(existing_priorities) - 10) if existing_priorities else 60

    configured = _run([
        "nmcli", "connection", "modify", conn_name,
        "connection.autoconnect-priority", str(next_priority),
        "wifi-sec.key-mgmt", "wpa-psk",
        "wifi-sec.psk", password,
    ], sudo=True)
    if configured is None or configured.returncode != 0:
        _run(["nmcli", "connection", "delete", conn_name], sudo=True)
        raise RuntimeError(f"failed to configure network: {configured.stderr.strip() if configured else 'nmcli error'}")

    return conn_name


def remove_wifi(conn_id: str) -> None:
    if not _available():
        raise RuntimeError("nmcli not available on this platform")
    if conn_id == AP_CONN_NAME:
        raise ValueError("cannot remove the access point profile")
    result = _run(["nmcli", "connection", "delete", conn_id], sudo=True)
    if result is None or result.returncode != 0:
        raise RuntimeError(f"failed to remove network: {result.stderr.strip() if result else 'nmcli error'}")


def reorder_wifi(order: list[str]) -> None:
    """Rewrites autoconnect-priority on each saved profile to match the
    given order (index 0 = highest priority)."""
    if not _available():
        raise RuntimeError("nmcli not available on this platform")
    total = len(order)
    for index, conn_id in enumerate(order):
        if conn_id == AP_CONN_NAME:
            continue
        priority = (total - index) * 10
        _run(["nmcli", "connection", "modify", conn_id,
              "connection.autoconnect-priority", str(priority)], sudo=True)


def activate_connection(conn_id: str) -> bool:
    result = _run(["nmcli", "connection", "up", conn_id, "ifname", WIFI_IFACE], sudo=True, timeout=30)
    return result is not None and result.returncode == 0


def deactivate_wlan() -> bool:
    result = _run(["nmcli", "device", "disconnect", WIFI_IFACE], sudo=True, timeout=15)
    return result is not None and result.returncode == 0


def get_status() -> dict:
    if not _available():
        return {"supported": False}
    conn = current_wlan_connection()
    eth_ok = eth_connected()
    if conn == AP_CONN_NAME:
        mode = "ap"
    elif conn:
        mode = "wifi-client"
    elif eth_ok:
        mode = "ethernet-only"
    else:
        mode = "disconnected"
    return {
        "supported": True,
        "mode": mode,
        "ssid": _get_field(conn, "802-11-wireless.ssid") if mode == "wifi-client" else None,
        "ap_ssid": _get_field(AP_CONN_NAME, "802-11-wireless.ssid") if mode == "ap" else None,
        "eth_connected": eth_ok,
    }


def reconcile(hysteresis_state: dict) -> dict:
    """Runs one reconciliation pass: picks the best available target for
    wlan0 (highest-priority saved network in range, else idle if Ethernet
    has a connection, else the AP) and switches to it if needed.

    `hysteresis_state` must be the same dict passed in on every call — it
    requires a new target to win two consecutive passes before switching
    AWAY from a currently active client Wi-Fi connection, so a momentary
    scan miss doesn't bounce the Pi off a working network.
    """
    if not _available():
        return {"supported": False}

    eth_ok = eth_connected()
    visible = set(scan_wifi(rescan=True))
    saved = list_saved_wifi()
    current = current_wlan_connection()

    candidate = next((entry["id"] for entry in saved if entry["ssid"] in visible), None)
    if candidate is not None:
        target = candidate
    elif eth_ok:
        target = None
    else:
        target = AP_CONN_NAME

    if target == current:
        hysteresis_state.clear()
        return {"supported": True, "action": "none", "target": target}

    protect_current = current is not None and current != AP_CONN_NAME
    if protect_current:
        if hysteresis_state.get("target") == target:
            hysteresis_state["count"] = hysteresis_state.get("count", 0) + 1
        else:
            hysteresis_state["target"] = target
            hysteresis_state["count"] = 1
        if hysteresis_state["count"] < 2:
            return {"supported": True, "action": "pending", "target": target}

    hysteresis_state.clear()
    if current is not None:
        deactivate_wlan()
    if target is not None:
        activate_connection(target)
    return {"supported": True, "action": "switched", "target": target}
