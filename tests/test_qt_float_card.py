"""悬浮聚合卡片测试：分组渲染、低水位红显、徽章、tooltip 与点击信号。"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from api.aggregator import AccountQuota, summarize_by_provider
from api.providers.base import QuotaWindow
from ui.qt_float_card import FLOAT_CARD_WIDTH, FloatingUsageCard, water_color
from ui.qt_theme import current_theme

APP = QApplication.instance() or QApplication([])


def make_account(
    label: str = "智谱1",
    provider_id: str = "zhipu",
    provider_name: str = "Zhipu GLM",
    used: float = 57.0,
    weekly_used: float | None = 10.0,
    error: str = "",
) -> AccountQuota:
    windows: tuple[QuotaWindow, ...] = ()
    if not error:
        parts = [
            QuotaWindow(
                "five_hour",
                "5小时",
                used,
                resets_at=datetime.now() + timedelta(hours=1, minutes=49),
                window_minutes=300,
            )
        ]
        if weekly_used is not None:
            parts.append(
                QuotaWindow(
                    "weekly",
                    "7天",
                    weekly_used,
                    resets_at=datetime.now() + timedelta(days=7),
                    window_minutes=10_080,
                )
            )
        windows = tuple(parts)
    return AccountQuota(
        provider_id=provider_id,
        provider_name=provider_name,
        label=label,
        windows=windows,
        error=error,
    )


def two_group_accounts() -> list[AccountQuota]:
    return [
        make_account("智谱1", used=57.0, weekly_used=10.0),
        make_account("智谱2", used=26.0, weekly_used=90.0),
        make_account("智谱10", used=5.0, weekly_used=None),
        make_account(
            "MiniMax主",
            provider_id="minimax",
            provider_name="MiniMax",
            used=4.0,
            weekly_used=2.0,
        ),
    ]


def QColorLike(value: str) -> str:
    from PySide6.QtGui import QColor

    return QColor(value).name().upper()


def test_card_renders_two_groups_with_four_window_rows():
    card = FloatingUsageCard()
    card.set_state(summarize_by_provider(two_group_accounts()))

    assert card.width() == FLOAT_CARD_WIDTH
    assert len(card._sections) == 2

    zhipu = card._sections[0]
    assert zhipu._name_label.text() == "Zhipu GLM"
    assert zhipu._badge.text() == "3 账号"
    # 5小时 (43+74+95)/3=70.666…→70.7 显示 71%；每周缺窗口的智谱10剔除 (90+10)/2=50。
    assert zhipu._rows["five_hour"]._percent_label.text() == "71%"
    assert zhipu._rows["five_hour"]._bar.ratio == pytest.approx(0.707)
    assert zhipu._rows["weekly"]._percent_label.text() == "50%"

    # MiniMax 组内仅 1 账号照常成组。
    minimax = card._sections[1]
    assert minimax._name_label.text() == "MiniMax"
    assert minimax._badge.text() == "1 账号"
    assert minimax._rows["five_hour"]._percent_label.text() == "96%"

    # 两组内容渲染冒烟 + 卡片高度随内容自适应（高于占位态）。
    grouped_height = card.height()
    assert not card.grab().isNull()
    empty = FloatingUsageCard()
    empty.set_placeholder("正在更新额度")
    assert grouped_height > empty.height()


def test_card_low_water_rows_turn_danger_red():
    card = FloatingUsageCard()
    card.set_state(
        summarize_by_provider(
            [
                make_account("智谱1", used=85.0, weekly_used=10.0),  # 5h 余 15 / 周 余 90
            ]
        )
    )
    theme = current_theme()
    section = card._sections[0]
    assert section._rows["five_hour"]._percent_label.text() == "15%"
    assert section._rows["five_hour"]._bar.fill_color.name().upper() == QColorLike(
        theme.danger
    )
    assert section._rows["weekly"]._bar.fill_color.name().upper() == QColorLike(
        theme.success
    )
    # 与面板同一阈值：20% 恰好算低水位。
    assert water_color(20.0).name().upper() == QColorLike(theme.danger)
    assert water_color(20.5).name().upper() == QColorLike(theme.success)


def test_card_tooltip_lists_account_usages_and_earliest_resets():
    card = FloatingUsageCard()
    card.set_state(summarize_by_provider(two_group_accounts()))
    tooltip = card.toolTip()

    assert "Zhipu GLM" in tooltip
    assert "智谱1 57%" in tooltip
    assert "智谱2 26%" in tooltip
    assert "智谱10 5%" in tooltip
    assert "MiniMax主 4%" in tooltip
    # 各窗口最早重置时间倒计时。
    assert "5 小时 " in tooltip and "重置" in tooltip
    assert "每周 " in tooltip


def test_card_tooltip_skips_error_accounts():
    accounts = [
        make_account("智谱1", error="网络异常"),
        make_account("智谱2", used=26.0, weekly_used=None),
    ]
    card = FloatingUsageCard()
    card.set_state(summarize_by_provider(accounts))
    tooltip = card.toolTip()
    assert "智谱1" not in tooltip
    assert "智谱2 26%" in tooltip


def test_card_placeholder_states():
    card = FloatingUsageCard()
    card.set_placeholder("正在更新额度")
    assert card._placeholder_label.text() == "正在更新额度"
    assert card.toolTip() == "正在更新额度"
    assert not card.grab().isNull()

    card.set_placeholder("暂无可用账号")
    assert card._placeholder_label.text() == "暂无可用账号"
    assert card.toolTip() == "暂无可用账号"


def test_card_click_drag_release_signals():
    card = FloatingUsageCard()
    card.show()

    def mouse_event(event_type, button, local):
        return QMouseEvent(
            event_type,
            QPointF(local),
            QPointF(card.mapToGlobal(local)),
            button,
            button,
            Qt.KeyboardModifier.NoModifier,
        )

    pressed: list[QPoint] = []
    card.pressed.connect(pressed.append)
    card.mousePressEvent(
        mouse_event(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton, QPoint(10, 8))
    )
    assert len(pressed) == 1

    moved: list[QPoint] = []
    released: list[QPoint] = []
    card.dragged.connect(moved.append)
    card.released.connect(released.append)
    card.mouseMoveEvent(
        mouse_event(QEvent.Type.MouseMove, Qt.MouseButton.LeftButton, QPoint(24, 12))
    )
    card.mouseReleaseEvent(
        mouse_event(
            QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton, QPoint(24, 12)
        )
    )
    assert len(moved) == 1
    assert len(released) == 1
    card.hide()


def test_card_has_no_wheel_resize_and_stays_fixed_width():
    """缩放调 Interaction 已按规格去除：卡片不得再暴露 resize_requested。"""

    card = FloatingUsageCard()
    assert not hasattr(card, "resize_requested")
    width = card.width()
    card.set_state(summarize_by_provider(two_group_accounts()))
    card.set_placeholder("暂无可用账号")
    card.set_state(summarize_by_provider(two_group_accounts()))
    assert card.width() == width == FLOAT_CARD_WIDTH
