from unittest.mock import Mock, patch

import main
from core.autostart import AutostartError


def test_smoke_mode_bypasses_accounts_single_instance_and_autostart():
    with (
        patch.object(main.sys, "argv", ["TokenMeter.exe", "--smoke-test"]),
        patch.object(main, "_smoke_test", return_value=0) as smoke,
        patch.object(main, "_acquire_single_instance") as acquire,
        patch.object(main.config_manager, "initialize") as initialize,
        patch.object(main, "sync_autostart") as autostart,
    ):
        assert main.main() == 0
    smoke.assert_called_once_with()
    acquire.assert_not_called()
    initialize.assert_not_called()
    autostart.assert_not_called()


def test_app_passes_accent_sync_preference_to_theme_controller():
    for enabled in (True, False):
        values = main.config_manager.validate_config({"UI_SYNC_ACCENT_COLOR": enabled})
        with (
            patch.object(main.config_manager, "get", side_effect=values.get),
            patch("ui.qt_theme.configure_theme") as configure,
            patch("ui.qt_widget.FloatingWidget"),
            patch("ui.qt_tray.SystemTray"),
        ):
            main.App()
        assert configure.call_args.kwargs["sync_accent"] is enabled
        assert configure.call_args.kwargs["light_accent"] == values["UI_LIGHT_ACCENT_COLOR"]
        assert configure.call_args.kwargs["dark_accent"] == values["UI_DARK_ACCENT_COLOR"]


def test_smoke_mode_preserves_failure_exit_code():
    with (
        patch.object(main.sys, "argv", ["TokenMeter.exe", "--smoke-test"]),
        patch.object(main, "_smoke_test", return_value=1),
    ):
        assert main.main() == 1


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
