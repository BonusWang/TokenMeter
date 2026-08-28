from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import requests

from api.providers.minimax import MiniMaxProvider

# 2026-08-28 实测的 MiniMax Coding Plan 响应样本（脱敏，无真实凭据）。
SAMPLE_PAYLOAD = {
    "base_resp": {"status_code": 0, "status_msg": "success"},
    "model_remains": [
        {
            "model_name": "general",
            "current_interval_remaining_percent": 97,
            "end_time": 1787918400000,
            "current_weekly_status": 1,
            "current_weekly_remaining_percent": 95,
            "weekly_end_time": 1788105600000,
        }
    ],
}


def response(payload: dict, status_code: int = 200) -> Mock:
    result = Mock()
    result.status_code = status_code
    result.ok = 200 <= status_code < 400
    result.json.return_value = payload
    return result


def provider(**overrides) -> MiniMaxProvider:
    values = {
        "MINIMAX_TOKEN": "synthetic-minimax-key",
        "MINIMAX_BASE": "https://api.minimaxi.com",
    }
    values.update(overrides)
    return MiniMaxProvider(values)


def local_reset(milliseconds: int) -> datetime:
    return datetime.fromtimestamp(milliseconds / 1000).astimezone()


def fetch_with(provider_instance: MiniMaxProvider, payload: dict, status_code: int = 200):
    provider_instance._session.get = Mock(
        return_value=response(payload, status_code)
    )
    try:
        return provider_instance.fetch_quota()
    finally:
        provider_instance.close()


def test_real_shape_maps_remaining_percent_to_used_windows():
    quota, error = fetch_with(provider(), SAMPLE_PAYLOAD)

    assert error is None
    assert [(window.id, window.title, window.window_minutes) for window in quota.windows] == [
        ("five_hour", "5小时", 300),
        ("weekly", "7天", 10_080),
    ]
    assert quota.windows[0].used_percent == 3
    assert quota.windows[0].resets_at == local_reset(1_787_918_400_000)
    assert quota.windows[1].used_percent == 5
    assert quota.windows[1].resets_at == local_reset(1_788_105_600_000)


def test_request_uses_bearer_token_and_official_endpoint():
    instance = provider()
    instance._session.get = Mock(return_value=response(SAMPLE_PAYLOAD))
    try:
        instance.fetch_quota()
    finally:
        instance.close()

    call = instance._session.get.call_args
    assert call.args[0] == "https://api.minimaxi.com/v1/api/openplatform/coding_plan/remains"
    assert call.kwargs["headers"]["Authorization"] == "Bearer synthetic-minimax-key"
    assert call.kwargs["headers"]["Content-Type"] == "application/json"
    assert call.kwargs["timeout"] == 15


def test_custom_base_url_is_used():
    quota, error = fetch_with(
        provider(MINIMAX_BASE="https://api.minimax.io/"), SAMPLE_PAYLOAD
    )
    assert error is None
    assert quota.windows


def test_weekly_status_other_than_one_skips_weekly_window():
    payload = {
        "base_resp": {"status_code": 0, "status_msg": "success"},
        "model_remains": [
            {
                "model_name": "general",
                "current_interval_remaining_percent": 80,
                "end_time": 1787918400000,
                "current_weekly_status": 3,
                "current_weekly_remaining_percent": 90,
                "weekly_end_time": 1788105600000,
            }
        ],
    }
    quota, error = fetch_with(provider(), payload)

    assert error is None
    assert [window.id for window in quota.windows] == ["five_hour"]
    assert quota.windows[0].used_percent == 20


def test_non_general_models_are_skipped():
    payload = {
        "base_resp": {"status_code": 0, "status_msg": "success"},
        "model_remains": [
            {
                "model_name": "video",
                "current_interval_remaining_percent": 10,
                "end_time": 1787918400000,
            },
            SAMPLE_PAYLOAD["model_remains"][0],
        ],
    }
    quota, error = fetch_with(provider(), payload)

    assert error is None
    assert quota.windows[0].used_percent == 3


def test_used_percent_clamped_to_range():
    payload = {
        "base_resp": {"status_code": 0, "status_msg": "success"},
        "model_remains": [
            {
                "model_name": "general",
                "current_interval_remaining_percent": -5,
                "end_time": 1787918400000,
                "current_weekly_status": 1,
                "current_weekly_remaining_percent": 120,
                "weekly_end_time": 1788105600000,
            }
        ],
    }
    quota, error = fetch_with(provider(), payload)

    assert error is None
    assert [window.used_percent for window in quota.windows] == [100.0, 0.0]


def test_business_error_returns_status_msg():
    payload = {"base_resp": {"status_code": 1004, "status_msg": "invalid api token"}}
    quota, error = fetch_with(provider(), payload)

    assert quota is None
    assert error.code == "API_ERROR"
    assert "invalid api token" in error.message


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
        assert "synthetic-minimax-key" not in error.message


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


def test_invalid_json_and_missing_general_row_are_rejected():
    invalid = response(SAMPLE_PAYLOAD)
    invalid.json.side_effect = ValueError("not json")
    instance = provider()
    instance._session.get = Mock(return_value=invalid)
    try:
        quota, error = instance.fetch_quota()
    finally:
        instance.close()
    assert quota is None
    assert error.code == "INVALID_RESPONSE"

    payload = {"base_resp": {"status_code": 0, "status_msg": "success"}, "model_remains": []}
    quota, error = fetch_with(provider(), payload)
    assert quota is None
    assert error.code == "INVALID_RESPONSE"


def test_missing_token_returns_not_configured_without_request():
    instance = MiniMaxProvider({"MINIMAX_TOKEN": ""})
    instance._session.get = Mock()
    try:
        quota, error = instance.fetch_quota()
    finally:
        instance.close()

    assert quota is None
    assert error.code == "NOT_CONFIGURED"
    instance._session.get.assert_not_called()


def test_token_alone_marks_provider_configured():
    assert MiniMaxProvider({"MINIMAX_TOKEN": "synthetic"}).is_configured() is True
    assert MiniMaxProvider({"MINIMAX_BASE": "https://api.minimax.io"}).is_configured() is False


def test_snapshot_identity_is_stable_and_non_secret():
    first = provider()
    second = provider(MINIMAX_TOKEN="another-synthetic")
    try:
        identity = first.snapshot_identity()
        assert identity == first.snapshot_identity()
        assert len(identity) == 64
        assert "synthetic-minimax-key" not in identity
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


def test_minimax_token_is_excluded_from_public_config():
    from config.defaults import SECRET_KEYS
    from config.store import public_values

    assert "MINIMAX_TOKEN" in SECRET_KEYS
    exported = public_values(
        {"MINIMAX_TOKEN": "synthetic", "MINIMAX_BASE": "https://api.minimaxi.com"}
    )
    assert "MINIMAX_TOKEN" not in exported
    assert exported["MINIMAX_BASE"] == "https://api.minimaxi.com"
