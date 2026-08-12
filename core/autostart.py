"""Windows per-user startup registration."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from core.identity import APP_DISPLAY_NAME

try:
    import winreg
except ImportError:  # pragma: no cover - TokenMeter is currently distributed for Windows.
    winreg = None  # type: ignore[assignment]


RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = APP_DISPLAY_NAME


class AutostartError(RuntimeError):
    """Raised when the requested Windows startup state cannot be applied."""


def autostart_command() -> str:
    """Return the command stored in the current user's Run registry key."""
    executable = Path(sys.executable).resolve(strict=False)
    parts = [str(executable)]
    if not getattr(sys, "frozen", False):
        parts.append(str(Path(__file__).resolve().parents[1] / "main.py"))
    return subprocess.list2cmdline(parts)


def _require_windows_registry():
    if sys.platform != "win32" or winreg is None:
        raise AutostartError("开机自启仅支持 Windows。")
    return winreg


def _read_run_value() -> str | None:
    registry = _require_windows_registry()
    try:
        with registry.OpenKey(
            registry.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            registry.KEY_QUERY_VALUE,
        ) as key:
            value, _value_type = registry.QueryValueEx(key, RUN_VALUE_NAME)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise AutostartError("无法读取 Windows 开机自启设置。") from exc
    return str(value)


def is_autostart_enabled() -> bool:
    """Return whether the Run entry points at this application build."""
    return _read_run_value() == autostart_command()


def set_autostart_enabled(enabled: bool) -> None:
    """Enable or disable startup for the current Windows user."""
    registry = _require_windows_registry()
    expected = autostart_command()
    current = _read_run_value()
    if enabled and current == expected:
        return
    if not enabled and current is None:
        return
    try:
        if enabled:
            with registry.CreateKeyEx(
                registry.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                registry.KEY_SET_VALUE,
            ) as key:
                registry.SetValueEx(key, RUN_VALUE_NAME, 0, registry.REG_SZ, expected)
            return
        with registry.OpenKey(
            registry.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            registry.KEY_SET_VALUE,
        ) as key:
            registry.DeleteValue(key, RUN_VALUE_NAME)
    except FileNotFoundError:
        if enabled:
            raise AutostartError("无法写入 Windows 开机自启设置。") from None
    except OSError as exc:
        raise AutostartError("无法更新 Windows 开机自启设置。") from exc


def sync_autostart(enabled: bool) -> None:
    """Reconcile the persisted preference with the current executable path."""
    if sys.platform != "win32" and not enabled:
        return
    set_autostart_enabled(enabled)


__all__ = [
    "AutostartError",
    "RUN_KEY_PATH",
    "RUN_VALUE_NAME",
    "autostart_command",
    "is_autostart_enabled",
    "set_autostart_enabled",
    "sync_autostart",
]
