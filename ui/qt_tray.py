"""Qt system tray integration."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from core.identity import APP_DISPLAY_NAME
from ui.i18n import bind_text
from ui.qt_theme import app_icon, theme_controller


class SystemTray(QSystemTrayIcon):
    def __init__(self, app):
        super().__init__(app_icon(64), app.widget)
        self.app = app
        bind_text(self, f"{APP_DISPLAY_NAME} - LLM 用量监控", method='setToolTip')

        menu = QMenu()
        visible = bind_text(QAction(menu), "显示/隐藏")
        visible.triggered.connect(app.widget.set_visible_from_tray)
        refresh = bind_text(QAction(menu), "刷新")
        refresh.triggered.connect(app.widget.refresh)
        settings = bind_text(QAction(menu), "设置")
        settings.triggered.connect(app.widget.open_settings)
        quit_action = bind_text(QAction(menu), "退出")
        quit_action.triggered.connect(self.quit_app)
        menu.addActions((visible, refresh, settings))
        menu.addSeparator()
        menu.addAction(quit_action)
        self._menu = menu
        self.setContextMenu(menu)
        theme_controller().changed.connect(self._refresh_menu_theme)
        self.activated.connect(self._activated)
        self.messageClicked.connect(app.widget.handle_auth_expired_notification_click)

    def _refresh_menu_theme(self, _mode: str, _resolved: str) -> None:
        application = QApplication.instance()
        if application is not None:
            self._menu.setPalette(application.palette())
        self._menu.style().unpolish(self._menu)
        self._menu.style().polish(self._menu)
        self._menu.update()

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.app.widget.set_visible_from_tray()

    def quit_app(self) -> None:
        self.hide()
        self.app.widget.close()

    def run(self) -> None:
        self.show()

    def stop(self) -> None:
        self.hide()
