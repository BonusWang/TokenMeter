import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import core.autostart as autostart


def _registry_mock():
    return SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        KEY_QUERY_VALUE=1,
        KEY_SET_VALUE=2,
        REG_SZ=3,
        OpenKey=Mock(),
        CreateKeyEx=Mock(),
        QueryValueEx=Mock(),
        SetValueEx=Mock(),
        DeleteValue=Mock(),
    )


def test_packaged_autostart_command_quotes_executable_path(tmp_path):
    executable = tmp_path / "Program Files" / "TokenMeter.exe"
    with (
        patch.object(autostart.sys, "executable", str(executable)),
        patch.object(autostart.sys, "frozen", True, create=True),
    ):
        assert autostart.autostart_command() == subprocess.list2cmdline(
            [str(executable.resolve())]
        )


def test_enable_autostart_writes_current_user_run_entry():
    registry = _registry_mock()
    key = object()
    context = MagicMock()
    context.__enter__.return_value = key
    registry.CreateKeyEx.return_value = context
    with (
        patch.object(autostart.sys, "platform", "win32"),
        patch.object(autostart, "winreg", registry),
        patch.object(autostart, "_read_run_value", return_value=None),
        patch.object(autostart, "autostart_command", return_value='"C:\\TokenMeter.exe"'),
    ):
        autostart.set_autostart_enabled(True)

    registry.CreateKeyEx.assert_called_once_with(
        registry.HKEY_CURRENT_USER,
        autostart.RUN_KEY_PATH,
        0,
        registry.KEY_SET_VALUE,
    )
    registry.SetValueEx.assert_called_once_with(
        key,
        autostart.RUN_VALUE_NAME,
        0,
        registry.REG_SZ,
        '"C:\\TokenMeter.exe"',
    )


def test_disable_autostart_deletes_existing_run_entry():
    registry = _registry_mock()
    key = object()
    context = MagicMock()
    context.__enter__.return_value = key
    registry.OpenKey.return_value = context
    with (
        patch.object(autostart.sys, "platform", "win32"),
        patch.object(autostart, "winreg", registry),
        patch.object(autostart, "_read_run_value", return_value="stale command"),
    ):
        autostart.set_autostart_enabled(False)

    registry.DeleteValue.assert_called_once_with(key, autostart.RUN_VALUE_NAME)


def test_sync_disabled_is_noop_on_unsupported_platform():
    with (
        patch.object(autostart.sys, "platform", "linux"),
        patch.object(autostart, "set_autostart_enabled") as set_enabled,
    ):
        autostart.sync_autostart(False)

    set_enabled.assert_not_called()
