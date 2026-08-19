from unittest.mock import Mock, patch

import main
from core.autostart import AutostartError


def test_second_instance_exits_before_runtime_initialization():
    with (
        patch.object(main, "_acquire_single_instance", return_value=None),
        patch.object(main.config_manager, "initialize") as initialize,
        patch.object(main.ctypes, "windll", create=True),
    ):
        assert main.main() == 0

    initialize.assert_not_called()


def test_startup_reconciles_autostart_preference_before_launching_app():
    instance_handle = object()
    with (
        patch.object(main, "_acquire_single_instance", return_value=instance_handle),
        patch.object(main, "_release_single_instance") as release,
        patch.object(main.config_manager, "initialize") as initialize,
        patch.object(main.config_manager, "get", return_value=True),
        patch.object(main, "sync_autostart") as sync_autostart,
        patch("updater.client.cleanup_pending_update") as cleanup_pending_update,
        patch.object(main, "App") as app,
    ):
        app.return_value.run.return_value = 0

        assert main.main() == 0

    initialize.assert_called_once_with()
    sync_autostart.assert_called_once_with(True)
    cleanup_pending_update.assert_called_once_with()
    app.return_value.run.assert_called_once_with()
    release.assert_called_once_with(instance_handle)


def test_startup_logs_autostart_failure_details_and_continues():
    instance_handle = object()
    error = AutostartError("Windows 开机自启设置更新后校验失败。")
    logger = Mock()
    with (
        patch.object(main, "_acquire_single_instance", return_value=instance_handle),
        patch.object(main, "_release_single_instance"),
        patch.object(main.config_manager, "initialize"),
        patch.object(main.config_manager, "get", return_value=True),
        patch.object(main.config_manager, "logger", return_value=logger),
        patch.object(main, "sync_autostart", side_effect=error),
        patch.object(main, "autostart_command", return_value='"D:\\TokenMeter.exe"'),
        patch("updater.client.cleanup_pending_update"),
        patch.object(main, "App") as app,
    ):
        app.return_value.run.return_value = 0

        assert main.main() == 0

    logger.warning.assert_called_once_with(
        "Windows autostart state could not be synchronized: %s; command=%r",
        error,
        '"D:\\TokenMeter.exe"',
        exc_info=True,
    )
