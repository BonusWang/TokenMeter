from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest
import requests

from api.providers.base import QuotaWindow
from api.providers.zhipu import ZhipuProvider

# 2026-08-28 实测的智谱 GLM Coding Plan 响应样本（脱敏，无真实凭据）。
SAMPLE_LIMITS = [
    {"type": "TIME_LIMIT", "unit": 5, "number": 1, "percentage": 0, "nextResetTime": 1790560834999},
    {"type": "TOKENS_LIMIT", "unit": 3, "number": 5, "percentage": 28, "nextResetTime": 1787918399836},
    {"type": "TOKENS_LIMIT", "unit": 6, "number": 1, "percentage": 29, "nextResetTime": 1787939363998},
]


def response(payload: dict, status_code: int = 200) -> Mock:
    result = Mock()
    result.status_code = status_code
    result.ok = 200 <= status_code < 400
    result.json.return_value = payload
    return result


def provider(**overrides) -> ZhipuProvider:
    values = {
        "ZHIPU_TOKEN": "synthetic-zhipu-key",
        "ZHIPU_BASE": "https://open.bigmodel.cn",
    }
    values.update(overrides)
    return ZhipuProvider(values)


def quota_payload(limits: list[dict], *, level: str = "max") -> dict:
    return {"success": True, "data": {"level": level, "limits": limits}}


def local_reset(milliseconds: int) -> datetime:
    # nextResetTime 是毫秒时间戳，实现按本地时区展示；测试用同一口径构造期望值。
    return datetime.fromtimestamp(milliseconds / 1000).astimezone()


def fetch_with(provider_instance: ZhipuProvider, payload: dict, status_code: int = 200):
    provider_instance._session.get = Mock(
        return_value=response(payload, status_code)
    )
    try:
        return provider_instance.fetch_quota()
    finally:
        provider_instance.close()


def test_real_shape_maps_five_hour_then_weekly_windows():
    quota, error = fetch_with(provider(), quota_payload(SAMPLE_LIMITS))

    assert error is None
    assert quota.plan == "max"
    assert [(window.id, window.title, window.window_minutes) for window in quota.windows] == [
        ("five_hour", "5小时", 300),
        ("weekly", "7天", 10_080),
    ]
    assert quota.windows[0].used_percent == 28
    assert quota.windows[0].resets_at == local_reset(1_787_918_399_836)
    assert quota.windows[1].used_percent == 29
    assert quota.windows[1].resets_at == local_reset(1_787_939_363_998)


def test_request_uses_bare_token_and_official_endpoint():
    instance = provider()
    instance._session.get = Mock(return_value=response(quota_payload(SAMPLE_LIMITS)))
    try:
        instance.fetch_quota()
    finally:
        instance.close()

    call = instance._session.get.call_args
    assert call.args[0] == "https://open.bigmodel.cn/api/monitor/usage/quota/limit"
    assert call.kwargs["headers"]["Authorization"] == "synthetic-zhipu-key"
    assert call.kwargs["headers"]["Content-Type"] == "application/json"
    assert call.kwargs["headers"]["Accept-Language"] == "en-US,en"
    assert call.kwargs["timeout"] == 15


def test_custom_and_default_base_urls():
    quota, error = fetch_with(
        provider(ZHIPU_BASE="https://api.z.ai/"), quota_payload(SAMPLE_LIMITS)
    )
    assert error is None
    assert quota.windows

    instance = provider(ZHIPU_BASE="")
    instance._session.get = Mock(return_value=response(quota_payload(SAMPLE_LIMITS)))
    try:
        instance.fetch_quota()
        assert (
            instance._session.get.call_args.args[0]
            == "https://open.bigmodel.cn/api/monitor/usage/quota/limit"
        )
    finally:
        instance.close()


def test_old_plan_single_limit_keeps_only_five_hour_window():
    limits = [
        {"type": "TOKENS_LIMIT", "unit": 3, "number": 5, "percentage": 40, "nextResetTime": 1787918399836},
    ]
    quota, error = fetch_with(provider(), quota_payload(limits))

    assert error is None
    assert [window.id for window in quota.windows] == ["five_hour"]
    assert quota.windows[0].used_percent == 40


def test_credit_limit_type_matches_case_insensitively():
    limits = [
        {"type": "credit_limit", "unit": 3, "percentage": 11, "nextResetTime": 1787918399836},
        {"type": "CREDIT_LIMIT", "unit": 6, "percentage": 22, "nextResetTime": 1787939363998},
    ]
    quota, error = fetch_with(provider(), quota_payload(limits))

    assert error is None
    assert [window.used_percent for window in quota.windows] == [11, 22]


def test_missing_unit_without_reset_prefers_five_hour_and_ascending_reset_fills_weekly():
    limits = [
        {"type": "TOKENS_LIMIT", "percentage": 20, "nextResetTime": 1787939363998},
        {"type": "TOKENS_LIMIT", "percentage": 30},
        {"type": "TOKENS_LIMIT", "percentage": 10, "nextResetTime": 1787918399836},
    ]
    quota, error = fetch_with(provider(), quota_payload(limits))

    assert error is None
    assert [window.id for window in quota.windows] == ["five_hour", "weekly"]
    # 无重置时间的条目优先补 5 小时窗，其余按重置时间升序填入空缺窗口。
    assert quota.windows[0].used_percent == 30
    assert quota.windows[0].resets_at is None
    assert quota.windows[1].used_percent == 10
    assert quota.windows[1].resets_at == local_reset(1_787_918_399_836)


def test_missing_unit_ascending_reset_fills_five_hour_first():
    limits = [
        {"type": "TOKENS_LIMIT", "percentage": 10, "nextResetTime": 1787939363998},
        {"type": "TOKENS_LIMIT", "percentage": 20, "nextResetTime": 1787918399836},
    ]
    quota, error = fetch_with(provider(), quota_payload(limits))

    assert error is None
    assert [(window.id, window.used_percent) for window in quota.windows] == [
        ("five_hour", 20),
        ("weekly", 10),
    ]


def test_unknown_unit_fills_only_empty_slots():
    limits = [
        {"type": "TOKENS_LIMIT", "unit": 6, "percentage": 50, "nextResetTime": 1787939363998},
        {"type": "TOKENS_LIMIT", "percentage": 15, "nextResetTime": 1787918399836},
    ]
    quota, error = fetch_with(provider(), quota_payload(limits))

    assert error is None
    assert [(window.id, window.used_percent) for window in quota.windows] == [
        ("five_hour", 15),
        ("weekly", 50),
    ]


def test_percentage_out_of_range_is_clamped():
    limits = [
        {"type": "TOKENS_LIMIT", "unit": 3, "percentage": 150, "nextResetTime": 1787918399836},
        {"type": "TOKENS_LIMIT", "unit": 6, "percentage": -5, "nextResetTime": 1787939363998},
    ]
    quota, error = fetch_with(provider(), quota_payload(limits))

    assert error is None
    assert [window.used_percent for window in quota.windows] == [100.0, 0.0]


def test_business_error_returns_server_message():
    quota, error = fetch_with(provider(), {"success": False, "msg": "token invalid"})

    assert quota is None
    assert error.code == "API_ERROR"
    assert "token invalid" in error.message


def test_http_failures_map_to_stable_error_codes():
    cases = (
        (401, "AUTH_EXPIRED"),
        (403, "AUTH_EXPIRED"),
        (429, "RATE_LIMITED"),
        (500, "SERVER_ERROR"),
    )
    for status_code, expected_code in cases:
        quota, error = fetch_with(provider(), {}, status_code)
        assert quota is None, status_code
        assert error.code == expected_code, status_code
        assert "synthetic-zhipu-key" not in error.message


def test_network_failures_keep_fixed_messages():
    for raised, expected_code in (
        (requests.Timeout(), "NETWORK_TIMEOUT"),
        (requests.ConnectionError(), "NETWORK_ERROR"),
    ):
        instance = provider()
        instance._session.get = Mock(side_effect=raised)
        try:
            quota, error = instance.fetch_quota()
        finally:
            instance.close()
        assert quota is None
        assert error.code == expected_code


def test_invalid_json_and_unusable_payload_are_rejected():
    invalid = response({"success": True, "data": {}})
    invalid.json.side_effect = ValueError("not json")
    instance = provider()
    instance._session.get = Mock(return_value=invalid)
    try:
        quota, error = instance.fetch_quota()
    finally:
        instance.close()
    assert quota is None
    assert error.code == "INVALID_RESPONSE"

    quota, error = fetch_with(provider(), {"success": True, "data": {"level": "max", "limits": []}})
    assert quota is None
    assert error.code == "INVALID_RESPONSE"


def test_missing_token_returns_not_configured_without_request():
    instance = ZhipuProvider({"ZHIPU_TOKEN": ""})
    instance._session.get = Mock()
    try:
        quota, error = instance.fetch_quota()
    finally:
        instance.close()

    assert quota is None
    assert error.code == "NOT_CONFIGURED"
    instance._session.get.assert_not_called()


def test_token_alone_marks_provider_configured():
    assert ZhipuProvider({"ZHIPU_TOKEN": "synthetic"}).is_configured() is True
    assert ZhipuProvider({"ZHIPU_BASE": "https://api.z.ai"}).is_configured() is False


def test_snapshot_identity_is_stable_and_non_secret():
    first = provider()
    second = provider(ZHIPU_TOKEN="another-synthetic")
    try:
        identity = first.snapshot_identity()
        assert identity == first.snapshot_identity()
        assert len(identity) == 64
        assert "synthetic-zhipu-key" not in identity
        assert identity != second.snapshot_identity()
    finally:
        first.close()
        second.close()


def test_non_quota_fetchers_stay_empty_like_codex():
    instance = provider()
    try:
        assert instance.fetch_balance() == (None, None)
        assert instance.fetch_summary() == (None, None)
        assert instance.fetch_payloads([(8, 2026)]) == ([], [])
    finally:
        instance.close()


def test_zhipu_token_is_excluded_from_public_config():
    from config.defaults import SECRET_KEYS
    from config.store import public_values

    assert "ZHIPU_TOKEN" in SECRET_KEYS
    exported = public_values(
        {"ZHIPU_TOKEN": "synthetic", "ZHIPU_BASE": "https://open.bigmodel.cn"}
    )
    assert "ZHIPU_TOKEN" not in exported
    assert exported["ZHIPU_BASE"] == "https://open.bigmodel.cn"


def test_window_order_feeds_floating_ball_first():
    # 悬浮球只读第一个窗口；5 小时窗必须排在周窗之前。
    quota, _error = fetch_with(provider(), quota_payload(SAMPLE_LIMITS))
    assert isinstance(quota.windows[0], QuotaWindow)
    assert quota.windows[0].window_minutes == 300
