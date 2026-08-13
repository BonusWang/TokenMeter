"""Custom-painted floating usage ball."""

from __future__ import annotations

import logging
import math
import random

from PySide6.QtCore import QElapsedTimer, QPoint, QPointF, QRectF, Qt, QTimer, Signal
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

logger = logging.getLogger(__name__)

DESIGN_SIZE = 120

# 液体手感参数集中在这里，避免调试波动时在事件和绘制代码间追逐魔法数字。
LIQUID_NODE_COUNT = 14
SPRING_STRENGTH = 48.0
DAMPING = 6.4
WAVE_SPREAD = 44.0
MOUSE_IMPULSE_STRENGTH = 0.075
MOUSE_SPLIT_MIN_WIDTH = 1.8
MOUSE_SPLIT_MAX_WIDTH = 3.5
DRAG_INERTIA_STRENGTH = 0.0045
MAX_WAVE_HEIGHT = 0.16
SETTLE_HEIGHT_THRESHOLD = 0.0012
SETTLE_VELOCITY_THRESHOLD = 0.006
POINTER_SAMPLE_INTERVAL_MS = 8
POINTER_VELOCITY_FILTER = 0.3
ACTIVE_FRAME_INTERVAL_MS = 16
IDLE_FRAME_INTERVAL_MS = 40
IDLE_WAVE_PRIMARY_AMPLITUDE = 0.45
IDLE_WAVE_SECONDARY_AMPLITUDE = 0.28
IDLE_WAVE_TERTIARY_AMPLITUDE = 0.15
IDLE_WEIGHT_ACTIVE = 0.28
IDLE_IMPULSE_MIN_INTERVAL = 2.0
IDLE_IMPULSE_MAX_INTERVAL = 5.0
IDLE_IMPULSE_MIN_AMPLITUDE = 0.15
IDLE_IMPULSE_MAX_AMPLITUDE = 0.35


class LiquidSurfaceState:
    """Fourteen-point free surface that creates fluid-looking separation cheaply."""

    def __init__(self, node_count: int = LIQUID_NODE_COUNT) -> None:
        self.node_count = node_count
        self.heights = [0.0] * node_count
        self.velocities = [0.0] * node_count
        self.idle_phase = 0.0
        self.idle_weight = 1.0
        self.drag_tilt = 0.0
        self.vertical_compression = 0.0
        self._idle_random = random.Random()
        self.idle_impulse_remaining = self._next_idle_impulse_interval()

    def reset(self) -> None:
        self.heights[:] = [0.0] * self.node_count
        self.velocities[:] = [0.0] * self.node_count
        self.idle_phase = 0.0
        self.idle_weight = 1.0
        self.drag_tilt = 0.0
        self.vertical_compression = 0.0
        self.idle_impulse_remaining = self._next_idle_impulse_interval()

    def clear_motion(self) -> None:
        self.heights[:] = [0.0] * self.node_count
        self.velocities[:] = [0.0] * self.node_count
        self.drag_tilt = 0.0
        self.vertical_compression = 0.0

    def _next_idle_impulse_interval(self) -> float:
        return self._idle_random.uniform(
            IDLE_IMPULSE_MIN_INTERVAL,
            IDLE_IMPULSE_MAX_INTERVAL,
        )

    def _inject_idle_impulse(self) -> None:
        center = self._idle_random.uniform(1.5, self.node_count - 2.5)
        amplitude_px = self._idle_random.uniform(
            IDLE_IMPULSE_MIN_AMPLITUDE,
            IDLE_IMPULSE_MAX_AMPLITUDE,
        )
        direction = -1.0 if self._idle_random.random() < 0.5 else 1.0
        velocity_strength = amplitude_px / DESIGN_SIZE * math.sqrt(SPRING_STRENGTH)
        for index in range(self.node_count):
            distance = abs(index - center)
            if distance <= 2.2:
                self.velocities[index] += (
                    direction * velocity_strength * math.exp(-((distance / 0.9) ** 2))
                )

    @property
    def activity(self) -> float:
        return max(
            max((abs(value) for value in self.heights), default=0.0),
            max((abs(value) for value in self.velocities), default=0.0) * 0.12,
            abs(self.drag_tilt),
            abs(self.vertical_compression),
        )

    @property
    def settled(self) -> bool:
        return (
            max((abs(value) for value in self.heights), default=0.0) < SETTLE_HEIGHT_THRESHOLD
            and max((abs(value) for value in self.velocities), default=0.0)
            < SETTLE_VELOCITY_THRESHOLD
            and abs(self.drag_tilt) < SETTLE_HEIGHT_THRESHOLD
            and abs(self.vertical_compression) < SETTLE_HEIGHT_THRESHOLD
        )

    def disturb(
        self,
        node_position: float,
        normalized_speed: float,
        direction_x: float,
    ) -> None:
        speed = max(0.0, min(7.0, normalized_speed))
        if speed <= 0:
            return
        width = min(
            MOUSE_SPLIT_MAX_WIDTH,
            MOUSE_SPLIT_MIN_WIDTH + speed * 0.28,
        )
        strength = min(0.46, speed * MOUSE_IMPULSE_STRENGTH)
        self.idle_weight = min(self.idle_weight, IDLE_WEIGHT_ACTIVE)
        direction = 1.0 if direction_x >= 0 else -1.0
        for index in range(self.node_count):
            offset = index - node_position
            distance = abs(offset)
            if distance > width * 1.2:
                continue
            # 中间向下、两肩向上；前肩略高、尾侧略深，形成分流而非单点橡皮筋凹陷。
            trough = math.exp(-((distance / max(0.01, width * 0.42)) ** 2))
            crest = math.exp(-(((distance - width * 0.72) / max(0.01, width * 0.22)) ** 2))
            directional_crest = 1.14 if offset * direction > 0 else 0.92
            trailing_wake = (
                math.exp(-(((offset + direction * width * 0.32) / (width * 0.34)) ** 2)) * 0.16
            )
            self.velocities[index] += strength * (
                trough + trailing_wake - crest * 0.82 * directional_crest
            )

    def add_drag_acceleration(self, acceleration_x: float, acceleration_y: float) -> None:
        tilt_impulse = acceleration_x * DRAG_INERTIA_STRENGTH
        compression_impulse = acceleration_y * DRAG_INERTIA_STRENGTH * 0.55
        self.idle_weight = min(self.idle_weight, 0.22)
        self.drag_tilt = max(
            -MAX_WAVE_HEIGHT * 2.25,
            min(
                MAX_WAVE_HEIGHT * 2.25,
                self.drag_tilt + acceleration_x * DRAG_INERTIA_STRENGTH,
            ),
        )
        self.vertical_compression = max(
            -MAX_WAVE_HEIGHT,
            min(
                MAX_WAVE_HEIGHT,
                self.vertical_compression + acceleration_y * DRAG_INERTIA_STRENGTH * 0.55,
            ),
        )
        for index in range(self.node_count):
            centered = index / (self.node_count - 1) - 0.5
            compression_shape = 1 - centered * centered * 4 - 2 / 3
            self.velocities[index] += (
                tilt_impulse * centered * 1.7 + compression_impulse * compression_shape * 0.8
            )

    def step(self, elapsed_seconds: float) -> None:
        dt = max(0.001, min(0.05, elapsed_seconds))
        self.idle_phase += dt
        if self.activity < 0.012:
            self.idle_impulse_remaining -= dt
            if self.idle_impulse_remaining <= 0:
                self._inject_idle_impulse()
                self.idle_impulse_remaining = self._next_idle_impulse_interval()
        previous = list(self.heights)
        velocity_damping = math.exp(-DAMPING * dt)
        target_idle_weight = 1.0 if self.activity < 0.012 else IDLE_WEIGHT_ACTIVE
        blend_rate = 1.6 if target_idle_weight > self.idle_weight else 8.0
        self.idle_weight += (target_idle_weight - self.idle_weight) * (
            1 - math.exp(-blend_rate * dt)
        )

        for index in range(self.node_count):
            progress = index / (self.node_count - 1)
            centered = progress - 0.5
            drag_target = self.drag_tilt * centered * 2
            # 上下加速度使用零均值的弧形目标，只产生压缩/回弹，不篡改平均额度。
            compression_shape = 1 - centered * centered * 4 - 2 / 3
            target = drag_target + self.vertical_compression * compression_shape
            left = previous[index - 1] if index > 0 else previous[index]
            right = previous[index + 1] if index < self.node_count - 1 else previous[index]
            neighbor_force = (left + right - previous[index] * 2) * WAVE_SPREAD
            acceleration = (target - previous[index]) * SPRING_STRENGTH + neighbor_force
            self.velocities[index] = (self.velocities[index] + acceleration * dt) * velocity_damping
            self.heights[index] = max(
                -MAX_WAVE_HEIGHT,
                min(
                    MAX_WAVE_HEIGHT,
                    previous[index] + self.velocities[index] * dt,
                ),
            )

        # 浮动只改变液面形状，平均高度必须继续精确表达真实额度。
        mean_height = sum(self.heights) / self.node_count
        mean_velocity = sum(self.velocities) / self.node_count
        self.heights[:] = [height - mean_height for height in self.heights]
        self.velocities[:] = [velocity - mean_velocity for velocity in self.velocities]
        self.drag_tilt *= math.exp(-5.4 * dt)
        self.vertical_compression *= math.exp(-7.0 * dt)


class FloatingUsageBall(QWidget):
    pressed = Signal(QPoint)
    dragged = Signal(QPoint)
    released = Signal(QPoint)
    resize_started = Signal(QPoint)
    resize_dragged = Signal(QPoint)
    resize_released = Signal(QPoint)

    def __init__(self, size: int = 88, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setMouseTracking(True)
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
        self._liquid_surface = LiquidSurfaceState()
        self._pointer_last_local: QPointF | None = None
        self._pointer_smoothed_velocity = QPointF()
        self._pointer_clock = QElapsedTimer()
        self._drag_last_global: QPointF | None = None
        self._drag_last_velocity = QPointF()
        self._drag_clock = QElapsedTimer()
        self._wave_clock = QElapsedTimer()
        self._wave_clock.start()
        self._wave_timer = QTimer(self)
        self._wave_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._wave_timer.setInterval(ACTIVE_FRAME_INTERVAL_MS)
        self._wave_timer.timeout.connect(self._advance_wave)
        self._quota_geometry_cache: dict[float, tuple[QRectF, QPainterPath]] = {}
        self._water_gradient_cache: dict[tuple[str, float, float], QLinearGradient] = {}
        self._quota_font_cache: dict[int, QFont] = {}
        self._debug_profile: dict[str, tuple[int, int]] = {}
        self._water_shine_gradient = QLinearGradient(-36, 0, 36, 0)
        self._water_shine_gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
        self._water_shine_gradient.setColorAt(0.38, QColor(255, 255, 255, 4))
        self._water_shine_gradient.setColorAt(0.5, QColor(225, 247, 255, 18))
        self._water_shine_gradient.setColorAt(0.62, QColor(255, 255, 255, 4))
        self._water_shine_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        self._deep_flow_gradient = QLinearGradient(-44, 0, 44, 0)
        self._deep_flow_gradient.setColorAt(0.0, QColor(8, 35, 98, 0))
        self._deep_flow_gradient.setColorAt(0.38, QColor(8, 35, 98, 3))
        self._deep_flow_gradient.setColorAt(0.5, QColor(8, 35, 98, 16))
        self._deep_flow_gradient.setColorAt(0.62, QColor(8, 35, 98, 3))
        self._deep_flow_gradient.setColorAt(1.0, QColor(8, 35, 98, 0))
        self._glass_highlight_path = QPainterPath(QPointF(23, 47))
        self._glass_highlight_path.cubicTo(
            QPointF(27, 29),
            QPointF(43, 18),
            QPointF(68, 17),
        )
        self._peak_highlight = False
        self._hovered = False
        self._active = False
        self._resizing = False
        theme_controller().changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str, _resolved: str) -> None:
        self._water_gradient_cache.clear()
        self.update()

    def _record_debug_profile(self, name: str, elapsed_ns: int) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return
        count, total_ns = self._debug_profile.get(name, (0, 0))
        count += 1
        total_ns += elapsed_ns
        if count >= 120:
            logger.debug(
                "Codex water ball %s average: %.3f ms",
                name,
                total_ns / count / 1_000_000,
            )
            count, total_ns = 0, 0
        self._debug_profile[name] = (count, total_ns)

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
            str(value).replace(" 天 ", "天 ").replace(" 小时", "小时").replace(" 分钟", "分钟")[:10]
        )

    def set_quota_state(
        self,
        remaining_percent: float | None,
        reset_text: str,
        title: str = "周额度",
    ) -> None:
        remaining = (
            None if remaining_percent is None else max(0.0, min(100.0, float(remaining_percent)))
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
        if remaining is None or remaining <= 0:
            # 空额度停止动画并清掉动量，避免下次恢复额度时复活旧余波。
            self._liquid_surface.reset()
        remaining_text = "未知" if remaining is None else f"{remaining:.0f}%"
        self.setAccessibleName("Codex 剩余额度")
        self.setAccessibleDescription(remaining_text)
        self.setToolTip(remaining_text)
        if self.isVisible():
            if remaining is not None and remaining > 0:
                self._ensure_animation()
            else:
                self._wave_timer.stop()
        self.update()

    def clear_quota_state(self) -> None:
        if not self._quota_mode:
            return
        self._quota_mode = False
        self._quota_remaining = None
        self._quota_reset_text = ""
        self._wave_timer.stop()
        self._liquid_surface.reset()
        self._pointer_last_local = None
        self._pointer_smoothed_velocity = QPointF()
        self._drag_last_global = None
        self._drag_last_velocity = QPointF()
        self.setAccessibleName("")
        self.setAccessibleDescription("")
        self.setToolTip("")
        self.update()

    def _ensure_animation(self) -> None:
        if self._quota_remaining is None or self._quota_remaining <= 0:
            return
        if self._active or not self._liquid_surface.settled:
            self._wave_timer.setInterval(ACTIVE_FRAME_INTERVAL_MS)
        if not self._wave_timer.isActive():
            self._wave_clock.restart()
            self._wave_timer.start()

    def _advance_wave(self) -> None:
        profile_timer = QElapsedTimer()
        if logger.isEnabledFor(logging.DEBUG):
            profile_timer.start()
        elapsed_ms = self._wave_clock.restart()
        elapsed_seconds = 0.016 if elapsed_ms <= 0 else min(elapsed_ms, 50) / 1000
        self._liquid_surface.step(elapsed_seconds)
        self._wave_phase = (self._liquid_surface.idle_phase * 0.4) % math.tau
        self.update()
        active_motion = self._active or not self._liquid_surface.settled
        interval = ACTIVE_FRAME_INTERVAL_MS if active_motion else IDLE_FRAME_INTERVAL_MS
        if self._wave_timer.interval() != interval:
            self._wave_timer.setInterval(interval)
        if not self._active and self._liquid_surface.settled:
            self._liquid_surface.clear_motion()
        if profile_timer.isValid():
            self._record_debug_profile("physics_update", profile_timer.nsecsElapsed())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._quota_mode and self._quota_remaining is not None and self._quota_remaining > 0:
            self._ensure_animation()

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
        self._pointer_last_local = QPointF(event.position())
        self._pointer_smoothed_velocity = QPointF()
        self._pointer_clock.restart()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._pointer_last_local = None
        self._pointer_smoothed_velocity = QPointF()
        if not self._resizing:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update()
        super().leaveEvent(event)

    def _resize_handle_rect(self) -> QRectF:
        scale = min(self.width(), self.height()) / DESIGN_SIZE
        # 点击区必须落在圆形窗口掩码内，否则 Windows 会把右下角事件裁掉。
        return QRectF(78 * scale, 78 * scale, 24 * scale, 24 * scale)

    def _liquid_inner_rect(self) -> QRectF:
        ball_radius = DESIGN_SIZE / 2 - (8 if self._peak_highlight else 3)
        inner, _ = self._quota_geometry(ball_radius)
        return QRectF(inner)

    def _disturb_surface_from_pointer(self, position: QPointF) -> bool:
        if self._pointer_last_local is None:
            self._pointer_last_local = QPointF(position)
            self._pointer_clock.restart()
            return False
        elapsed_ms = self._pointer_clock.elapsed()
        if 0 <= elapsed_ms < POINTER_SAMPLE_INTERVAL_MS:
            return False
        self._pointer_clock.restart()
        elapsed_seconds = 0.016 if elapsed_ms <= 0 else elapsed_ms / 1000
        delta = position - self._pointer_last_local
        self._pointer_last_local = QPointF(position)
        side = max(1.0, min(self.width(), self.height()))
        design_position = QPointF(
            position.x() * DESIGN_SIZE / side,
            position.y() * DESIGN_SIZE / side,
        )
        ball_radius = DESIGN_SIZE / 2 - (8 if self._peak_highlight else 3)
        inner, clip = self._quota_geometry(ball_radius)
        if not clip.contains(design_position) or self._quota_remaining is None:
            return False
        ratio = self._quota_remaining / 100
        if ratio <= 0:
            return False
        progress = max(
            0.0,
            min(1.0, (design_position.x() - inner.left()) / inner.width()),
        )
        node_position = progress * (self._liquid_surface.node_count - 1)
        low_index = int(node_position)
        high_index = min(self._liquid_surface.node_count - 1, low_index + 1)
        blend = node_position - low_index
        surface_offset = (
            self._liquid_surface.heights[low_index] * (1 - blend)
            + self._liquid_surface.heights[high_index] * blend
        ) * inner.height()
        surface_y = inner.bottom() - inner.height() * ratio + surface_offset
        if ratio < 0.995 and design_position.y() < surface_y - 5:
            return False
        raw_velocity = QPointF(
            delta.x() / side / elapsed_seconds,
            delta.y() / side / elapsed_seconds,
        )
        self._pointer_smoothed_velocity = QPointF(
            self._pointer_smoothed_velocity.x() * (1 - POINTER_VELOCITY_FILTER)
            + raw_velocity.x() * POINTER_VELOCITY_FILTER,
            self._pointer_smoothed_velocity.y() * (1 - POINTER_VELOCITY_FILTER)
            + raw_velocity.y() * POINTER_VELOCITY_FILTER,
        )
        normalized_speed = math.hypot(
            self._pointer_smoothed_velocity.x(),
            self._pointer_smoothed_velocity.y(),
        )
        if normalized_speed < 0.05:
            return False
        self._liquid_surface.disturb(
            node_position,
            normalized_speed,
            self._pointer_smoothed_velocity.x(),
        )
        self._ensure_animation()
        return True

    def _sample_drag_motion(self, position: QPointF) -> None:
        if self._drag_last_global is None:
            self._drag_last_global = QPointF(position)
            self._drag_clock.restart()
            return
        elapsed_ms = self._drag_clock.restart()
        elapsed_seconds = 0.016 if elapsed_ms <= 0 else max(0.008, elapsed_ms / 1000)
        delta = position - self._drag_last_global
        self._drag_last_global = QPointF(position)
        side = max(1.0, min(self.width(), self.height()))
        raw_velocity = QPointF(
            max(-12.0, min(12.0, delta.x() / side / elapsed_seconds)),
            max(-12.0, min(12.0, delta.y() / side / elapsed_seconds)),
        )
        # 平滑采样速度以过滤 Windows 鼠标事件间隔抖动，同时保留启动和反向的加速度峰值。
        velocity = QPointF(
            self._drag_last_velocity.x() + (raw_velocity.x() - self._drag_last_velocity.x()) * 0.52,
            self._drag_last_velocity.y() + (raw_velocity.y() - self._drag_last_velocity.y()) * 0.52,
        )
        acceleration = QPointF(
            max(
                -80.0,
                min(80.0, (velocity.x() - self._drag_last_velocity.x()) / elapsed_seconds),
            ),
            max(
                -80.0,
                min(80.0, (velocity.y() - self._drag_last_velocity.y()) / elapsed_seconds),
            ),
        )
        self._drag_last_velocity = velocity
        # 使用容器加速度而不是鼠标位置：匀速阶段外力自然归零，启动/停止/反向最明显。
        self._liquid_surface.add_drag_acceleration(
            acceleration.x(),
            acceleration.y(),
        )
        self._ensure_animation()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._resize_handle_rect().contains(event.position()):
                self._resizing = True
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                self.update()
                self.resize_started.emit(event.globalPosition().toPoint())
                event.accept()
                return
            self._active = True
            self._drag_last_global = QPointF(event.globalPosition())
            self._drag_last_velocity = QPointF()
            self._drag_clock.restart()
            self._ensure_animation()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()
            self.pressed.emit(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        profile_timer = QElapsedTimer()
        if logger.isEnabledFor(logging.DEBUG):
            profile_timer.start()
        try:
            if self._resizing and event.buttons() & Qt.MouseButton.LeftButton:
                self.resize_dragged.emit(event.globalPosition().toPoint())
                event.accept()
                return
            if event.buttons() & Qt.MouseButton.LeftButton:
                self._sample_drag_motion(event.globalPosition())
                self.dragged.emit(event.globalPosition().toPoint())
                event.accept()
                return
            self._disturb_surface_from_pointer(event.position())
            cursor = (
                Qt.CursorShape.SizeFDiagCursor
                if self._resize_handle_rect().contains(event.position())
                else Qt.CursorShape.OpenHandCursor
            )
            self.setCursor(cursor)
            super().mouseMoveEvent(event)
        finally:
            if profile_timer.isValid():
                self._record_debug_profile("mouseMoveEvent", profile_timer.nsecsElapsed())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._resizing:
                self._resizing = False
                self.setCursor(
                    Qt.CursorShape.SizeFDiagCursor
                    if self._resize_handle_rect().contains(event.position())
                    else Qt.CursorShape.OpenHandCursor
                )
                self.update()
                self.resize_released.emit(event.globalPosition().toPoint())
                event.accept()
                return
            # 停止本身是一次反向加速度；把它注入节点后再清除拖拽采样状态。
            stop_acceleration_x = -self._drag_last_velocity.x() / 0.045
            stop_acceleration_y = -self._drag_last_velocity.y() / 0.045
            self._liquid_surface.add_drag_acceleration(
                stop_acceleration_x,
                stop_acceleration_y,
            )
            self._ensure_animation()
            self._active = False
            self._drag_last_global = None
            self._drag_last_velocity = QPointF()
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.update()
            self.released.emit(event.globalPosition().toPoint())
            event.accept()

    def _paint_resize_handle(self, painter: QPainter, theme) -> None:
        if not self._hovered and not self._resizing:
            return
        color = QColor(theme.accent_hover)
        color.setAlpha(245 if self._resizing else 210)
        painter.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        # 三条斜线比实心角标更轻，不会遮挡缩小后的额度或余额文字。
        painter.drawLine(QPointF(84, 98), QPointF(98, 84))
        painter.drawLine(QPointF(89, 100), QPointF(100, 89))
        painter.drawLine(QPointF(80, 94), QPointF(94, 80))

    @staticmethod
    def _smooth_surface_path(rect: QRectF, surface_y: float, offsets: list[float]) -> QPainterPath:
        points = [
            QPointF(
                rect.left() + rect.width() * index / (len(offsets) - 1),
                surface_y + offset,
            )
            for index, offset in enumerate(offsets)
        ]
        path = QPainterPath(points[0])
        # Catmull-Rom 转三次贝塞尔，保证节点能传播尖锐冲量但绘制出来仍是连续液面。
        for index in range(len(points) - 1):
            previous = points[index - 1] if index > 0 else points[index]
            current = points[index]
            following = points[index + 1]
            after = points[index + 2] if index + 2 < len(points) else following
            control_one = current + (following - previous) / 6
            control_two = following - (after - current) / 6
            path.cubicTo(control_one, control_two, following)
        return path

    def _idle_surface_offsets(
        self,
        rect: QRectF,
        phase_shift: float = 0.0,
    ) -> list[float]:
        time = self._liquid_surface.idle_phase
        weight = self._liquid_surface.idle_weight
        offsets = [
            weight
            * (
                math.sin(x * 0.060 - time * 0.55 + phase_shift)
                * IDLE_WAVE_PRIMARY_AMPLITUDE
                + math.sin(x * 0.037 + time * 0.31 + 1.6 + phase_shift * 0.63)
                * IDLE_WAVE_SECONDARY_AMPLITUDE
                + math.sin(x * 0.095 - time * 0.18 + 3.1 - phase_shift * 0.4)
                * IDLE_WAVE_TERTIARY_AMPLITUDE
            )
            for x in (
                rect.left() + rect.width() * index / (self._liquid_surface.node_count - 1)
                for index in range(self._liquid_surface.node_count)
            )
        ]
        # 三组双向行波在有限节点上并非天然零均值；去掉均值才能保证 idle 不篡改额度水位。
        mean_offset = sum(offsets) / len(offsets)
        return [offset - mean_offset for offset in offsets]

    def _surface_paths(
        self,
        rect: QRectF,
        surface_y: float,
        ratio: float,
        back_layer: bool = False,
    ) -> tuple[QPainterPath, QPainterPath]:
        edge_scale = min(1.0, min(ratio, 1 - ratio) / 0.16)
        layer_scale = 0.62 if back_layer else 1.0
        layer_shift = -1.5 if back_layer else 0.8
        idle_offsets = self._idle_surface_offsets(rect, 0.72 if back_layer else 0.0)
        offsets = [
            (
                height * rect.height() * layer_scale
                + idle_offsets[index] * (0.7 if back_layer else 1.0)
            )
            * edge_scale
            for index, height in enumerate(self._liquid_surface.heights)
        ]
        surface = self._smooth_surface_path(rect, surface_y + layer_shift, offsets)
        fill = QPainterPath(surface)
        fill.lineTo(rect.right(), rect.bottom() + 1)
        fill.lineTo(rect.left(), rect.bottom() + 1)
        fill.closeSubpath()
        return fill, surface

    def _subsurface_highlight_path(
        self,
        rect: QRectF,
        surface_y: float,
        ratio: float,
    ) -> QPainterPath:
        edge_scale = min(1.0, min(ratio, 1 - ratio) / 0.16)
        idle_offsets = self._idle_surface_offsets(rect, 1.1)
        offsets = [
            (height * rect.height() * 0.68 + idle_offsets[index] * 0.72) * edge_scale
            for index, height in enumerate(self._liquid_surface.heights)
        ]
        return self._smooth_surface_path(rect, surface_y + 3.2, offsets)

    def _paint_full_quota_flow(
        self,
        painter: QPainter,
        theme,
        inner: QRectF,
        clip: QPainterPath,
    ) -> None:
        center = inner.center()
        phase_angle = math.degrees(self._wave_phase)
        activity = min(1.0, self._liquid_surface.activity / MAX_WAVE_HEIGHT)
        edge_delta = self._liquid_surface.heights[-1] - self._liquid_surface.heights[0]
        painter.save()
        painter.setClipPath(clip)
        painter.translate(center)
        painter.translate(-edge_delta * inner.width() * 0.16, 0)
        painter.rotate(phase_angle + edge_delta * 46)
        painter.translate(-center)

        # 满液位没有可见液面；用同一永久 idle 相位缓慢移动内部弧光。
        flow_color = QColor("#FFFFFF")
        flow_color.setAlpha(round(24 + activity * 58))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(
                flow_color,
                4.5,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawArc(inner.adjusted(11, 16, -11, -16), 18 * 16, 142 * 16)

        inner_flow = QColor(theme.accent_hover)
        inner_flow.setAlpha(round(50 + activity * 62))
        painter.setPen(
            QPen(
                inner_flow,
                3.0,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawArc(inner.adjusted(21, 25, -21, -25), 198 * 16, 154 * 16)
        painter.restore()

        if activity > 0.03:
            # 满水时只在受力阶段投影一条柔和流带，避免常驻锐利横线被误读为 50% 液面。
            flow_offsets = [
                height * inner.height() * 0.55 for height in self._liquid_surface.heights
            ]
            flow_band = self._smooth_surface_path(inner, center.y(), flow_offsets)
            band_color = QColor(theme.accent_hover)
            band_color.setAlpha(round(18 + activity * 62))
            painter.save()
            painter.setClipPath(clip)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(
                QPen(
                    band_color,
                    4.5 + activity * 3.5,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawPath(flow_band)
            painter.restore()

        rim_light = QColor("#FFFFFF")
        rim_light.setAlpha(round(45 + activity * 82))
        painter.setPen(
            QPen(
                rim_light,
                1.5,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        start = round((28 - phase_angle - edge_delta * 80) * 16)
        painter.drawArc(inner.adjusted(2, 2, -2, -2), start, 78 * 16)

    @staticmethod
    def _paint_centered_text(
        painter: QPainter,
        rect: QRectF,
        text: str,
        color: QColor,
        shadow: QColor,
    ) -> None:
        painter.setPen(shadow)
        painter.drawText(
            rect.translated(0, 1),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )
        painter.setPen(color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _quota_geometry(self, ball_radius: float) -> tuple[QRectF, QPainterPath]:
        key = round(ball_radius, 2)
        cached = self._quota_geometry_cache.get(key)
        if cached is not None:
            return cached
        inner_margin = DESIGN_SIZE / 2 - ball_radius + 3
        inner = QRectF(
            inner_margin,
            inner_margin,
            DESIGN_SIZE - inner_margin * 2,
            DESIGN_SIZE - inner_margin * 2,
        )
        clip = QPainterPath()
        clip.addEllipse(inner)
        self._quota_geometry_cache[key] = (inner, clip)
        return inner, clip

    def _water_gradient(self, theme, surface_y: float, bottom: float) -> QLinearGradient:
        key = (theme.name, round(surface_y, 2), round(bottom, 2))
        cached = self._water_gradient_cache.get(key)
        if cached is not None:
            return cached
        water_top = QColor("#73BDFF" if theme.name == "light" else "#5CA6FF")
        water_top.setAlpha(205 if theme.name == "light" else 218)
        upper = QColor(theme.accent_hover)
        upper.setAlpha(224)
        middle = QColor(theme.accent)
        middle.setAlpha(236)
        deep = QColor(theme.accent).darker(138)
        deep.setAlpha(248)
        water = QLinearGradient(0, surface_y, 0, bottom)
        water.setColorAt(0.0, water_top)
        water.setColorAt(0.2, upper)
        water.setColorAt(0.64, middle)
        water.setColorAt(1.0, deep)
        self._water_gradient_cache[key] = water
        return water

    def _paint_water_shine(
        self,
        painter: QPainter,
        inner: QRectF,
        water_path: QPainterPath,
    ) -> None:
        shine_progress = (self._liquid_surface.idle_phase % 12.0) / 12.0
        shine_margin = inner.width() * 0.45
        shine_x = inner.left() - shine_margin + shine_progress * (inner.width() + shine_margin * 2)
        painter.save()
        painter.setClipPath(water_path)
        painter.translate(shine_x, inner.center().y())
        painter.rotate(-10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._water_shine_gradient)
        painter.drawRect(QRectF(-36, -inner.height(), 72, inner.height() * 2))
        painter.restore()

    def _paint_deep_flow(
        self,
        painter: QPainter,
        inner: QRectF,
        water_path: QPainterPath,
    ) -> None:
        deep_progress = (self._liquid_surface.idle_phase % 16.0) / 16.0
        deep_margin = inner.width() * 0.5
        deep_x = inner.right() + deep_margin - deep_progress * (
            inner.width() + deep_margin * 2
        )
        painter.save()
        painter.setClipPath(water_path)
        painter.translate(deep_x, inner.center().y())
        painter.rotate(7)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._deep_flow_gradient)
        painter.drawRect(QRectF(-44, 0, 88, inner.height()))
        painter.restore()

    def _paint_glass_highlight(self, painter: QPainter) -> None:
        highlight = QColor(255, 255, 255, 38 if self._hovered else 28)
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(
                highlight,
                1.8,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawPath(self._glass_highlight_path)
        painter.restore()

    def _paint_quota(self, painter: QPainter, theme, ball_radius: float) -> None:
        inner, clip = self._quota_geometry(ball_radius)
        water_path = QPainterPath()
        if self._quota_remaining is not None and self._quota_remaining > 0:
            ratio = self._quota_remaining / 100
            surface_y = inner.bottom() - inner.height() * ratio

            painter.save()
            painter.setClipPath(clip)
            water_top = QColor(theme.heat[3] if theme.name == "light" else theme.accent_hover)
            water = self._water_gradient(theme, surface_y, inner.bottom())

            if ratio >= 0.995:
                water_path = QPainterPath(clip)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(water)
                painter.drawPath(water_path)
                self._paint_deep_flow(painter, inner, water_path)
                self._paint_water_shine(painter, inner, water_path)
                self._paint_full_quota_flow(painter, theme, inner, water_path)
            else:
                back_path, _back_surface = self._surface_paths(
                    inner, surface_y, ratio, back_layer=True
                )
                water_path, water_surface = self._surface_paths(inner, surface_y, ratio)

                back_color = QColor(water_top)
                back_color.setAlpha(170)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(back_color)
                painter.drawPath(back_path)
                painter.setBrush(water)
                painter.drawPath(water_path)
                self._paint_deep_flow(painter, inner, water_path)
                self._paint_water_shine(painter, inner, water_path)

                subsurface = self._subsurface_highlight_path(inner, surface_y, ratio)
                subsurface_color = QColor(220, 245, 255, 34)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(
                    QPen(
                        subsurface_color,
                        1.0,
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap,
                    )
                )
                painter.drawPath(subsurface)

                surface_highlight = QColor("#FFFFFF")
                surface_highlight.setAlpha(
                    round(92 + min(1.0, self._liquid_surface.activity * 5) * 38)
                )
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(
                    QPen(
                        surface_highlight,
                        1.25,
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap,
                    )
                )
                painter.drawPath(water_surface)
            painter.restore()

        inner_rim = QColor(theme.accent_hover if theme.name == "light" else "#FFFFFF")
        inner_rim.setAlpha(105 if theme.name == "light" else 78)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(inner_rim, 1.2))
        painter.drawEllipse(inner.adjusted(0.7, 0.7, -0.7, -0.7))

        percentage = "--" if self._quota_remaining is None else f"{self._quota_remaining:.0f}%"
        value_size = 25 if len(percentage) <= 3 else 22 if len(percentage) <= 4 else 20
        value_font = self._quota_font_cache.get(value_size)
        if value_font is None:
            value_font = QFont("Microsoft YaHei UI", value_size, QFont.Weight.Bold)
            self._quota_font_cache[value_size] = value_font
        painter.setFont(value_font)
        value_rect = QRectF(8, 36, 104, 48)
        empty_shadow = QColor("#000000" if theme.name == "dark" else "#FFFFFF")
        empty_shadow.setAlpha(130)
        water_shadow = QColor("#000000")
        water_shadow.setAlpha(145)

        if water_path.isEmpty():
            self._paint_centered_text(
                painter,
                value_rect,
                percentage,
                QColor(theme.value),
                empty_shadow,
            )
            return

        # 同一数字按空气和液体区域各绘制一次，液面穿过文字时仍保持逐像素对比度。
        empty_path = clip.subtracted(water_path)
        painter.save()
        painter.setClipPath(empty_path)
        self._paint_centered_text(
            painter,
            value_rect,
            percentage,
            QColor(theme.value),
            empty_shadow,
        )
        painter.restore()

        painter.save()
        painter.setClipPath(water_path.intersected(clip))
        self._paint_centered_text(
            painter,
            value_rect,
            percentage,
            QColor("#FFFFFF"),
            water_shadow,
        )
        painter.restore()

    def paintEvent(self, _event) -> None:
        profile_timer = QElapsedTimer()
        if logger.isEnabledFor(logging.DEBUG):
            profile_timer.start()
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
                theme.accent_hover
                if self._quota_mode and self._hovered
                else theme.border_hover
                if self._hovered
                else theme.accent
            )
            painter.setPen(QPen(QColor(border), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, ball_radius, ball_radius)

        if self._quota_mode:
            self._paint_quota(painter, theme, ball_radius)
            self._paint_glass_highlight(painter)
        else:
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
            painter.drawText(
                QRectF(8, 34, side - 16, 25),
                Qt.AlignmentFlag.AlignCenter,
                self._today,
            )

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
            painter.drawText(
                QRectF(14, 80, side - 28, 19),
                Qt.AlignmentFlag.AlignCenter,
                self._balance,
            )
        self._paint_resize_handle(painter, theme)
        painter.end()
        if profile_timer.isValid():
            self._record_debug_profile("paintEvent", profile_timer.nsecsElapsed())
