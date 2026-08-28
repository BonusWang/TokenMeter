"""智谱 GLM Coding Plan 订阅额度 provider。"""

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

_ZHIPU_BASE = "https://open.bigmodel.cn"
_QUOTA_PATH = "/api/monitor/usage/quota/limit"
_REQUEST_TIMEOUT_SECONDS = 15
# unit=3 对应 5 小时窗，unit=6 对应周窗；映射与 cc-switch 的智谱适配一致。
# 列表顺序即展示顺序：5 小时窗必须在前，悬浮球只读第一个窗口。
_UNIT_SLOTS = {
    3: ("five_hour", "5小时", 300),
    6: ("weekly", "7天", 10_080),
}
_FALLBACK_SLOTS = (
    ("five_hour", "5小时", 300),
    ("weekly", "7天", 10_080),
)


def _reset_milliseconds(value: Any) -> int | None:
    try:
        milliseconds = int(value)
    except (TypeError, ValueError):
        return None
    return milliseconds if milliseconds > 0 else None


class ZhipuProvider(Provider):
    id = "zhipu"
    name = "Zhipu GLM"
    default_currency = "CNY"
    default_base = _ZHIPU_BASE
    official_api_hosts = {"open.bigmodel.cn", "api.z.ai"}
    supports_subscription_quota = True
    credential_fields = {
        "TOKEN": {
            "label": "API Key",
            "secret": True,
            "hint": "智谱开放平台 API Key，用于查询 Coding Plan 用量",
        },
        "BASE": {
            "label": "平台地址",
            "secret": False,
            "optional": True,
            "hint": "默认 https://open.bigmodel.cn；国际站填 https://api.z.ai",
        },
    }

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        super().__init__(config)
        self._session = build_session()

    def close(self) -> None:
        self._session.close()

    def _token(self) -> str:
        return str(self.config_get("ZHIPU_TOKEN", "")).strip()

    def _base_url(self) -> str:
        configured = str(self.config_get("ZHIPU_BASE", "")).strip().rstrip("/")
        return configured or self.default_base

    def snapshot_identity(self) -> str:
        token = self._token()
        # 快照只保存不可逆指纹，避免把 API Key 写入缓存数据库。
        return hashlib.sha256(f"zhipu:token:{token}".encode()).hexdigest() if token else ""

    @staticmethod
    def _error(code: str, status_code: int | None = None) -> FetchError:
        messages = {
            "NOT_CONFIGURED": "未配置 Zhipu GLM API Key",
            "AUTH_EXPIRED": "Zhipu GLM API Key 已失效，请在设置中更新",
            "RATE_LIMITED": "Zhipu GLM 请求过于频繁，请稍后重试",
            "NETWORK_TIMEOUT": "连接 Zhipu GLM 额度服务超时",
            "NETWORK_ERROR": "无法连接 Zhipu GLM 额度服务",
            "SERVER_ERROR": "Zhipu GLM 额度服务返回 HTTP "
            + (str(status_code) if status_code is not None else "错误"),
            "INVALID_RESPONSE": "Zhipu GLM 额度数据结构已变化",
        }
        return FetchError(code, "Zhipu GLM 订阅额度", messages[code])

    @staticmethod
    def _reset_at(value: Any) -> datetime | None:
        milliseconds = _reset_milliseconds(value)
        if milliseconds is None:
            return None
        # nextResetTime 是毫秒时间戳，按本机时区展示。
        return datetime.fromtimestamp(milliseconds / 1000).astimezone()

    @classmethod
    def _window(
        cls, item: Mapping[str, Any], identifier: str, title: str, window_minutes: int
    ) -> QuotaWindow | None:
        if not isinstance(item, Mapping):
            return None
        try:
            used = float(item["percentage"])
        except (KeyError, TypeError, ValueError):
            return None
        return QuotaWindow(
            identifier,
            title,
            max(0.0, min(100.0, used)),
            resets_at=cls._reset_at(item.get("nextResetTime")),
            window_minutes=window_minutes,
        )

    @classmethod
    def _windows(cls, limits: Any) -> tuple[QuotaWindow, ...]:
        if not isinstance(limits, list):
            return ()
        slots: dict[str, QuotaWindow | None] = {"five_hour": None, "weekly": None}
        fallback: list[tuple[int, int, Mapping[str, Any]]] = []
        for item in limits:
            if not isinstance(item, Mapping):
                continue
            kind = str(item.get("type") or "").strip().upper()
            if kind not in ("TOKENS_LIMIT", "CREDIT_LIMIT"):
                # TIME_LIMIT 是请求次数限制，不代表额度，不参与窗口展示。
                continue
            unit = item.get("unit")
            definition = _UNIT_SLOTS.get(unit) if isinstance(unit, int) else None
            if definition is not None:
                identifier, title, window_minutes = definition
                if slots[identifier] is None:
                    slots[identifier] = cls._window(
                        item, identifier, title, window_minutes
                    )
                continue
            reset = _reset_milliseconds(item.get("nextResetTime"))
            # 无重置时间的条目排最前（优先补 5 小时窗），其余按重置时间升序。
            fallback.append((0 if reset is None else 1, reset or 0, item))
        if fallback:
            fallback.sort(key=lambda entry: (entry[0], entry[1]))
            for _rank, _reset, item in fallback:
                for identifier, title, window_minutes in _FALLBACK_SLOTS:
                    if slots[identifier] is None:
                        slots[identifier] = cls._window(
                            item, identifier, title, window_minutes
                        )
                        break
        return tuple(
            window for window in (slots["five_hour"], slots["weekly"]) if window is not None
        )

    def fetch_quota(self) -> tuple[ProviderQuota | None, FetchError | None]:
        token = self._token()
        if not token:
            return None, self._error("NOT_CONFIGURED")
        try:
            response = self._session.get(
                f"{self._base_url()}{_QUOTA_PATH}",
                headers={
                    # 智谱监控接口直接使用裸 API Key，不加 Bearer 前缀。
                    "Authorization": token,
                    "Content-Type": "application/json",
                    "Accept-Language": "en-US,en",
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
        if payload.get("success") is not True:
            # 业务失败时 msg 是服务端文案，原样透传便于排查。
            message = str(payload.get("msg") or "").strip() or "智谱额度查询失败"
            return None, FetchError("API_ERROR", "Zhipu GLM 订阅额度", message)
        data = payload.get("data")
        limits = data.get("limits") if isinstance(data, dict) else None
        windows = self._windows(limits)
        if not windows:
            return None, self._error("INVALID_RESPONSE")
        plan = str(data.get("level") or "").strip() if isinstance(data, dict) else ""
        return ProviderQuota(windows=windows, plan=plan), None


__all__ = ["ZhipuProvider"]
