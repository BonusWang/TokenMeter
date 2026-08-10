"""Custom-painted floating usage ball."""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from ui.qt_theme import current_theme, theme_controller


DESIGN_SIZE = 120


class FloatingUsageBall(QWidget):
    pressed = Signal(QPoint)
    dragged = Signal(QPoint)
    released = Signal(QPoint)

    def __init__(self, size: int = 88, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._today = "--"
        self._balance = "--"
        self._primary_label = "今日使用"
        self._secondary_label = "余额"
        self._quota_mode = False
        self._quota_remaining: float | None = None
        self._quota_reset_text = ""
        self._quota_title = "周额度"
        self._wave_phase = 0.0
        self._wave_timer = QTimer(self)
        self._wave_timer.setInterval(60)
        self._wave_timer.timeout.connect(self._advance_wave)
        self._peak_highlight = False
        self._hovered = False
        self._active = False
        theme_controller().changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str, _resolved: str) -> None:
        self.update()

    def set_values(self, today: str, balance: str) -> None:
        if self._today == today and self._balance == balance:
            return
        self._today = today
        self._balance = balance
        self.update()

    def set_labels(self, primary: str, secondary: str) -> None:
        primary = str(primary)[:8]
        secondary = str(secondary)[:8]
        if (self._primary_label, self._secondary_label) == (primary, secondary):
            return
        self._primary_label = primary
        self._secondary_label = secondary
        self.update()

    @staticmethod
    def _compact_reset_text(value: str) -> str:
        return (
            str(value)
            .replace(" 天 ", "天 ")
            .replace(" 小时", "小时")
            .replace(" 分钟", "分钟")[:10]
        )

    def set_quota_state(
        self,
        remaining_percent: float | None,
        reset_text: str,
        title: str = "周额度",
    ) -> None:
        remaining = (
            None
            if remaining_percent is None
            else max(0.0, min(100.0, float(remaining_percent)))
        )
        compact_reset = self._compact_reset_text(reset_text)
        compact_title = str(title).replace("每周额度", "周额度")[:8] or "周额度"
        state = (remaining, compact_reset, compact_title)
        if self._quota_mode and state == (
            self._quota_remaining,
            self._quota_reset_text,
            self._quota_title,
        ):
            return
        self._quota_mode = True
        self._quota_remaining, self._quota_reset_text, self._quota_title = state
        remaining_text = "未知" if remaining is None else f"{remaining:.0f}%"
        self.setAccessibleName("Codex 剩余额度")
        self.setAccessibleDescription(remaining_text)
        self.setToolTip(remaining_text)
        if self.isVisible() and not self._wave_timer.isActive():
            self._wave_timer.start()
        self.update()

    def clear_quota_state(self) -> None:
        if not self._quota_mode:
            return
        self._quota_mode = False
        self._quota_remaining = None
        self._quota_reset_text = ""
        self._wave_timer.stop()
        self.setAccessibleName("")
        self.setAccessibleDescription("")
        self.setToolTip("")
        self.update()

    def _advance_wave(self) -> None:
        self._wave_phase = (self._wave_phase + 0.16) % math.tau
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._quota_mode:
            self._wave_timer.start()

    def hideEvent(self, event) -> None:
        self._wave_timer.stop()
        super().hideEvent(event)

    def set_peak_highlight(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._peak_highlight == enabled:
            return
        self._peak_highlight = enabled
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._active = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()
            self.pressed.emit(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.dragged.emit(event.globalPosition().toPoint())
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._active = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.update()
            self.released.emit(event.globalPosition().toPoint())
            event.accept()

    @staticmethod
    def _wave_path(
        rect: QRectF,
        surface_y: float,
        amplitude: float,
        reverse: bool,
        phase: float,
    ) -> QPainterPath:
        direction = -1 if reverse else 1
        first_y = surface_y + math.sin(phase * direction) * amplitude
        path = QPainterPath(QPointF(rect.left(), first_y))
        # 多点正弦曲线可平滑平移波峰；前后层反向运动，避免看起来像整块横移。
        for step in range(1, 33):
            progress = step / 32
            angle = progress * math.tau + phase * direction
            path.lineTo(
                rect.left() + rect.width() * progress,
                surface_y + math.sin(angle) * amplitude,
            )
        path.lineTo(rect.right(), rect.bottom() + 1)
        path.lineTo(rect.left(), rect.bottom() + 1)
        path.closeSubpath()
        return path

    def _paint_quota(self, painter: QPainter, theme, ball_radius: float) -> None:
        inner_margin = DESIGN_SIZE / 2 - ball_radius + 4
        inner = QRectF(
            inner_margin,
            inner_margin,
            DESIGN_SIZE - inner_margin * 2,
            DESIGN_SIZE - inner_margin * 2,
        )
        clip = QPainterPath()
        clip.addEllipse(inner)
        painter.save()
        painter.setClipPath(clip)
        if self._quota_remaining is not None and self._quota_remaining > 0:
            ratio = self._quota_remaining / 100
            surface_y = inner.bottom() - inner.height() * ratio
            amplitude = min(7.0, inner.height() * min(ratio, 1 - ratio) * 0.25)

            back_color = QColor(theme.heat[3] if theme.name == "light" else theme.accent_hover)
            back_color.setAlpha(205)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(back_color)
            painter.drawPath(
                self._wave_path(
                    inner,
                    surface_y - 2,
                    amplitude,
                    False,
                    self._wave_phase,
                )
            )

            water = QLinearGradient(0, surface_y, 0, inner.bottom())
            water_top = QColor(theme.heat[3] if theme.name == "light" else theme.accent_hover)
            water.setColorAt(0.0, water_top)
            water.setColorAt(0.2, QColor(theme.accent))
            deep = QColor(theme.accent).darker(118)
            deep.setAlpha(232)
            water.setColorAt(1.0, deep)
            painter.setBrush(water)
            painter.drawPath(
                self._wave_path(
                    inner,
                    surface_y + 1,
                    amplitude,
                    True,
                    self._wave_phase,
                )
            )
        painter.restore()

        percentage = (
            "--"
            if self._quota_remaining is None
            else f"{self._quota_remaining:.0f}%"
        )
        value_over_water = self._quota_remaining is not None and self._quota_remaining >= 50
        value_size = 25 if len(percentage) <= 4 else 21
        painter.setFont(QFont("Microsoft YaHei UI", value_size, QFont.Weight.Bold))
        value_shadow = QColor(
            "#000000" if value_over_water or theme.name == "dark" else "#FFFFFF"
        )
        value_shadow.setAlpha(150)
        painter.setPen(value_shadow)
        painter.drawText(
            QRectF(8, 42, 104, 37).translated(0, 1),
            Qt.AlignmentFlag.AlignCenter,
            percentage,
        )
        painter.setPen(QColor("#FFFFFF") if value_over_water else QColor(theme.value))
        painter.drawText(QRectF(8, 42, 104, 37), Qt.AlignmentFlag.AlignCenter, percentage)

    def paintEvent(self, _event) -> None:
        theme = current_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        side = min(self.width(), self.height())
        painter.scale(side / DESIGN_SIZE, side / DESIGN_SIZE)
        side = DESIGN_SIZE
        center = QPointF(side / 2, side / 2)

        # The light warning token is tuned for text contrast and looks brown as
        # emitted light; use saturated amber for the peak glow instead.
        peak_color = QColor("#FFB000" if theme.name == "light" else theme.warning)
        ball_radius = side / 2 - (8 if self._peak_highlight else 3)
        if self._peak_highlight:
            # Keep the outermost pixels transparent so antialiasing is completed
            # inside the widget instead of being clipped into a jagged edge.
            halo_radius = side / 2 - 2
            halo = QRadialGradient(center, halo_radius)
            transparent_warning = QColor(peak_color)
            transparent_warning.setAlpha(0)
            soft_warning = QColor(peak_color)
            soft_warning.setAlpha(64 if self._hovered else 48)
            bright_warning = QColor(peak_color)
            bright_warning.setAlpha(220 if self._hovered else 190)
            outer_warning = QColor(peak_color)
            outer_warning.setAlpha(82 if self._hovered else 62)
            halo.setColorAt(0.82, transparent_warning)
            halo.setColorAt(0.88, soft_warning)
            halo.setColorAt(0.93, bright_warning)
            halo.setColorAt(0.97, outer_warning)
            halo.setColorAt(1.0, transparent_warning)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(center, halo_radius, halo_radius)
        else:
            glow = QColor(theme.accent)
            glow.setAlpha(24 if self._active else 70 if self._hovered else 36)
            painter.setPen(QPen(glow, 4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, side / 2 - 3, side / 2 - 3)

        outer = QRadialGradient(center, ball_radius)
        outer.setColorAt(0.0, QColor(theme.elevated))
        outer.setColorAt(0.72, QColor(theme.surface))
        outer.setColorAt(1.0, QColor(theme.window))
        painter.setBrush(outer)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, ball_radius, ball_radius)

        if self._peak_highlight:
            border_color = QColor(peak_color)
            border_color.setAlpha(210 if self._active else 235)
            painter.setPen(QPen(border_color, 3))
        else:
            border = (
                theme.accent_hover if self._quota_mode and self._hovered
                else theme.border_hover if self._hovered
                else theme.accent
            )
            painter.setPen(QPen(QColor(border), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, ball_radius, ball_radius)

        if self._quota_mode:
            self._paint_quota(painter, theme, ball_radius)
            painter.end()
            return

        highlight = QLinearGradient(0, 8, 0, side * 0.55)
        highlight_start = QColor(theme.accent)
        highlight_start.setAlpha(42)
        highlight_end = QColor(theme.accent)
        highlight_end.setAlpha(0)
        highlight.setColorAt(0.0, highlight_start)
        highlight.setColorAt(1.0, highlight_end)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(highlight)
        painter.drawEllipse(QRectF(16, 12, side - 32, side * 0.42))

        painter.setPen(QColor(theme.subtext))
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        painter.drawText(
            QRectF(10, 18, side - 20, 18),
            Qt.AlignmentFlag.AlignCenter,
            self._primary_label,
        )

        painter.setPen(QColor(theme.value))
        value_size = 16 if len(self._today) <= 8 else 12
        painter.setFont(QFont("Microsoft YaHei UI", value_size, QFont.Weight.Bold))
        painter.drawText(QRectF(8, 34, side - 16, 25), Qt.AlignmentFlag.AlignCenter, self._today)

        painter.setPen(QPen(QColor(theme.border), 1))
        painter.drawLine(QPointF(side * 0.25, 64), QPointF(side * 0.75, 64))
        painter.setPen(QColor(theme.subtext))
        painter.setFont(QFont("Microsoft YaHei UI", 8))
        painter.drawText(
            QRectF(10, 65, side - 20, 15),
            Qt.AlignmentFlag.AlignCenter,
            self._secondary_label,
        )
        painter.setPen(QColor(theme.accent_hover))
        balance_size = 11 if len(self._balance) <= 8 else 9
        painter.setFont(QFont("Microsoft YaHei UI", balance_size, QFont.Weight.DemiBold))
        painter.drawText(QRectF(14, 80, side - 28, 19), Qt.AlignmentFlag.AlignCenter, self._balance)
        painter.end()
