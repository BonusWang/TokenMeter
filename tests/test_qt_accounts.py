"""多账号面板 UI 测试：账号卡片渲染、错误态、白名单与进度条水位颜色。"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QWidget

from api.aggregator import AccountQuota
from api.providers.base import QuotaWindow
from ui.formatting import format_weekly_reset_date
from ui.qt_ball import FloatingUsageBall
from ui.qt_float_card import FloatingUsageCard
from ui.qt_panel import AccountCard, MainPanel
from ui.qt_theme import current_theme

APP = QApplication.instance() or QApplication([])

# 哨兵默认值：显式传 resets_at=None 表示“无重置时间”，与不传区分开。
_DEFAULT_RESET = object()


def make_account(
    label: str = "智谱1",
    provider_id: str = "zhipu",
    provider_name: str = "Zhipu GLM",
    used: float = 57.0,
    weekly_used: float | None = 10.0,
    plan: str = "max",
    error: str = "",
    resets_at=_DEFAULT_RESET,
) -> AccountQuota:
    windows: tuple[QuotaWindow, ...] = ()
    if not error:
        five_hour = QuotaWindow(
            "five_hour",
            "5小时",
            used,
            resets_at=(
                datetime.now() + timedelta(hours=1, minutes=49)
                if resets_at is _DEFAULT_RESET
                else resets_at
            ),
            window_minutes=300,
        )
        parts = [five_hour]
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
        plan=plan,
        windows=windows,
        error=error,
    )


def test_weekly_reset_date_format():
    reset = datetime(2026, 9, 4, 8, 0)
    assert format_weekly_reset_date(reset) == "9月4日重置"
    assert format_weekly_reset_date(None) == "重置时间未知"


def test_panel_renders_one_card_per_account_in_whitelist_order():
    panel = MainPanel()
    accounts = [
        make_account("智谱1"),
        make_account("智谱2", used=26.0),
        make_account("智谱10", used=4.0),
        make_account("MiniMax主", provider_id="minimax", provider_name="MiniMax"),
    ]
    panel.set_accounts(accounts, refreshing=False, last_success=datetime.now())

    cards = panel._account_cards
    assert len(cards) == 4
    assert "智谱1" in cards[0]._title_label.text()
    assert "Zhipu GLM" in cards[0]._title_label.text()
    assert "MiniMax" in cards[3]._title_label.text()
    # 套餐徽章来自 quota.plan，空套餐不显示。
    assert cards[0]._plan_badge.text() == "max"
    no_plan = AccountCard(make_account("智谱3", plan=""))
    assert no_plan._plan_badge.isHidden()
    assert not cards[0]._plan_badge.isHidden()
    assert panel.updated_text.text().endswith("4 个账号")


def test_error_card_renders_summary_without_progress_bars():
    card = AccountCard(make_account("智谱9", error="无法连接 Zhipu GLM 额度服务"))
    assert not card._error_bar.isHidden()
    assert "无法连接" in card._error_label.text()
    assert not card._window_blocks


def test_progress_block_shows_remaining_percent_and_low_water_warning():
    theme = current_theme()
    normal = AccountCard(make_account("智谱1", used=57.0))
    block = normal._window_blocks["five_hour"]
    assert block.percent_label.text() == "43%"
    assert block.progress.ratio == 0.43
    assert block.progress.fill_color.name().upper() == QColorLike(theme.success)

    low = AccountCard(make_account("智谱2", used=85.0))
    low_block = low._window_blocks["five_hour"]
    assert low_block.percent_label.text() == "15%"
    assert low_block.progress.fill_color.name().upper() == QColorLike(theme.danger)


def QColorLike(value: str) -> str:
    from PySide6.QtGui import QColor

    return QColor(value).name().upper()


def test_weekly_block_uses_date_reset_text_and_five_hour_uses_countdown():
    card = AccountCard(make_account("智谱1", used=57.0))
    weekly = card._window_blocks["weekly"]
    assert "重置" in weekly.reset_label.text()
    assert "小时" in card._window_blocks["five_hour"].reset_label.text() or "分" in (
        card._window_blocks["five_hour"].reset_label.text()
    )


def test_window_without_reset_time_hides_reset_label():
    account = make_account("智谱1", used=30.0, resets_at=None)
    card = AccountCard(account)
    block = card._window_blocks["five_hour"]
    assert block.reset_label.isHidden()


def test_show_overview_keeps_provider_combo_hidden_in_accounts_mode():
    """白名单模式下从设置页返回概览，旧单账号快速切换下拉不得复活。"""

    panel = MainPanel()
    assert panel.provider_quick_combo.isHidden()
    settings = QWidget()
    for _ in range(2):
        panel.show_settings(settings)
        panel.show_overview()
        assert panel.provider_quick_combo.isHidden()


def test_widget_accounts_update_drives_card_groups():
    """白名单模式紧凑态是分组卡片：两组、徽章、聚合数值与 tooltip。"""

    from ui.qt_widget import FloatingWidget

    with patch("ui.qt_widget.FloatingWidget.refresh"):
        widget = FloatingWidget()
    widget._accounts = [
        make_account("智谱1", used=57.0),
        make_account("智谱2", used=26.0),
        make_account("MiniMax主", provider_id="minimax", provider_name="MiniMax", used=4.0, weekly_used=1.5),
    ]
    widget._accounts_last_success = datetime.now()
    widget._apply_accounts_update()

    assert isinstance(widget.ball, FloatingUsageCard)
    card = widget.ball
    assert len(card._sections) == 2
    zhipu = card._sections[0]
    # 5 小时跨 2 个智谱账号平均剩余 (43+74)/2=58.5→.0f 显示 58%。
    assert zhipu._rows["five_hour"]._percent_label.text() == "58%"
    assert zhipu._badge.text() == "2 账号"
    # 每周两个智谱账号均 90→90%；MiniMax 单账号一组 (96, 98.5→98%)。
    assert zhipu._rows["weekly"]._percent_label.text() == "90%"
    assert card._sections[1]._rows["five_hour"]._percent_label.text() == "96%"
    assert card._sections[1]._badge.text() == "1 账号"

    tooltip = card.toolTip()
    assert "Zhipu GLM" in tooltip
    assert "智谱1 57%" in tooltip
    assert "智谱2 26%" in tooltip
    assert "MiniMax主 4%" in tooltip
    assert "重置" in tooltip
    widget._closed = True
    widget.hide()


def test_widget_accounts_update_all_error_shows_unavailable_state():
    from ui.qt_widget import FloatingWidget

    with patch("ui.qt_widget.FloatingWidget.refresh"):
        widget = FloatingWidget()
    widget._accounts = [
        make_account("智谱1", error="网络异常"),
        make_account("MiniMax主", provider_id="minimax", provider_name="MiniMax", error="失效"),
    ]
    widget._apply_accounts_update()
    assert widget.ball._placeholder_label.text() == "暂无可用账号"
    assert widget.ball.toolTip() == "暂无可用账号"
    widget._closed = True
    widget.hide()


def test_widget_accounts_update_card_aggregates_not_single_account():
    """卡片必须显示分组聚合值，不是单个最紧张账号的数值（王总：43% 不对）。"""

    from ui.qt_widget import FloatingWidget

    with patch("ui.qt_widget.FloatingWidget.refresh"):
        widget = FloatingWidget()
    widget._accounts = [
        make_account("智谱1", used=50.0),
        make_account("智谱2", used=20.0, weekly_used=80.0),
    ]
    widget._accounts_last_success = datetime.now()
    widget._apply_accounts_update()

    # 旧实现取智谱2 每周（剩余 20）；聚合口径应为 5 小时 (50+80)/2=65、每周 (90+20)/2=55。
    card = widget.ball
    assert card._sections[0]._rows["five_hour"]._percent_label.text() == "65%"
    assert card._sections[0]._rows["weekly"]._percent_label.text() == "55%"
    widget._closed = True
    widget.hide()


def test_widget_accounts_update_resizes_compact_window_to_card():
    """紧凑窗口尺寸跟随卡片宽高，不再受球的方形尺寸约束。"""

    from ui.qt_widget import FloatingWidget

    with patch("ui.qt_widget.FloatingWidget.refresh"):
        widget = FloatingWidget()
    widget._accounts = [
        make_account("智谱1", used=57.0),
        make_account(
            "MiniMax主", provider_id="minimax", provider_name="MiniMax", used=4.0
        ),
    ]
    widget._accounts_last_success = datetime.now()
    widget._apply_accounts_update()

    card = widget.ball
    assert (widget.width(), widget.height()) == (card.width(), card.height())
    # 圆角矩形遮罩：中心在遮罩内、直角边角在外（与球的椭圆遮罩同样不含 (0,0)）。
    assert widget.mask().contains(card.rect().center())
    assert not widget.mask().contains(QPoint(0, 0))
    widget._closed = True
    widget.hide()


def test_whitelist_mode_replaces_ball_with_card_and_keeps_ball_for_legacy(monkeypatch):
    """白名单模式实例化卡片且不再实例化球；非白名单路径球不回归。"""

    import ui.qt_widget as qt_widget_module
    from ui.qt_widget import FloatingWidget

    with patch("ui.qt_widget.FloatingWidget.refresh"):
        widget = FloatingWidget()
    assert isinstance(widget.ball, FloatingUsageCard)
    assert not isinstance(widget.ball, FloatingUsageBall)
    widget._closed = True
    widget.hide()

    monkeypatch.setattr(qt_widget_module, "ACCOUNTS_MODE", False)
    with patch("ui.qt_widget.FloatingWidget.refresh"):
        legacy = FloatingWidget()
    assert isinstance(legacy.ball, FloatingUsageBall)
    legacy._closed = True
    legacy.hide()


def test_accounts_view_strings_registered_for_all_languages():
    """账号视图的状态与错误文案必须在全部语言目录登记，避免非中文界面回退中文。"""

    from ui.translations import MESSAGES

    strings = (
        "部分账号数据异常，显示可用数据",
        "无法连接 Zhipu GLM 额度服务",
        "连接 Zhipu GLM 额度服务超时",
        "Zhipu GLM 请求过于频繁，请稍后重试",
        "智谱额度查询失败",
        "无法连接 MiniMax 额度服务",
        "连接 MiniMax 额度服务超时",
        "MiniMax 请求过于频繁，请稍后重试",
        "MiniMax 额度查询失败",
    )
    for source in strings:
        entry = MESSAGES.get(source)
        assert isinstance(entry, tuple) and len(entry) == 4, source
        assert all(text.strip() for text in entry), source
