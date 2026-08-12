from unittest.mock import patch

import main


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
