"""Default configuration values and field metadata."""

from __future__ import annotations

from typing import Any

SECRET_KEYS = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_AUTH",
    "DEEPSEEK_COOKIE",
    "MIMO_COOKIE",
    "MIMO_API_PLATFORM_PH",
    "MIMO_API_KEY",
    "NAYUTO_AUTH",
    "ZHIPU_TOKEN",
    "MINIMAX_TOKEN",
)
# 多账号 token 按下标存键（ZHIPU_TOKEN_0…），前缀命中即视为秘密。
SECRET_KEY_PREFIXES = ("ZHIPU_TOKEN", "MINIMAX_TOKEN")
# 面板只展示这些 provider 的账号；后续接入新厂商改这一处即可。
UI_PROVIDER_WHITELIST = ("zhipu", "minimax")


def is_secret_key(key: str) -> bool:
    """旧精确键与序号化账号 token 键统一走前缀判定。"""

    if key in SECRET_KEYS:
        return True
    return any(key.startswith(prefix) for prefix in SECRET_KEY_PREFIXES)
OFFICIAL_HOSTS = {
    "platform.deepseek.com",
    "api.deepseek.com",
    "platform.xiaomimimo.com",
    "nayutoai.xyz",
    "open.bigmodel.cn",
    "api.z.ai",
    "api.minimaxi.com",
    "api.minimax.io",
}
DEFAULT_CONFIG: dict[str, Any] = {
    "DEEPSEEK_API_KEY": "",
    "DEEPSEEK_AUTH": "",
    "DEEPSEEK_COOKIE": "",
    "DEEPSEEK_BASE": "https://platform.deepseek.com",
    "DEEPSEEK_PEAK_PRICING_ENABLED": False,
    "DEEPSEEK_PEAK_PERIOD_1_START": "09:00",
    "DEEPSEEK_PEAK_PERIOD_1_END": "12:00",
    "DEEPSEEK_PEAK_PERIOD_2_START": "14:00",
    "DEEPSEEK_PEAK_PERIOD_2_END": "18:00",
    "MIMO_COOKIE": "",
    "MIMO_API_PLATFORM_PH": "",
    "MIMO_API_KEY": "",
    "MIMO_BASE": "https://platform.xiaomimimo.com",
    "NAYUTO_AUTH": "",
    "NAYUTO_BASE": "https://nayutoai.xyz",
    "ZHIPU_TOKEN": "",
    "ZHIPU_BASE": "https://open.bigmodel.cn",
    "ZHIPU_ACCOUNTS": [],
    "MINIMAX_TOKEN": "",
    "MINIMAX_BASE": "https://api.minimaxi.com",
    "MINIMAX_ACCOUNTS": [],
    "CODEX_HOME": "",
    "CURSOR_GLOBAL_STORAGE": "",
    "REFRESH_INTERVAL": 60_000,
    "WIDGET_COMPACT_SIZE": 88,
    "WIDGET_EXPANDED_SIZE": (820, 564),
    "BG_COLOR": "#071427",
    "ACCENT_COLOR": "#2f6fe4",
    "TEXT_COLOR": "#edf4ff",
    "ACTIVE_PROVIDER": "deepseek",
    "BACKGROUND_PROVIDER_IDS": [],
    "EDGE_HIDE_ENABLED": True,
    "VPET_ENABLED": False,
    "PANEL_AUTO_COLLAPSE_ON_DEACTIVATE": True,
    "AUTO_START_ENABLED": False,
    "UI_THEME": "dark",
    "UI_LANGUAGE": "system",
    "UI_SYNC_ACCENT_COLOR": True,
    "UI_LIGHT_ACCENT_COLOR": "#2F72E8",
    "UI_DARK_ACCENT_COLOR": "#3478F6",
    "UI_CUSTOM_COLORS": [],
    "UI_LIGHT_PANEL_OPACITY": 100,
    "UI_DARK_PANEL_OPACITY": 100,
    "UPDATE_AUTO_CHECK_ENABLED": True,
    "UPDATE_CHANNEL": "stable",
    "UPDATE_SKIPPED_VERSION": "",
    "MINUTE_USAGE_CHART_TYPE": "bar",
    "MINUTE_USAGE_INTERVAL_MINUTES": 5,
    "MINUTE_USAGE_RETENTION_DAYS": 3,
}
FIELD_META: dict[str, dict[str, Any]] = {
    **{key: {"kind": "text", "secret": key in SECRET_KEYS} for key in DEFAULT_CONFIG},
    "REFRESH_INTERVAL": {"kind": "int", "min": 5_000},
    "DEEPSEEK_PEAK_PRICING_ENABLED": {"kind": "bool"},
    "DEEPSEEK_PEAK_PERIOD_1_START": {"kind": "time"},
    "DEEPSEEK_PEAK_PERIOD_1_END": {"kind": "time"},
    "DEEPSEEK_PEAK_PERIOD_2_START": {"kind": "time"},
    "DEEPSEEK_PEAK_PERIOD_2_END": {"kind": "time"},
    "WIDGET_COMPACT_SIZE": {"kind": "int", "min": 88, "max": 124},
    "WIDGET_EXPANDED_SIZE": {"kind": "tuple_int"},
    "BG_COLOR": {"kind": "color"},
    "ACCENT_COLOR": {"kind": "color"},
    "TEXT_COLOR": {"kind": "color"},
    "EDGE_HIDE_ENABLED": {"kind": "bool"},
    "VPET_ENABLED": {"kind": "bool"},
    "PANEL_AUTO_COLLAPSE_ON_DEACTIVATE": {"kind": "bool"},
    "AUTO_START_ENABLED": {"kind": "bool"},
    "BACKGROUND_PROVIDER_IDS": {
        "kind": "provider_list",
        "choices": ("deepseek", "mimo", "codex", "cursor", "nayuto", "zhipu", "minimax"),
    },
    "UI_THEME": {"kind": "choice", "choices": ("system", "light", "dark")},
    "UI_LANGUAGE": {
        "kind": "choice", "choices": ("system", "zh-cn", "zh-tw", "en", "ja", "ko"),
    },
    "UI_LIGHT_ACCENT_COLOR": {"kind": "color"},
    "UI_SYNC_ACCENT_COLOR": {"kind": "bool"},
    "UI_DARK_ACCENT_COLOR": {"kind": "color"},
    "UI_CUSTOM_COLORS": {"kind": "color_list"},
    "UI_LIGHT_PANEL_OPACITY": {"kind": "int", "min": 70, "max": 100},
    "UI_DARK_PANEL_OPACITY": {"kind": "int", "min": 70, "max": 100},
    "UPDATE_AUTO_CHECK_ENABLED": {"kind": "bool"},
    "ZHIPU_ACCOUNTS": {"kind": "account_list"},
    "MINIMAX_ACCOUNTS": {"kind": "account_list"},
    "MINUTE_USAGE_CHART_TYPE": {"kind": "choice", "choices": ("bar", "line")},
    "MINUTE_USAGE_INTERVAL_MINUTES": {"kind": "int", "min": 1, "max": 60},
    "MINUTE_USAGE_RETENTION_DAYS": {"kind": "int", "min": 1, "max": 365},
}

__all__ = [
    "DEFAULT_CONFIG",
    "FIELD_META",
    "OFFICIAL_HOSTS",
    "SECRET_KEYS",
    "SECRET_KEY_PREFIXES",
    "UI_PROVIDER_WHITELIST",
    "is_secret_key",
]
