"""Windows per-user startup registration."""

from __future__ import annotations

import os
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
STARTUP_SHORTCUT_NAME = f"{APP_DISPLAY_NAME}.lnk"
_CREATE_SHORTCUT_SCRIPT = (
    "$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut("
    "$env:TOKENMETER_AUTOSTART_SHORTCUT); "
    "$shortcut.TargetPath = $env:TOKENMETER_AUTOSTART_TARGET; "
    "$shortcut.Arguments = $env:TOKENMETER_AUTOSTART_ARGUMENTS; "
    "$shortcut.WorkingDirectory = $env:TOKENMETER_AUTOSTART_WORKDIR; "
    "$shortcut.IconLocation = $env:TOKENMETER_AUTOSTART_TARGET; "
    "$shortcut.Save()"
)


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


def _startup_shortcut_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise AutostartError("无法定位当前 Windows 用户的启动文件夹。")
    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / STARTUP_SHORTCUT_NAME
    )


def _write_startup_shortcut(path: Path) -> None:
    executable = Path(sys.executable).resolve(strict=False)
    arguments = ""
    working_dir = executable.parent
    if not getattr(sys, "frozen", False):
        main_script = Path(__file__).resolve().parents[1] / "main.py"
        arguments = subprocess.list2cmdline([str(main_script)])
        working_dir = main_script.parent
    environment = os.environ.copy()
    environment.update(
        {
            "TOKENMETER_AUTOSTART_SHORTCUT": str(path),
            "TOKENMETER_AUTOSTART_TARGET": str(executable),
            "TOKENMETER_AUTOSTART_ARGUMENTS": arguments,
            "TOKENMETER_AUTOSTART_WORKDIR": str(working_dir),
        }
    )
    system_root = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
    powershell = (
        system_root
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _CREATE_SHORTCUT_SCRIPT,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AutostartError("无法创建 Windows 开机自启快捷方式。") from exc


def _delete_legacy_run_value() -> None:
    registry = _require_windows_registry()
    if _read_run_value() is None:
        return
    try:
        with registry.OpenKey(
            registry.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            registry.KEY_SET_VALUE,
        ) as key:
            registry.DeleteValue(key, RUN_VALUE_NAME)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise AutostartError("无法清理旧版 Windows 开机自启设置。") from exc


def is_autostart_enabled() -> bool:
    """Return whether a current or legacy per-user startup entry exists."""
    _require_windows_registry()
    return _startup_shortcut_path().is_file() or _read_run_value() == autostart_command()


def set_autostart_enabled(enabled: bool) -> None:
    """Enable or disable startup for the current Windows user."""
    _require_windows_registry()
    shortcut_path = _startup_shortcut_path()
    try:
        if enabled:
            if not shortcut_path.is_file():
                # OEM 启动管理可能移走 Run 值；用户启动文件夹不受该兼容层影响。
                _write_startup_shortcut(shortcut_path)
            if not shortcut_path.is_file():
                raise AutostartError("Windows 开机自启快捷方式创建后校验失败。")
        else:
            shortcut_path.unlink(missing_ok=True)
            if shortcut_path.exists():
                raise AutostartError("Windows 开机自启快捷方式删除后校验失败。")
    except OSError as exc:
        raise AutostartError("无法更新 Windows 开机自启设置。") from exc
    # 清理旧 Run 值可以避免升级后启动两份进程；OEM 的禁用备份不参与登录启动。
    _delete_legacy_run_value()


def sync_autostart(enabled: bool) -> None:
    """Reconcile the persisted preference with the current executable path."""
    if sys.platform != "win32" and not enabled:
        return
    set_autostart_enabled(enabled)


__all__ = [
    "AutostartError",
    "RUN_KEY_PATH",
    "RUN_VALUE_NAME",
    "STARTUP_SHORTCUT_NAME",
    "autostart_command",
    "is_autostart_enabled",
    "set_autostart_enabled",
    "sync_autostart",
]
