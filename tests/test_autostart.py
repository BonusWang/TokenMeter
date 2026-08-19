import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

import core.autostart as autostart


def _registry_mock():
    return SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        KEY_QUERY_VALUE=1,
        KEY_SET_VALUE=2,
        OpenKey=Mock(),
        QueryValueEx=Mock(),
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


def test_enable_autostart_creates_shortcut_and_removes_legacy_run_entry(tmp_path):
    registry = _registry_mock()
    key = object()
    context = MagicMock()
    context.__enter__.return_value = key
    registry.OpenKey.return_value = context
    shortcut = tmp_path / autostart.STARTUP_SHORTCUT_NAME

    def write_shortcut(path):
        assert path == shortcut
        path.write_bytes(b"shortcut")

    with (
        patch.object(autostart.sys, "platform", "win32"),
        patch.object(autostart, "winreg", registry),
        patch.object(autostart, "_startup_shortcut_path", return_value=shortcut),
        patch.object(
            autostart,
            "_write_startup_shortcut",
            side_effect=write_shortcut,
        ) as write,
        patch.object(autostart, "_read_run_value", return_value="legacy command"),
    ):
        autostart.set_autostart_enabled(True)

    write.assert_called_once_with(shortcut)
    assert shortcut.is_file()
    registry.DeleteValue.assert_called_once_with(key, autostart.RUN_VALUE_NAME)


def test_disable_autostart_deletes_shortcut_and_existing_run_entry(tmp_path):
    registry = _registry_mock()
    key = object()
    context = MagicMock()
    context.__enter__.return_value = key
    registry.OpenKey.return_value = context
    shortcut = tmp_path / autostart.STARTUP_SHORTCUT_NAME
    shortcut.write_bytes(b"shortcut")
    with (
        patch.object(autostart.sys, "platform", "win32"),
        patch.object(autostart, "winreg", registry),
        patch.object(autostart, "_startup_shortcut_path", return_value=shortcut),
        patch.object(autostart, "_read_run_value", return_value="stale command"),
    ):
        autostart.set_autostart_enabled(False)

    assert not shortcut.exists()
    registry.DeleteValue.assert_called_once_with(key, autostart.RUN_VALUE_NAME)


def test_enable_autostart_rejects_a_shortcut_that_does_not_persist(tmp_path):
    registry = _registry_mock()
    shortcut = tmp_path / autostart.STARTUP_SHORTCUT_NAME
    with (
        patch.object(autostart.sys, "platform", "win32"),
        patch.object(autostart, "winreg", registry),
        patch.object(autostart, "_startup_shortcut_path", return_value=shortcut),
        patch.object(autostart, "_write_startup_shortcut"),
        pytest.raises(autostart.AutostartError, match="校验失败"),
    ):
        autostart.set_autostart_enabled(True)


def test_existing_shortcut_is_kept_without_rewriting(tmp_path):
    registry = _registry_mock()
    shortcut = tmp_path / autostart.STARTUP_SHORTCUT_NAME
    shortcut.write_bytes(b"shortcut")
    with (
        patch.object(autostart.sys, "platform", "win32"),
        patch.object(autostart, "winreg", registry),
        patch.object(autostart, "_startup_shortcut_path", return_value=shortcut),
        patch.object(autostart, "_write_startup_shortcut") as write,
        patch.object(autostart, "_read_run_value", return_value=None),
    ):
        autostart.set_autostart_enabled(True)

    write.assert_not_called()


def test_write_shortcut_uses_packaged_executable_and_hidden_powershell(tmp_path):
    executable = tmp_path / "Program Files" / "TokenMeter.exe"
    shortcut = tmp_path / autostart.STARTUP_SHORTCUT_NAME
    with (
        patch.object(autostart.sys, "executable", str(executable)),
        patch.object(autostart.sys, "frozen", True, create=True),
        patch.object(autostart.subprocess, "run") as run,
    ):
        autostart._write_startup_shortcut(shortcut)

    call = run.call_args
    assert call.args[0][-1] == autostart._CREATE_SHORTCUT_SCRIPT
    assert call.kwargs["env"]["TOKENMETER_AUTOSTART_SHORTCUT"] == str(shortcut)
    assert call.kwargs["env"]["TOKENMETER_AUTOSTART_TARGET"] == str(executable.resolve())
    assert call.kwargs["env"]["TOKENMETER_AUTOSTART_ARGUMENTS"] == ""
    assert call.kwargs["creationflags"] == getattr(
        autostart.subprocess, "CREATE_NO_WINDOW", 0
    )


def test_sync_disabled_is_noop_on_unsupported_platform():
    with (
        patch.object(autostart.sys, "platform", "linux"),
        patch.object(autostart, "set_autostart_enabled") as set_enabled,
    ):
        autostart.sync_autostart(False)

    set_enabled.assert_not_called()
