"""MiniMax Coding Plan 订阅额度 provider。"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import requests

from api.providers.base import (
    FetchError,
    Provider,
    ProviderQuota,
    QuotaWindow,
    build_session,
)

_MINIMAX_BASE = "https://api.minimaxi.com"
_REMAINS_PATH = "/v1/api/openplatform/coding_plan/remains"
_REQUEST_TIMEOUT_SECONDS = 15
_FIVE_HOURS_MINUTES = 300
_WEEKLY_MINUTES = 10_080


def _reset_at(value: Any) -> datetime | None:
    try:
        milliseconds = int(value)
    except (TypeError, ValueError):
        return None
    if milliseconds <= 0:
        return None
    # end_time / weekly_end_time 是毫秒时间戳，按本机时区展示。
    return datetime.fromtimestamp(milliseconds / 1000).astimezone()


def _used_percent(remaining: Any) -> float | None:
    try:
        value = 100.0 - float(remaining)
    except (TypeError, ValueError):
        return None
    # 接口返回的是剩余百分比；换算成已用百分比并夹紧到 0-100。
    return max(0.0, min(100.0, value))


class MiniMaxProvider(Provider):
    id = "minimax"
    name = "MiniMax"
    default_currency = "CNY"
    default_base = _MINIMAX_BASE
    official_api_hosts = {"api.minimaxi.com", "api.minimax.io"}
    supports_subscription_quota = True
    credential_fields = {
        "TOKEN": {
            "label": "API Key",
            "secret": True,
            "hint": "MiniMax 开放平台 API Key，用于查询 Coding Plan 用量",
        },
        "BASE": {
            "label": "平台地址",
            "secret": False,
            "optional": True,
            "hint": "默认 https://api.minimaxi.com；国际站填 https://api.minimax.io",
        },
    }

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        super().__init__(config)
        self._session = build_session()

    def close(self) -> None:
        self._session.close()

    def _token(self) -> str:
        return str(self.config_get("MINIMAX_TOKEN", "")).strip()

    def _base_url(self) -> str:
        configured = str(self.config_get("MINIMAX_BASE", "")).strip().rstrip("/")
        return configured or self.default_base

    def snapshot_identity(self) -> str:
        token = self._token()
        # 快照只保存不可逆指纹，避免把 API Key 写入缓存数据库。
        return hashlib.sha256(f"minimax:token:{token}".encode()).hexdigest() if token else ""

    @staticmethod
    def _error(code: str, status_code: int | None = None) -> FetchError:
        messages = {
            "NOT_CONFIGURED": "未配置 MiniMax API Key",
            "AUTH_EXPIRED": "MiniMax API Key 已失效，请在设置中更新",
            "RATE_LIMITED": "MiniMax 请求过于频繁，请稍后重试",
            "NETWORK_TIMEOUT": "连接 MiniMax 额度服务超时",
            "NETWORK_ERROR": "无法连接 MiniMax 额度服务",
            "SERVER_ERROR": "MiniMax 额度服务返回 HTTP "
            + (str(status_code) if status_code is not None else "错误"),
            "INVALID_RESPONSE": "MiniMax 额度数据结构已变化",
        }
        return FetchError(code, "MiniMax 订阅额度", messages[code])

    @staticmethod
    def _general_row(model_remains: Any) -> Mapping[str, Any] | None:
        if not isinstance(model_remains, list):
            return None
        for item in model_remains:
            if isinstance(item, Mapping) and item.get("model_name") == "general":
                return item
        return None

    @classmethod
    def _windows(cls, row: Mapping[str, Any]) -> tuple[QuotaWindow, ...]:
        windows: list[QuotaWindow] = []
        interval_used = _used_percent(row.get("current_interval_remaining_percent"))
        if interval_used is not None:
            windows.append(
                QuotaWindow(
                    "five_hour",
                    "5小时",
                    interval_used,
                    resets_at=_reset_at(row.get("end_time")),
                    window_minutes=_FIVE_HOURS_MINUTES,
                )
            )
        # current_weekly_status==1 才有周限额；3 等其他值表示无周限额，跳过。
        if row.get("current_weekly_status") == 1:
            weekly_used = _used_percent(row.get("current_weekly_remaining_percent"))
            if weekly_used is not None:
                windows.append(
                    QuotaWindow(
                        "weekly",
                        "7天",
                        weekly_used,
                        resets_at=_reset_at(row.get("weekly_end_time")),
                        window_minutes=_WEEKLY_MINUTES,
                    )
                )
        # 悬浮球只读第一个窗口，5 小时窗必须排在周窗之前。
        return tuple(windows)

    def fetch_quota(self) -> tuple[ProviderQuota | None, FetchError | None]:
        token = self._token()
        if not token:
            return None, self._error("NOT_CONFIGURED")
        try:
            response = self._session.get(
                f"{self._base_url()}{_REMAINS_PATH}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
        except requests.Timeout:
            return None, self._error("NETWORK_TIMEOUT")
        except requests.RequestException:
            return None, self._error("NETWORK_ERROR")
        if response.status_code in (401, 403):
            return None, self._error("AUTH_EXPIRED")
        if response.status_code == 429:
            return None, self._error("RATE_LIMITED")
        if not response.ok:
            return None, self._error("SERVER_ERROR", response.status_code)
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError
        except (requests.JSONDecodeError, ValueError):
            return None, self._error("INVALID_RESPONSE")
        base_resp = payload.get("base_resp")
        status_code = base_resp.get("status_code") if isinstance(base_resp, Mapping) else None
        if status_code != 0:
            message = (
                str(base_resp.get("status_msg") or "").strip() if isinstance(base_resp, Mapping) else ""
            ) or "MiniMax 额度查询失败"
            return None, FetchError("API_ERROR", "MiniMax 订阅额度", message)
        row = self._general_row(payload.get("model_remains"))
        if row is None:
            return None, self._error("INVALID_RESPONSE")
        windows = self._windows(row)
        if not windows:
            return None, self._error("INVALID_RESPONSE")
        return ProviderQuota(windows=windows), None


__all__ = ["MiniMaxProvider"]
