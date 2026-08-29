"""白名单多账号模式的悬浮聚合卡片：按 provider 分组展示 5 小时与每周剩余。

替代白名单模式下的液面悬浮球（qt_ball 保留给非白名单单账号路径）。卡片只做
展示与拖拽/点击透传，窗口几何、贴边隐藏和面板展开由 qt_widget 统一驱动。
"""

from __future__ import annotations

from api.aggregator import AGGREGATE_WINDOW_IDS, ProviderGroupSummary
from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.formatting import format_reset_countdown, format_weekly_reset_date
from ui.i18n import bind_text
from ui.qt_theme import current_theme, theme_controller

FLOAT_CARD_WIDTH = 210
CARD_RADIUS = 12
# 与面板 AccountCard 共用 20% 低水位阈值（qt_panel.ACCOUNTS_LOW_WATER_PERCENT）。
# 不直接 import qt_panel：面板模块级加载 pyqtgraph/NumPy，常驻悬浮卡片拖不起。
LOW_WATER_PERCENT = 20
# 卡片小标签用王总拍板的短口径（面板 AccountCard 用“5 小时剩余/每周剩余”全称）。
CARD_WINDOW_TITLES = {"five_hour": "5 小时", "weekly": "每周"}


def water_color(remaining_percent: float) -> QColor:
    """进度 = 剩余%；≤20% 警示红，其余主题绿（与面板 AccountProgressBar 同规则）。"""

    tokens = current_theme()
    low = remaining_percent <= LOW_WATER_PERCENT
    return QColor(tokens.danger if low else tokens.success)


class _CardBar(QWidget):
    """迷你圆角进度条：面板 AccountProgressBar 的轻量版（避免依赖面板模块）。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self._ratio = 0.0
        self._fill_color = water_color(100.0)

    @property
    def ratio(self) -> float:
        return self._ratio

    @property
    def fill_color(self) -> QColor:
        return QColor(self._fill_color)

    def set_state(self, remaining_percent: float) -> None:
        self._ratio = max(0.0, min(1.0, float(remaining_percent) / 100))
        self._fill_color = water_color(remaining_percent)
        self.update()

    def refresh_theme(self) -> None:
        self._fill_color = water_color(self._ratio * 100)
        self.update()

    def paintEvent(self, _event) -> None:
        tokens = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        radius = self.height() / 2
        painter.setBrush(QColor(tokens.elevated))
        painter.drawRoundedRect(self.rect(), radius, radius)
        if self._ratio > 0:
            width = max(self.height(), int(self.width() * self._ratio))
            painter.setBrush(self._fill_color)
            painter.drawRoundedRect(0, 0, width, self.height(), radius, radius)
        painter.end()


class _WindowRow(QWidget):
    """“5 小时/每周”单行：小标签 + 剩余大数字 + 迷你进度条。"""

    def __init__(self, window_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._window_id = window_id
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.setSpacing(4)
        self._title_label = bind_text(QLabel(), CARD_WINDOW_TITLES.get(window_id, window_id))
        self._title_label.setObjectName("floatCardRowTitle")
        self._percent_label = QLabel()
        self._percent_label.setObjectName("floatCardPercent")
        self._percent_label.setFont(QFont("Microsoft YaHei UI", 13, QFont.Weight.Bold))
        header.addWidget(self._title_label)
        header.addStretch(1)
        header.addWidget(self._percent_label)
        layout.addLayout(header)
        self._bar = _CardBar()
        layout.addWidget(self._bar)

    def set_remaining(self, remaining_percent: float) -> None:
        self._percent_label.setText(f"{remaining_percent:.0f}%")
        color = water_color(remaining_percent).name()
        self._percent_label.setStyleSheet(f"color: {color};")
        self._bar.set_state(remaining_percent)

    def refresh_theme(self) -> None:
        self._bar.refresh_theme()
        self.set_remaining(self._bar.ratio * 100)


class _GroupSection(QWidget):
    """单 provider 分组：组头（名称 + N 账号徽章）+ 每窗口一行。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)
        self._name_label = QLabel()
        self._name_label.setObjectName("floatCardGroupName")
        self._name_label.setFont(QFont("Microsoft YaHei UI", 9, QFont.Weight.DemiBold))
        self._badge = QLabel()
        self._badge.setObjectName("floatCardBadge")
        header.addWidget(self._name_label)
        header.addStretch(1)
        header.addWidget(self._badge)
        layout.addLayout(header)

        # 两类聚合窗口各预留一行，缺失窗口整行隐藏，刷新时不重建控件。
        self._rows: dict[str, _WindowRow] = {}
        for window_id in AGGREGATE_WINDOW_IDS:
            row = _WindowRow(window_id)
            self._rows[window_id] = row
            layout.addWidget(row)

    def set_group(self, summary: ProviderGroupSummary) -> None:
        self._name_label.setText(summary.provider_name)
        self._badge.setText(f"{summary.account_count} 账号")
        for window_id, row in self._rows.items():
            window = summary.windows.get(window_id)
            row.setVisible(window is not None)
            if window is not None:
                row.set_remaining(window.remaining_percent)

    def refresh_theme(self) -> None:
        for row in self._rows.values():
            row.refresh_theme()


def build_tooltip(groups: list[ProviderGroupSummary]) -> str:
    """tooltip 分组列出各账号 5 小时已用% 与各窗口最早重置时间。"""

    lines: list[str] = []
    for group in groups:
        lines.append(group.provider_name)
        usages = []
        for account in group.accounts:
            if account.error:
                continue
            five_hour = next(
                (w for w in account.windows if w.id == "five_hour"), None
            )
            if five_hour is not None:
                label = account.label or account.provider_name
                usages.append(f"{label} {five_hour.used_percent:.0f}%")
        if usages:
            lines.append(" · ".join(usages))
        resets = []
        for window_id in AGGREGATE_WINDOW_IDS:
            window = group.windows.get(window_id)
            if window is None or window.earliest_reset is None:
                continue
            title = CARD_WINDOW_TITLES.get(window_id, window.title)
            if window_id == "weekly":
                resets.append(f"{title} {format_weekly_reset_date(window.earliest_reset)}")
            else:
                resets.append(f"{title} {format_reset_countdown(window.earliest_reset)}")
        if resets:
            lines.append(" · ".join(resets))
    return "\n".join(lines)


class FloatingUsageCard(QWidget):
    """分组聚合悬浮卡片；拖拽/点击信号交给 qt_widget 复用球的窗口基础设施。"""

    pressed = Signal(QPoint)
    dragged = Signal(QPoint)
    released = Signal(QPoint)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedWidth(FLOAT_CARD_WIDTH)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._sections: list[_GroupSection] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 12, 10)
        self._layout.setSpacing(10)
        self._placeholder_label = QLabel()
        self._placeholder_label.setObjectName("floatCardPlaceholder")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder_label.setStyleSheet(
            f"color: {current_theme().subtext}; font-size: 12px;"
        )
        self._layout.addWidget(self._placeholder_label)
        self.set_placeholder("正在更新额度")
        theme_controller().changed.connect(self._on_theme_changed)

    # ------------------------------------------------------------- data API
    def set_state(
        self, groups: list[ProviderGroupSummary], *, loading: bool = False
    ) -> None:
        """渲染分组；空分组或全部账号失败（无任何窗口数据）回退占位态。"""

        if not groups or not any(group.windows for group in groups):
            self.set_placeholder("正在更新额度" if loading else "暂无可用账号")
            return
        self._placeholder_label.setVisible(False)
        if len(self._sections) != len(groups):
            self._clear_sections()
            for _index, group in enumerate(groups):
                section = _GroupSection(self)
                self._sections.append(section)
                self._layout.addWidget(section)
                # Qt 陷阱（同 qt_panel._set_widget_visible）：父级已可见时新建
                # 子控件会残留 WA_WState_Hidden，仅靠布局激活不会显示，必须显式补写。
                section.setVisible(True)
        for section, group in zip(self._sections, groups, strict=True):
            section.set_group(group)
        self._sync_height()
        bind_text(self, build_tooltip(groups), method="setToolTip")

    def set_placeholder(self, text: str) -> None:
        """加载态/全 error 态：整卡显示占位文案。"""

        self._clear_sections()
        self._placeholder_label.setVisible(True)
        bind_text(self._placeholder_label, text)
        bind_text(self, text, method="setToolTip")
        self._sync_height()

    def _clear_sections(self) -> None:
        for section in self._sections:
            self._layout.removeWidget(section)
            section.deleteLater()
        self._sections.clear()

    def _sync_height(self) -> None:
        # 高度随分组/窗口行数自适应；隐藏行不计入 sizeHint。
        # shown 状态下 addWidget 只做失效标记，必须先 activate 强制重算，
        # 否则读到脏缓存会把卡片压回最小高度。
        self._layout.activate()
        self.setFixedHeight(max(54, self._layout.sizeHint().height()))

    def _on_theme_changed(self, _mode: str, _resolved: str) -> None:
        self._placeholder_label.setStyleSheet(
            f"color: {current_theme().subtext}; font-size: 12px;"
        )
        for section in self._sections:
            section.refresh_theme()
        self.update()

    # --------------------------------------------------------------- events
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.dragged.emit(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.released.emit(event.globalPosition().toPoint())
            event.accept()

    def paintEvent(self, _event) -> None:
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
            CARD_RADIUS,
            CARD_RADIUS,
        )
        fill = QColor(theme.window)
        fill.setAlpha(235)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawPath(path)
        border = QColor(theme.border_hover)
        border.setAlpha(190)
        painter.setPen(QPen(border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()
