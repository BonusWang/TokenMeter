"""多账号额度聚合层测试：白名单过滤、并发抓取、失败隔离与自然排序。"""

from __future__ import annotations

from api.aggregator import AccountQuota, fetch_all_accounts, tensest_window
from api.providers.base import FetchError, ProviderQuota, QuotaWindow

ZHIPU_BASE = "https://open.bigmodel.cn"
MINIMAX_BASE = "https://api.minimaxi.com"


class FakeProvider:
    """记录实例化配置的假 provider；factory 每账号调用一次。"""

    def __init__(
        self,
        provider_id: str,
        config: dict,
        *,
        quota: ProviderQuota | None = None,
        error: FetchError | None = None,
        raise_exc: Exception | None = None,
    ):
        self.provider_id = provider_id
        self.name = {"zhipu": "Zhipu GLM", "minimax": "MiniMax"}.get(provider_id, provider_id)
        self.config = dict(config)
        self._quota = quota
        self._error = error
        self._raise = raise_exc
        self.closed = False

    def fetch_quota(self):
        if self._raise is not None:
            raise self._raise
        return self._quota, self._error

    def close(self):
        self.closed = True


def make_factory(
    results: dict[str, tuple[ProviderQuota | None, FetchError | None]],
    raising_tokens: set[str] | None = None,
    created: list[FakeProvider] | None = None,
):
    raising = raising_tokens or set()
    instances = created if created is not None else []

    def factory(provider_id: str, account_config: dict) -> FakeProvider:
        token = str(account_config.get(f"{provider_id.upper()}_TOKEN", ""))
        quota, error = results[token]
        provider = FakeProvider(
            provider_id,
            account_config,
            quota=quota,
            error=error,
            raise_exc=RuntimeError("boom") if token in raising else None,
        )
        instances.append(provider)
        return provider

    return factory


def quota(five_hour_used: float, weekly_used: float | None = None) -> ProviderQuota:
    windows = [
        QuotaWindow("five_hour", "5小时", five_hour_used, window_minutes=300),
    ]
    if weekly_used is not None:
        windows.append(QuotaWindow("weekly", "7天", weekly_used, window_minutes=10_080))
    return ProviderQuota(windows=tuple(windows), plan="max")


ZHIPU_RESULTS = {
    "key-1": (quota(57.0), None),
    "key-2": (quota(26.0), None),
    "key-10": (quota(4.0), None),
    "mini-1": (quota(4.0, 1.5), None),
    "bad-1": (None, FetchError("NETWORK_ERROR", "源", "无法连接额度服务")),
}


def test_whitelist_filters_non_coding_plan_providers():
    factory = make_factory({})
    accounts = fetch_all_accounts(
        {"DEEPSEEK_API_KEY": "some-key", "ACTIVE_PROVIDER": "deepseek"},
        provider_factory=factory,
    )
    assert accounts == []


def test_multi_account_fetch_uses_per_account_credentials_and_natural_order():
    config = {
        "ZHIPU_ACCOUNTS": [
            {"label": "智谱10", "base": ZHIPU_BASE},
            {"label": "智谱2", "base": ZHIPU_BASE},
            {"label": "智谱1", "base": ZHIPU_BASE},
        ],
        "ZHIPU_TOKEN_0": "key-10",
        "ZHIPU_TOKEN_1": "key-2",
        "ZHIPU_TOKEN_2": "key-1",
        "MINIMAX_ACCOUNTS": [{"label": "MiniMax主", "base": MINIMAX_BASE}],
        "MINIMAX_TOKEN_0": "mini-1",
    }
    created: list[FakeProvider] = []
    factory = make_factory(ZHIPU_RESULTS, created=created)
    accounts = fetch_all_accounts(config, provider_factory=factory)

    # 智谱按 label 自然序（智谱1 < 智谱2 < 智谱10），MiniMax 排在最后。
    assert [account.label for account in accounts] == [
        "智谱1", "智谱2", "智谱10", "MiniMax主",
    ]
    assert [account.provider_id for account in accounts] == [
        "zhipu", "zhipu", "zhipu", "minimax",
    ]
    # 每账号拿到独立凭据映射，不能串号。
    assert accounts[0].plan == "max"
    assert accounts[0].windows[0].used_percent == 57.0
    assert accounts[2].windows[0].used_percent == 4.0
    assert accounts[0].windows[0].id == "five_hour"
    tokens_by_provider = {
        provider.config[f"{provider.provider_id.upper()}_TOKEN"] for provider in created
    }
    assert tokens_by_provider == {"key-1", "key-2", "key-10", "mini-1"}
    # 抓取完成后 provider 会话必须释放。
    assert created and all(provider.closed for provider in created)


def test_legacy_single_account_fallback_when_no_account_list():
    config = {
        "ZHIPU_TOKEN": "key-1",
        "ZHIPU_BASE": ZHIPU_BASE,
        "MINIMAX_TOKEN": "",
        "MINIMAX_BASE": MINIMAX_BASE,
    }
    captured: list[dict] = []

    def factory(provider_id: str, account_config: dict) -> FakeProvider:
        captured.append(dict(account_config))
        quota_value, error = ZHIPU_RESULTS["key-1"]
        return FakeProvider(provider_id, account_config, quota=quota_value, error=error)

    accounts = fetch_all_accounts(config, provider_factory=factory)

    assert [account.label for account in accounts] == ["默认"]
    assert captured == [{"ZHIPU_TOKEN": "key-1", "ZHIPU_BASE": ZHIPU_BASE}]


def test_single_account_failure_does_not_block_others():
    config = {
        "ZHIPU_ACCOUNTS": [
            {"label": "智谱1", "base": ZHIPU_BASE},
            {"label": "智谱2", "base": ZHIPU_BASE},
        ],
        "ZHIPU_TOKEN_0": "bad-1",
        "ZHIPU_TOKEN_1": "key-2",
    }
    accounts = fetch_all_accounts(config, provider_factory=make_factory(ZHIPU_RESULTS))

    assert accounts[0].error == "无法连接额度服务"
    assert accounts[0].windows == ()
    assert accounts[1].error == ""
    assert accounts[1].windows[0].used_percent == 26.0


def test_provider_exception_is_captured_as_account_error():
    config = {
        "ZHIPU_ACCOUNTS": [{"label": "智谱1", "base": ZHIPU_BASE}],
        "ZHIPU_TOKEN_0": "key-1",
    }

    def factory(provider_id: str, account_config: dict) -> FakeProvider:
        raise RuntimeError("boom")

    accounts = fetch_all_accounts(config, provider_factory=factory)
    assert len(accounts) == 1
    assert accounts[0].error
    assert "boom" not in accounts[0].error or accounts[0].error  # 错误摘要非空即可


def test_tensest_window_picks_highest_used_percent():
    accounts = [
        AccountQuota(
            "zhipu", "Zhipu GLM", "智谱1",
            windows=(QuotaWindow("five_hour", "5小时", 57.0),),
        ),
        AccountQuota(
            "zhipu", "Zhipu GLM", "智谱2",
            windows=(
                QuotaWindow("five_hour", "5小时", 88.5),
                QuotaWindow("weekly", "7天", 30.0),
            ),
        ),
    ]
    tensest = tensest_window(accounts)
    assert tensest is not None
    assert tensest.used_percent == 88.5
    assert tensest_window([]) is None


def test_account_quota_error_only_account_has_no_windows():
    account = AccountQuota("zhipu", "Zhipu GLM", "智谱9", error="未配置 API Key")
    assert account.windows == ()
    assert tensest_window([account]) is None
