"""多账号额度聚合：并发抓取白名单 provider 的全部账号，单账号失败不互相阻塞。

账号结构来自 config 的 ``<PROVIDER>_ACCOUNTS``（非密，含 label/base）与凭据
管理器的 ``<PROVIDER>_TOKEN_<n>``；旧单账号配置（``<PROVIDER>_TOKEN``）在没有
账号列表时作为兜底账号参与抓取。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime

from api.providers import get_provider
from api.providers.base import Provider, QuotaWindow
from config.defaults import UI_PROVIDER_WHITELIST

_MAX_WORKERS = 8

# 悬浮球聚合只关心这两类窗口；其他窗口类型（如月度）不进聚合。
AGGREGATE_WINDOW_IDS = ("five_hour", "weekly")
AGGREGATE_WINDOW_TITLES = {"five_hour": "5小时", "weekly": "每周"}


@dataclass(frozen=True)
class AccountQuota:
    """一个账号的一次抓取结果；error 非空表示该账号失败。"""

    provider_id: str
    provider_name: str
    label: str
    plan: str = ""
    windows: tuple[QuotaWindow, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class AggregateWindow:
    """同窗口类型跨账号的聚合结果，供悬浮卡片双进度条渲染。"""

    window_id: str
    title: str
    remaining_percent: float
    account_count: int
    earliest_reset: datetime | None


@dataclass(frozen=True)
class ProviderGroupSummary:
    """单个 provider 分组的聚合视图，供悬浮卡片按组渲染。"""

    provider_id: str
    provider_name: str
    account_count: int
    accounts: tuple[AccountQuota, ...]
    windows: dict[str, AggregateWindow]


def _natural_sort_key(label: str) -> list[tuple[int, object]]:
    # “智谱2”排在“智谱10”前面：数字段按数值比较，其余按小写文本比较。
    parts = re.split(r"(\d+)", str(label))
    return [
        (1, int(part)) if part.isdigit() else (0, part.lower()) for part in parts if part
    ]


def account_jobs(config: Mapping[str, object]) -> list[tuple[str, str, str, str]]:
    """返回 (provider_id, label, token, base) 的抓取清单，顺序即展示顺序。"""

    jobs: list[tuple[str, str, str, str]] = []
    for provider_id in UI_PROVIDER_WHITELIST:
        upper = provider_id.upper()
        accounts = config.get(f"{upper}_ACCOUNTS") or []
        if accounts:
            for index, account in enumerate(accounts):
                if not isinstance(account, Mapping):
                    continue
                jobs.append(
                    (
                        provider_id,
                        str(account.get("label", "") or ""),
                        str(config.get(f"{upper}_TOKEN_{index}", "") or ""),
                        str(account.get("base", "") or ""),
                    )
                )
            continue
        # 旧单账号配置兜底：未迁移时仍能看到原账号。
        legacy_token = str(config.get(f"{upper}_TOKEN", "") or "")
        if legacy_token:
            jobs.append(
                (
                    provider_id,
                    "默认",
                    legacy_token,
                    str(config.get(f"{upper}_BASE", "") or ""),
                )
            )
    return jobs


def fetch_all_accounts(
    config: Mapping[str, object],
    *,
    provider_factory=get_provider,
) -> list[AccountQuota]:
    """并发抓取全部账号；任一账号的异常都收敛为该账号的错误摘要。"""

    jobs = account_jobs(config)
    if not jobs:
        return []
    results: list[AccountQuota | None] = [None] * len(jobs)

    def fetch_one(index: int, provider_id: str, label: str, token: str, base: str) -> None:
        upper = provider_id.upper()
        account_config = {f"{upper}_TOKEN": token, f"{upper}_BASE": base}
        provider: Provider | None = None
        try:
            provider = provider_factory(provider_id, account_config)
            quota, error = provider.fetch_quota()
            if error is not None:
                results[index] = AccountQuota(
                    provider_id, provider.name, label, error=error.message
                )
                return
            if quota is None:
                results[index] = AccountQuota(
                    provider_id, provider.name, label, error="额度数据不可用"
                )
                return
            results[index] = AccountQuota(
                provider_id,
                provider.name,
                label,
                plan=quota.plan,
                windows=quota.windows,
            )
        except Exception as exc:
            # 单账号崩溃不阻塞其他账号；日志不记录凭据内容。
            from config import runtime as config_manager

            config_manager.logger().warning(
                "Account quota fetch failed: provider=%s (%s)", provider_id, type(exc).__name__
            )
            results[index] = AccountQuota(
                provider_id, provider_id, label, error="账号额度查询失败"
            )
        finally:
            if provider is not None:
                with suppress(Exception):
                    provider.close()

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(jobs))) as executor:
        futures = [
            executor.submit(fetch_one, index, *job) for index, job in enumerate(jobs)
        ]
        for future in futures:
            future.result()

    ordered = [result for result in results if result is not None]
    provider_order = {
        provider_id: index for index, provider_id in enumerate(UI_PROVIDER_WHITELIST)
    }
    ordered.sort(
        key=lambda account: (
            provider_order.get(account.provider_id, len(provider_order)),
            _natural_sort_key(account.label),
        )
    )
    return ordered


def tensest_window(accounts: list[AccountQuota]) -> QuotaWindow | None:
    """所有账号中已用百分比最高的窗口（最紧张）；无可用窗口时返回 None。"""

    windows = [window for account in accounts for window in account.windows]
    if not windows:
        return None
    return max(windows, key=lambda window: window.used_percent)


def group_by_provider(accounts: list[AccountQuota]) -> dict[str, list[AccountQuota]]:
    """按 provider_id 分组并保持白名单顺序（zhipu→minimax）。

    fetch_all_accounts 的产物已按白名单排序，这里再按白名单键重排一次以
    不依赖上游实现；白名单外的 provider（理论不可达）兜底追加在末尾。
    """

    grouped: dict[str, list[AccountQuota]] = {}
    for account in accounts:
        grouped.setdefault(account.provider_id, []).append(account)
    ordered: dict[str, list[AccountQuota]] = {}
    for provider_id in UI_PROVIDER_WHITELIST:
        if provider_id in grouped:
            ordered[provider_id] = grouped.pop(provider_id)
    ordered.update(grouped)
    return ordered


def aggregate_windows(accounts: list[AccountQuota]) -> dict[str, AggregateWindow]:
    """组内各账号同窗口的剩余百分比算术平均（round 1 位）。

    智谱老版套餐与 MiniMax 只返回剩余百分比、无统一绝对额度，真加权不可得；
    error 账号与缺该窗口的账号不参与该窗口的平均。空输入返回空 dict。
    """

    remaining_by_window: dict[str, list[float]] = {}
    resets_by_window: dict[str, list[datetime]] = {}
    for account in accounts:
        if account.error:
            continue
        for window in account.windows:
            if window.id not in AGGREGATE_WINDOW_IDS:
                continue
            remaining = max(0.0, min(100.0, 100 - window.used_percent))
            remaining_by_window.setdefault(window.id, []).append(remaining)
            if window.resets_at is not None:
                resets_by_window.setdefault(window.id, []).append(window.resets_at)
    aggregates: dict[str, AggregateWindow] = {}
    for window_id, remaining in remaining_by_window.items():
        aggregates[window_id] = AggregateWindow(
            window_id=window_id,
            title=AGGREGATE_WINDOW_TITLES.get(window_id, window_id),
            remaining_percent=round(sum(remaining) / len(remaining), 1),
            account_count=len(remaining),
            earliest_reset=(
                min(resets_by_window[window_id]) if window_id in resets_by_window else None
            ),
        )
    return aggregates


def summarize_by_provider(accounts: list[AccountQuota]) -> list[ProviderGroupSummary]:
    """按 provider 汇总卡片所需的分组视图；无账号时返回空列表。"""

    summaries: list[ProviderGroupSummary] = []
    for provider_id, members in group_by_provider(accounts).items():
        # 异常收敛路径拿不到 provider.name（记为 provider_id），优先取真实显示名。
        display_names = [
            account.provider_name
            for account in members
            if account.provider_name and account.provider_name != account.provider_id
        ]
        summaries.append(
            ProviderGroupSummary(
                provider_id=provider_id,
                provider_name=display_names[0] if display_names else provider_id,
                account_count=len(members),
                accounts=tuple(members),
                windows=aggregate_windows(members),
            )
        )
    return summaries


__all__ = [
    "AccountQuota",
    "AggregateWindow",
    "ProviderGroupSummary",
    "account_jobs",
    "aggregate_windows",
    "fetch_all_accounts",
    "group_by_provider",
    "summarize_by_provider",
    "tensest_window",
]
