"""多账号配置层测试：秘密键前缀判定、账号列表校验与旧单账号迁移。"""

from __future__ import annotations

import json
from unittest.mock import patch

from config import runtime as config_manager
from config.defaults import DEFAULT_CONFIG, SECRET_KEYS, is_secret_key
from config.store import public_values, validate_value

ZHIPU_BASE = "https://open.bigmodel.cn"
MINIMAX_BASE = "https://api.minimaxi.com"


def test_ui_provider_whitelist_only_contains_coding_plan_providers():
    from config.defaults import UI_PROVIDER_WHITELIST

    assert UI_PROVIDER_WHITELIST == ("zhipu", "minimax")


def test_is_secret_key_prefix_matching():
    # 旧精确键保持秘密判定。
    assert all(is_secret_key(key) for key in SECRET_KEYS)
    # 序号化账号 token 键按前缀判定为秘密。
    assert is_secret_key("ZHIPU_TOKEN_0")
    assert is_secret_key("ZHIPU_TOKEN_12")
    assert is_secret_key("MINIMAX_TOKEN_3")
    # 非秘密键不能被误伤。
    assert not is_secret_key("ZHIPU_BASE")
    assert not is_secret_key("MINIMAX_BASE")
    assert not is_secret_key("ZHIPU_ACCOUNTS")
    assert not is_secret_key("MINIMAX_ACCOUNTS")
    assert not is_secret_key("ACTIVE_PROVIDER")


def test_public_values_hide_indexed_account_tokens():
    values = {
        "ZHIPU_TOKEN_0": "secret-a",
        "MINIMAX_TOKEN_1": "secret-b",
        "ZHIPU_ACCOUNTS": [{"label": "智谱1", "base": ZHIPU_BASE}],
        "ACTIVE_PROVIDER": "zhipu",
    }
    result = public_values(values)
    assert "ZHIPU_TOKEN_0" not in result
    assert "MINIMAX_TOKEN_1" not in result
    assert result["ZHIPU_ACCOUNTS"] == [{"label": "智谱1", "base": ZHIPU_BASE}]


def test_account_list_validation_normalizes_entries():
    value = validate_value(
        "ZHIPU_ACCOUNTS",
        [{"label": " 智谱1 ", "base": ZHIPU_BASE}, {"base": ""}],
    )
    assert value == [
        {"label": "智谱1", "base": ZHIPU_BASE},
        {"label": "", "base": ""},
    ]


def test_account_list_validation_rejects_invalid_entries():
    import pytest

    with pytest.raises(ValueError):
        validate_value("ZHIPU_ACCOUNTS", "not-a-list")
    with pytest.raises(ValueError):
        validate_value("ZHIPU_ACCOUNTS", ["not-a-dict"])
    with pytest.raises(ValueError):
        validate_value("ZHIPU_ACCOUNTS", [{"label": "x", "base": "ftp://bad"}])
    # 空列表合法（尚未导入账号）。
    assert validate_value("MINIMAX_ACCOUNTS", []) == []


def test_defaults_include_empty_account_lists():
    assert DEFAULT_CONFIG["ZHIPU_ACCOUNTS"] == []
    assert DEFAULT_CONFIG["MINIMAX_ACCOUNTS"] == []


def test_load_config_migrates_legacy_single_account(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"ZHIPU_BASE": ZHIPU_BASE, "MINIMAX_BASE": MINIMAX_BASE}),
        encoding="utf-8",
    )
    credentials = {"ZHIPU_TOKEN": "legacy-zhipu-key", "MINIMAX_TOKEN": "legacy-mini-key"}
    writes: list[tuple[str, str]] = []

    def fake_write(key: str, value: str) -> None:
        writes.append((key, value))
        if value:
            credentials[key] = value
        else:
            credentials.pop(key, None)

    with (
        patch.object(config_manager, "CONFIG_PATH", config_path),
        patch.object(config_manager, "CONFIG_DIR", tmp_path),
        patch.object(config_manager, "_read_credential", lambda key: credentials.get(key, "")),
        patch.object(config_manager, "_write_credential", fake_write),
    ):
        config = config_manager.load_config()

    # 账号列表生成且 base 沿用旧配置；label 用默认占位。
    assert config["ZHIPU_ACCOUNTS"] == [{"label": "默认", "base": ZHIPU_BASE}]
    assert config["MINIMAX_ACCOUNTS"] == [{"label": "默认", "base": MINIMAX_BASE}]
    # 新凭据先写入，旧键随后清理，凭据全程不丢。
    assert credentials.get("ZHIPU_TOKEN_0") == "legacy-zhipu-key"
    assert credentials.get("MINIMAX_TOKEN_0") == "legacy-mini-key"
    assert "ZHIPU_TOKEN" not in credentials
    assert "MINIMAX_TOKEN" not in credentials
    write_order = [key for key, _value in writes]
    assert write_order.index("ZHIPU_TOKEN_0") < len(writes) - 1
    assert "ZHIPU_TOKEN" in write_order  # 清理动作（value=""）也经过写入口
    # 迁移结果落盘，重启不会二次迁移。
    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert on_disk["ZHIPU_ACCOUNTS"] == [{"label": "默认", "base": ZHIPU_BASE}]
    assert "ZHIPU_TOKEN" not in on_disk


def test_load_config_skips_migration_when_accounts_exist(tmp_path):
    accounts = [{"label": "智谱1", "base": ZHIPU_BASE}]
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"ZHIPU_ACCOUNTS": accounts, "ZHIPU_BASE": ZHIPU_BASE}),
        encoding="utf-8",
    )
    credentials = {"ZHIPU_TOKEN": "stale-legacy-key", "ZHIPU_TOKEN_0": "real-key"}

    with (
        patch.object(config_manager, "CONFIG_PATH", config_path),
        patch.object(config_manager, "CONFIG_DIR", tmp_path),
        patch.object(config_manager, "_read_credential", lambda key: credentials.get(key, "")),
        patch.object(config_manager, "_write_credential", lambda key, value: None),
    ):
        config = config_manager.load_config()

    assert config["ZHIPU_ACCOUNTS"] == accounts
    # 已迁移的配置不再回退读取旧单账号键。
    assert config["ZHIPU_TOKEN_0"] == "real-key"


def test_load_config_reads_indexed_tokens_for_each_account(tmp_path):
    accounts = [
        {"label": "智谱1", "base": ZHIPU_BASE},
        {"label": "智谱2", "base": ZHIPU_BASE},
    ]
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"ZHIPU_ACCOUNTS": accounts}), encoding="utf-8")
    credentials = {"ZHIPU_TOKEN_0": "key-0", "ZHIPU_TOKEN_1": "key-1"}
    reads: list[str] = []

    def fake_read(key: str) -> str:
        reads.append(key)
        return credentials.get(key, "")

    with (
        patch.object(config_manager, "CONFIG_PATH", config_path),
        patch.object(config_manager, "CONFIG_DIR", tmp_path),
        patch.object(config_manager, "_read_credential", fake_read),
        patch.object(config_manager, "_write_credential", lambda key, value: None),
    ):
        config = config_manager.load_config()

    assert config["ZHIPU_TOKEN_0"] == "key-0"
    assert config["ZHIPU_TOKEN_1"] == "key-1"
    assert "ZHIPU_TOKEN_0" in reads and "ZHIPU_TOKEN_1" in reads


def test_save_config_round_trips_account_tokens(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    credentials: dict[str, str] = {}
    with (
        patch.object(config_manager, "CONFIG_PATH", config_path),
        patch.object(config_manager, "CONFIG_DIR", tmp_path),
        patch.object(config_manager, "_read_credential", lambda key: credentials.get(key, "")),
        patch.object(
            config_manager,
            "_write_credential",
            lambda key, value: credentials.update({key: value}) if value else credentials.pop(key, None),
        ),
    ):
        config_manager.load_config()
        config_manager.save_config(
            {
                "ZHIPU_ACCOUNTS": [{"label": "智谱1", "base": ZHIPU_BASE}],
                "ZHIPU_TOKEN_0": "round-trip-key",
            }
        )

    assert credentials.get("ZHIPU_TOKEN_0") == "round-trip-key"
    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    assert on_disk["ZHIPU_ACCOUNTS"] == [{"label": "智谱1", "base": ZHIPU_BASE}]
    assert not any(key.startswith("ZHIPU_TOKEN") for key in on_disk)


def test_save_config_clears_credentials_beyond_shrunk_account_list(tmp_path):
    """账号列表缩短后，超出新长度的旧下标凭据必须清空，不能残留凭据管理器。"""

    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    credentials: dict[str, str] = {}
    with (
        patch.object(config_manager, "CONFIG_PATH", config_path),
        patch.object(config_manager, "CONFIG_DIR", tmp_path),
        patch.object(config_manager, "_read_credential", lambda key: credentials.get(key, "")),
        patch.object(
            config_manager,
            "_write_credential",
            lambda key, value: credentials.update({key: value}) if value else credentials.pop(key, None),
        ),
    ):
        config_manager.load_config()
        config_manager.save_config(
            {
                "ZHIPU_ACCOUNTS": [
                    {"label": "智谱1", "base": ZHIPU_BASE},
                    {"label": "智谱2", "base": ZHIPU_BASE},
                ],
                "ZHIPU_TOKEN_0": "key-A",
                "ZHIPU_TOKEN_1": "key-B",
            }
        )
        assert credentials.get("ZHIPU_TOKEN_1") == "key-B"

        config_manager.save_config(
            {
                "ZHIPU_ACCOUNTS": [{"label": "智谱1", "base": ZHIPU_BASE}],
                "ZHIPU_TOKEN_0": "key-A",
            }
        )
        # 被删除账号的下标凭据已清空，内存态也不再携带。
        assert "ZHIPU_TOKEN_1" not in credentials
        assert config_manager.get("ZHIPU_TOKEN_1", "") == ""

        # 失败回滚不动本次语义：扩回 2 个账号后旧下标不复活残留值。
        config_manager.save_config(
            {
                "ZHIPU_ACCOUNTS": [
                    {"label": "智谱1", "base": ZHIPU_BASE},
                    {"label": "新账号", "base": ZHIPU_BASE},
                ],
                "ZHIPU_TOKEN_0": "key-A",
                "ZHIPU_TOKEN_1": "key-C",
            }
        )
        assert credentials.get("ZHIPU_TOKEN_1") == "key-C"
