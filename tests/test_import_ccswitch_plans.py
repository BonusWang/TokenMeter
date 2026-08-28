from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import import_ccswitch_plans as importer

# 假 key 仅用于测试路由与写入逻辑，不含任何真实凭据。
ZHIPU_TOKEN = "fake-zhipu-token-123456"
ZHIPU_CURRENT_TOKEN = "fake-zhipu-token-current"
MINIMAX_TOKEN = "fake-minimax-token-654321"


def make_row(
    row_id: str,
    name: str,
    app_type: str,
    token: str,
    base: str,
    *,
    notes: str = "",
    is_current: int = 0,
    created_at: int = 100,
) -> tuple:
    settings = json.dumps(
        {"env": {"ANTHROPIC_AUTH_TOKEN": token, "ANTHROPIC_BASE_URL": base}}
    )
    return (row_id, app_type, name, settings, created_at, notes, is_current)


@pytest.fixture()
def ccswitch_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "cc-switch.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE providers (
                id TEXT PRIMARY KEY,
                app_type TEXT,
                name TEXT,
                settings_config TEXT,
                created_at INTEGER,
                notes TEXT,
                is_current BOOLEAN
            )
            """
        )
    return db_path


def insert(db_path: Path, *rows: tuple) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            "INSERT INTO providers(id, app_type, name, settings_config, created_at, notes, is_current) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def test_route_provider_maps_domains():
    cases = (
        ("https://open.bigmodel.cn/api/anthropic", "zhipu"),
        ("https://api.z.ai/api/anthropic", "zhipu"),
        ("https://api.minimaxi.com/anthropic", "minimax"),
        ("https://api.minimax.io/anthropic", "minimax"),
        ("https://other.example.com/api", None),
        ("", None),
    )
    for base_url, expected in cases:
        assert importer.route_provider(base_url) == expected, base_url


def test_mask_secret_keeps_head_and_tail_only():
    masked = importer.mask_secret(ZHIPU_TOKEN)
    assert masked == "fake-z...3456"
    assert ZHIPU_TOKEN not in masked
    assert importer.mask_secret("short") == "***"


def test_read_candidates_filters_app_type_and_parses_env(ccswitch_db):
    insert(
        ccswitch_db,
        make_row("zhipu-current", "Zhipu GLM", "claude-desktop", ZHIPU_CURRENT_TOKEN,
                 "https://open.bigmodel.cn/api/anthropic", notes="智谱3", is_current=1),
        make_row("minimax-current", "MiniMax", "claude", MINIMAX_TOKEN,
                 "https://api.minimaxi.com/anthropic", is_current=1),
        # codex 渠道的同名条目不参与导入。
        make_row("zhipu-codex", "Zhipu GLM", "codex", "fake-codex-only",
                 "https://open.bigmodel.cn/api/coding/paas"),
        # 与智谱/MiniMax 无关的中转条目跳过。
        make_row("relay", "My Relay", "claude", "fake-relay-token",
                 "https://other.example.com/api"),
    )

    rows = importer.read_candidates(ccswitch_db)

    assert {row.name for row in rows} == {"Zhipu GLM", "MiniMax"}
    zhipu = next(row for row in rows if row.provider_id == "zhipu")
    assert zhipu.token == ZHIPU_CURRENT_TOKEN
    assert zhipu.base_url == "https://open.bigmodel.cn"


def test_import_accounts_sorts_by_notes_number_and_keeps_all_entries(ccswitch_db):
    insert(
        ccswitch_db,
        make_row("zhipu-1", "Zhipu GLM", "claude", "fake-zhipu-1",
                 "https://open.bigmodel.cn/api/anthropic", notes="智谱1"),
        make_row("zhipu-4", "Zhipu GLM", "claude", "fake-zhipu-4",
                 "https://open.bigmodel.cn/api/anthropic", notes="智谱4"),
        make_row("zhipu-2", "Zhipu GLM", "claude", "fake-zhipu-2",
                 "https://open.bigmodel.cn/api/anthropic", notes="智谱2"),
    )
    accounts, tokens = importer.build_provider_accounts(
        importer.read_candidates(ccswitch_db), "zhipu"
    )
    assert [account["label"] for account in accounts] == ["智谱1", "智谱2", "智谱4"]
    assert tokens == ["fake-zhipu-1", "fake-zhipu-2", "fake-zhipu-4"]


def test_import_accounts_labels_empty_notes_with_name_and_sequence(ccswitch_db):
    insert(
        ccswitch_db,
        make_row("zhipu-a", "Zhipu GLM", "claude", "fake-zhipu-a",
                 "https://open.bigmodel.cn/api/anthropic"),
        make_row("zhipu-b", "Zhipu GLM", "claude", "fake-zhipu-b",
                 "https://open.bigmodel.cn/api/anthropic"),
    )
    accounts, tokens = importer.build_provider_accounts(
        importer.read_candidates(ccswitch_db), "zhipu"
    )
    assert [account["label"] for account in accounts] == [
        "Zhipu GLM 1", "Zhipu GLM 2",
    ]
    assert tokens == ["fake-zhipu-a", "fake-zhipu-b"]


def test_apply_import_imports_all_accounts_with_indexed_tokens(ccswitch_db):
    insert(
        ccswitch_db,
        make_row("zhipu-1", "Zhipu GLM", "claude", "fake-zhipu-1",
                 "https://open.bigmodel.cn/api/anthropic", notes="智谱1"),
        make_row("zhipu-2", "Zhipu GLM", "claude-desktop", "fake-zhipu-2",
                 "https://open.bigmodel.cn/api/anthropic", notes="智谱2"),
        make_row("zhipu-3", "Zhipu GLM", "claude", "fake-zhipu-3",
                 "https://open.bigmodel.cn/api/anthropic", notes="智谱3", is_current=1),
        make_row("zhipu-4", "Zhipu GLM", "claude", "fake-zhipu-4",
                 "https://open.bigmodel.cn/api/anthropic", notes="智谱4"),
        make_row("minimax-current", "MiniMax", "claude", MINIMAX_TOKEN,
                 "https://api.minimaxi.com/anthropic", notes="MiniMax主"),
    )
    saved: dict = {}
    loads = [{"ACTIVE_PROVIDER": "zhipu"}]

    updates = importer.apply_import(
        ccswitch_db,
        save=lambda values: saved.update(values),
        load=lambda: loads[0],
        log=lambda _line: None,
    )

    assert [account["label"] for account in updates["ZHIPU_ACCOUNTS"]] == [
        "智谱1", "智谱2", "智谱3", "智谱4",
    ]
    assert updates["ZHIPU_TOKEN_0"] == "fake-zhipu-1"
    assert updates["ZHIPU_TOKEN_3"] == "fake-zhipu-4"
    assert updates["MINIMAX_ACCOUNTS"] == [
        {"label": "MiniMax主", "base": "https://api.minimaxi.com"}
    ]
    assert updates["MINIMAX_TOKEN_0"] == MINIMAX_TOKEN
    # ACTIVE_PROVIDER 只随原配置透传，导入不切换当前数据源。
    assert saved["ACTIVE_PROVIDER"] == "zhipu"
    # 日志打码：完整 key 绝不出现。
    # （打码断言在 dry-run 用例中统一覆盖。）


def test_apply_import_rerun_updates_by_label_without_duplicates(ccswitch_db):
    insert(
        ccswitch_db,
        make_row("zhipu-1", "Zhipu GLM", "claude", "fake-zhipu-1-new",
                 "https://open.bigmodel.cn/api/anthropic", notes="智谱1"),
        make_row("zhipu-2", "Zhipu GLM", "claude", "fake-zhipu-2-new",
                 "https://open.bigmodel.cn/api/anthropic", notes="智谱2"),
    )
    existing = {
        "ZHIPU_ACCOUNTS": [
            {"label": "智谱1", "base": "https://old.example.com"},
            {"label": "智谱2", "base": "https://old.example.com"},
        ],
        "ZHIPU_TOKEN_0": "fake-zhipu-1-old",
        "ZHIPU_TOKEN_1": "fake-zhipu-2-old",
        "ACTIVE_PROVIDER": "zhipu",
    }
    updates = importer.apply_import(
        ccswitch_db,
        save=lambda values: None,
        load=lambda: existing,
        log=lambda _line: None,
    )
    assert updates["ZHIPU_ACCOUNTS"] == [
        {"label": "智谱1", "base": "https://open.bigmodel.cn"},
        {"label": "智谱2", "base": "https://open.bigmodel.cn"},
    ]
    assert updates["ZHIPU_TOKEN_0"] == "fake-zhipu-1-new"
    assert updates["ZHIPU_TOKEN_1"] == "fake-zhipu-2-new"
    assert "ZHIPU_TOKEN_2" not in updates


def test_apply_import_rerun_appends_new_labels_after_existing(ccswitch_db):
    insert(
        ccswitch_db,
        make_row("zhipu-2", "Zhipu GLM", "claude", "fake-zhipu-2-new",
                 "https://open.bigmodel.cn/api/anthropic", notes="智谱2"),
    )
    existing = {
        "ZHIPU_ACCOUNTS": [{"label": "智谱1", "base": "https://open.bigmodel.cn"}],
        "ZHIPU_TOKEN_0": "fake-zhipu-1-old",
    }
    updates = importer.apply_import(
        ccswitch_db,
        save=lambda values: None,
        load=lambda: existing,
        log=lambda _line: None,
    )
    assert [account["label"] for account in updates["ZHIPU_ACCOUNTS"]] == [
        "智谱1", "智谱2",
    ]
    # 已有账号未被导入条目覆盖时保持原 token 下标不动。
    assert updates["ZHIPU_TOKEN_0"] == "fake-zhipu-1-old"
    assert updates["ZHIPU_TOKEN_1"] == "fake-zhipu-2-new"


def test_apply_import_rerun_replaces_legacy_default_account_with_same_key(ccswitch_db):
    # 先启动应用会把旧单账号迁移为「默认」账号；随后导入同一把 key 的
    # 「智谱1」时应原位覆盖，而不是追加出重复 key 的账号。
    insert(
        ccswitch_db,
        make_row("zhipu-1", "Zhipu GLM", "claude", "fake-zhipu-1-old",
                 "https://open.bigmodel.cn/api/anthropic", notes="智谱1"),
    )
    existing = {
        "ZHIPU_ACCOUNTS": [{"label": "默认", "base": "https://open.bigmodel.cn"}],
        "ZHIPU_TOKEN_0": "fake-zhipu-1-old",
        "ACTIVE_PROVIDER": "zhipu",
    }
    updates = importer.apply_import(
        ccswitch_db,
        save=lambda values: None,
        load=lambda: existing,
        log=lambda _line: None,
    )
    assert updates["ZHIPU_ACCOUNTS"] == [
        {"label": "智谱1", "base": "https://open.bigmodel.cn"}
    ]
    assert updates["ZHIPU_TOKEN_0"] == "fake-zhipu-1-old"
    assert "ZHIPU_TOKEN_1" not in updates


def test_name_without_keyword_is_skipped(ccswitch_db):
    # 域名能路由到智谱，但名字和备注都不含智谱关键词时不导入，避免误伤中转配置。
    insert(
        ccswitch_db,
        make_row("quiet-relay", " Quiet Relay ", "claude", "fake-relay-token",
                 "https://open.bigmodel.cn/api/anthropic"),
    )
    rows = importer.read_candidates(ccswitch_db)
    assert rows == []


def test_apply_import_masks_keys_in_logs_and_keeps_active_provider(ccswitch_db):
    insert(
        ccswitch_db,
        make_row("zhipu-current", "Zhipu GLM", "claude-desktop", ZHIPU_CURRENT_TOKEN,
                 "https://open.bigmodel.cn/api/anthropic", notes="智谱3", is_current=1),
        make_row("minimax-current", "MiniMax", "claude", MINIMAX_TOKEN,
                 "https://api.minimaxi.com/anthropic", is_current=1),
    )
    saved: dict = {}
    lines: list[str] = []

    updates = importer.apply_import(
        ccswitch_db,
        save=lambda values: saved.update(values),
        load=lambda: {"ACTIVE_PROVIDER": "deepseek"},
        log=lines.append,
    )

    assert updates["ZHIPU_ACCOUNTS"] == [
        {"label": "智谱3", "base": "https://open.bigmodel.cn"}
    ]
    assert updates["ZHIPU_TOKEN_0"] == ZHIPU_CURRENT_TOKEN
    # ACTIVE_PROVIDER 只随原配置透传，导入不切换当前数据源。
    assert saved["ACTIVE_PROVIDER"] == "deepseek"
    # 日志必须打码，完整 key 绝不出现。
    joined = "\n".join(lines)
    assert ZHIPU_CURRENT_TOKEN not in joined
    assert MINIMAX_TOKEN not in joined
    assert "fake-z..." in joined and "fake-m..." in joined


def test_apply_import_dry_run_lists_full_account_plan_without_write(ccswitch_db):
    insert(
        ccswitch_db,
        make_row("zhipu-1", "Zhipu GLM", "claude", "fake-zhipu-token-000001",
                 "https://open.bigmodel.cn/api/anthropic", notes="智谱1"),
        make_row("zhipu-2", "Zhipu GLM", "claude", "fake-zhipu-token-000002",
                 "https://open.bigmodel.cn/api/anthropic", notes="智谱2"),
        make_row("minimax-current", "MiniMax", "claude", MINIMAX_TOKEN,
                 "https://api.minimaxi.com/anthropic", is_current=1),
    )
    saved: dict = {}
    lines: list[str] = []

    updates = importer.apply_import(
        ccswitch_db,
        dry_run=True,
        save=lambda values: saved.update(values),
        load=lambda: {"ACTIVE_PROVIDER": "deepseek"},
        log=lines.append,
    )

    assert saved == {}
    # dry-run 输出完整账号清单：全部 label 与打码 key。
    joined = "\n".join(lines)
    for label in ("智谱1", "智谱2", "MiniMax"):
        assert label in joined
    assert "fake-zhipu-token-000001" not in joined
    assert MINIMAX_TOKEN not in joined
    assert "fake-z..." in joined and "fake-m..." in joined
    assert len(updates["ZHIPU_ACCOUNTS"]) == 2
    assert updates["ZHIPU_TOKEN_0"] == "fake-zhipu-token-000001"
    assert updates["ZHIPU_TOKEN_1"] == "fake-zhipu-token-000002"


def test_apply_import_without_matches_changes_nothing(tmp_path):
    empty_db = tmp_path / "empty.db"
    with sqlite3.connect(empty_db):
        pass
    saved: dict = {}
    updates = importer.apply_import(
        empty_db,
        save=lambda values: saved.update(values),
        load=lambda: {"ACTIVE_PROVIDER": "deepseek"},
        log=lambda _line: None,
    )
    assert updates == {}
    assert saved == {}


def test_apply_import_reports_missing_database(tmp_path):
    updates = importer.apply_import(
        tmp_path / "missing.db",
        save=lambda values: None,
        load=lambda: {},
        log=lambda _line: None,
    )
    assert updates == {}
