"""Maimai sprite view for the existing compact desktop window."""

from __future__ import annotations

import json
import math
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QWidget

from ui.i18n import bind_text, tr
from ui.qt_theme import current_theme, theme_controller

PET_DIRECTORY = Path(__file__).resolve().parents[1] / "assets" / "pets" / "maimai"
CELL_WIDTH, CELL_HEIGHT = 192, 208
# 只播放图集中的有效单元；待机略过明显抬身的帧，长停留后眨眼，避免静止时跳变。
ANIMATIONS = {
    "idle": (0, (3000, 140, 120, 140)),
    "waving": (3, (140, 140, 140, 280)),
    "jumping": (4, (140, 140, 140, 140, 280)),
    "failed": (5, (140,) * 7 + (240,)),
    "waiting": (6, (150,) * 5 + (260,)),
    "running": (7, (120,) * 5 + (220,)),
}


class FloatingPet(QWidget):
    pressed = Signal(QPoint)
    dragged = Signal(QPoint)
    released = Signal(QPoint)
    resize_requested = Signal(int)
    shape_changed = Signal()

    def __init__(self, size: int = 88, parent: QWidget | None = None):
        # 先校验资源再创建 Qt 子窗口；构造失败不能留下会接收绘制事件的半初始化控件。
        manifest = json.loads((PET_DIRECTORY / "pet.json").read_text(encoding="utf-8-sig"))
        atlas = QPixmap(str(PET_DIRECTORY / "spritesheet.webp"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("spriteVersionNumber") != 2
            or atlas.isNull()
            or (atlas.width(), atlas.height()) != (1536, 2288)
            or not atlas.hasAlphaChannel()
        ):
            raise ValueError("Invalid maimai v2 spritesheet")
        super().__init__(parent)
        self._frames = {
            state: [
                atlas.copy(column * CELL_WIDTH, row * CELL_HEIGHT, CELL_WIDTH, CELL_HEIGHT)
                for column in ((0, 1, 2, 1) if state == "idle" else range(len(durations)))
            ]
            for state, (row, durations) in ANIMATIONS.items()
        }
        self._frame_cache: dict[tuple, tuple[QPixmap, QPoint]] = {}
        self._mask: QRegion | None = None
        self._state = "idle"
        self._base_state = "idle"
        self._frame_index = 0
        self._hovered = False
        self._greeting_done = False
        self._pressed = False
        self._wheel_remainder = 0
        self._detail = ""
        self._status_text = ""
        self._summary = "--"
        self._remaining_percent: float | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance_frame)
        self.setFixedSize(size, size)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        bind_text(self, "麦麦桌宠", method="setAccessibleName")
        bind_text(self, self._tooltip_text, method="setToolTip")
        bind_text(self, self._tooltip_text, method="setAccessibleDescription")
        theme_controller().changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str, _resolved: str) -> None:
        self.update()

    def set_usage(
        self,
        detail: str,
        *,
        refreshing: bool,
        unavailable: bool,
        low: bool,
        summary: str = "--",
        remaining_percent: float | None = None,
    ) -> None:
        self._detail = detail
        self._summary = summary
        self._remaining_percent = remaining_percent
        # 这里表达的是用量采集状态，不把刷新动画冒充 Codex 任务的运行状态。
        if refreshing:
            self._base_state, self._status_text = "running", "正在刷新用量"
        elif unavailable:
            self._base_state, self._status_text = "failed", "用量暂不可用"
        elif low:
            self._base_state, self._status_text = "waiting", "剩余额度不足"
        else:
            self._base_state, self._status_text = "idle", ""
        bind_text(self, self._tooltip_text, method="setToolTip")
        bind_text(self, self._tooltip_text, method="setAccessibleDescription")
        self._sync_state()
        self.update()

    def _tooltip_text(self) -> str:
        return "\n".join(
            filter(
                None,
                (
                    tr("麦麦桌宠"),
                    tr(self._status_text),
                    tr(self._detail),
                    tr("单击打开面板；拖动移动；滚轮调整大小。"),
                ),
            )
        )

    def _sync_state(self) -> None:
        state = (
            "jumping"
            if self._pressed
            else ("waving" if self._hovered and not self._greeting_done else self._base_state)
        )
        if state != self._state:
            self._state = state
            self._frame_index = 0
            self._timer.stop()
            self.update()
        if self.isVisible() and not self._timer.isActive():
            self._timer.start(ANIMATIONS[self._state][1][self._frame_index])

    def _advance_frame(self) -> None:
        if not self.isVisible():
            return
        durations = ANIMATIONS[self._state][1]
        if self._state == "waving" and self._frame_index == len(durations) - 1:
            # 悬停只招手一次；鼠标不动时回到待机，避免持续大幅动作干扰阅读。
            self._greeting_done = True
            self._sync_state()
            return
        self._frame_index = (self._frame_index + 1) % len(durations)
        self.update()
        self._timer.start(durations[self._frame_index])

    def _current_frame(self) -> tuple[QPixmap, QPoint]:
        key = (
            self.width(),
            self.height(),
            self.devicePixelRatioF(),
            self._state,
            self._frame_index,
        )
        if key not in self._frame_cache:
            source = self._frames[self._state][self._frame_index]
            # 所有动作共用原始单元尺寸与底部锚点，不能逐帧裁紧，否则会忽大忽小。
            bounds = self._sprite_bounds()
            logical = source.scaled(
                bounds.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            offset = QPoint(
                (self.width() - logical.width()) // 2, bounds.bottom() + 1 - logical.height()
            )
            dpr = self.devicePixelRatioF()
            pixmap = source.scaled(
                round(logical.width() * dpr),
                round(logical.height() * dpr),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            pixmap.setDevicePixelRatio(dpr)
            self._frame_cache[key] = pixmap, offset
        return self._frame_cache[key]

    def _badge_rect(self) -> QRectF:
        height = max(22, round(self.height() * 0.20))
        return QRectF(2, self.height() - height - 2, self.width() - 4, height)

    def _sprite_bounds(self):
        # 为常驻读数预留底部空间，宠物所有动作都不能盖住或推动额度气泡。
        return self.rect().adjusted(2, 2, -2, -round(self._badge_rect().height()) - 4)

    def frame_mask(self) -> QRegion:
        if self._mask is None:
            # Windows 透明窗口逐帧 setMask 会反复重建原生轮廓并触发 enter/leave，
            # 造成闪动。使用所有动作的轮廓并集，只在缩放或模式切换时应用一次。
            region = QRegion()
            bounds = self._sprite_bounds()
            for frames in self._frames.values():
                for source in frames:
                    logical = source.scaled(
                        bounds.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    offset = QPoint(
                        (self.width() - logical.width()) // 2,
                        bounds.bottom() + 1 - logical.height(),
                    )
                    region = region.united(QRegion(logical.mask()).translated(offset))
            # 一像素余量保留半透明毛发的抗锯齿边缘。
            mask = region
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                mask = mask.united(region.translated(dx, dy))
            badge = QPainterPath()
            badge.addRoundedRect(self._badge_rect(), 10, 10)
            mask = mask.united(QRegion(badge.toFillPolygon().toPolygon()))
            self._mask = mask.intersected(QRegion(self.rect()))
        return self._mask

    def paintEvent(self, _event) -> None:
        pixmap, offset = self._current_frame()
        painter = QPainter(self)
        painter.drawPixmap(offset, pixmap)
        self._paint_badge(painter)

    def _paint_badge(self, painter: QPainter) -> None:
        theme = current_theme()
        badge = self._badge_rect()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(theme.border), 1))
        painter.setBrush(QColor(theme.surface))
        painter.drawRoundedRect(badge.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        text_rect = badge.adjusted(6, 0, -6, 0)
        if self._remaining_percent is not None:
            # 小水位图只用于百分比额度；余额不画进度，避免把金额误当成额度比例。
            sphere = QRectF(badge.left() + 6, badge.center().y() - 6, 12, 12)
            clip = QPainterPath()
            clip.addEllipse(sphere)
            painter.save()
            painter.setClipPath(clip)
            painter.fillRect(sphere, QColor(theme.accent_soft))
            water = QRectF(sphere)
            water.setTop(water.bottom() - water.height() * self._remaining_percent / 100)
            painter.fillRect(
                water, QColor(theme.warning if self._remaining_percent <= 10 else theme.accent)
            )
            painter.restore()
            text_rect.setLeft(sphere.right() + 4)
        font = QFont(self.font())
        font.setPixelSize(max(11, round(self.height() * 0.115)))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(theme.value))
        # 大额余额不能溢出气泡；完整精度仍在悬停详情和原面板中可见。
        label = painter.fontMetrics().elidedText(
            self._summary, Qt.TextElideMode.ElideRight, int(text_rect.width())
        )
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)

    def resizeEvent(self, event) -> None:
        self._frame_cache.clear()
        self._mask = None
        super().resizeEvent(event)
        self.shape_changed.emit()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_state()

    def hideEvent(self, event) -> None:
        # 面板展开、托盘隐藏或切回球体后都必须停止计时，且不恢复残留拖动状态。
        self._timer.stop()
        self._pressed = self._hovered = False
        self._greeting_done = False
        self._state, self._frame_index = self._base_state, 0
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().hideEvent(event)

    def enterEvent(self, event) -> None:
        if not self._hovered:
            self._greeting_done = False
        self._hovered = True
        self._sync_state()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._greeting_done = False
        self._sync_state()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._sync_state()
            self.pressed.emit(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pressed and event.buttons() & Qt.MouseButton.LeftButton:
            self.dragged.emit(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self._sync_state()
            self.released.emit(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if not delta:
            event.ignore()
            return
        self._wheel_remainder += delta
        steps = math.trunc(self._wheel_remainder / 120)
        if steps:
            self._wheel_remainder -= steps * 120
            self.resize_requested.emit(steps)
        event.accept()
