"""从 CCSwitch 导入智谱 GLM / MiniMax Coding Plan 凭据到 TokenMeter。

读取 ~/.cc-switch/cc-switch.db（只读），按名字+备注识别两家厂商的条目并
全部导入为多账号配置：账号列表（label/base，非密）写入 config.json，每个
账号的 token 按下标写入凭据管理器（ZHIPU_TOKEN_0…）。按 ANTHROPIC_BASE_URL
域名路由；不修改 ACTIVE_PROVIDER；按 label 覆盖更新，可重复执行。
日志全程打码，绝不输出完整 key。

用法：
    python scripts/import_ccswitch_plans.py [--db 路径] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# 直接 `python scripts/import_ccswitch_plans.py` 运行时仓库根不在 sys.path，
# 按 scripts/build_release.py 的同款惯例补齐，保证 `from config import ...` 可用。
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DB_PATH = Path.home() / ".cc-switch" / "cc-switch.db"
# 只导入 Claude 渠道的配置；codex 等其他渠道的条目不参与。
APP_TYPES = ("claude", "claude-desktop")
PROVIDER_IDS = ("zhipu", "minimax")
# 域名路由：bigmodel.cn→zhipu，minimaxi.com/minimax.io→minimax。
_DOMAIN_ROUTING = (
    ("zhipu", ("bigmodel.cn", "z.ai")),
    ("minimax", ("minimaxi.com", "minimax.io")),
)
# 名字或备注命中关键词才认为是该厂商条目，避免误伤指向官方域名的中转配置。
_KEYWORDS = {
    "zhipu": ("zhipu", "智谱", "glm"),
    "minimax": ("minimax",),
}
_NOTES_NUMBER = re.compile(r"(\d+)\s*$")


def mask_secret(value: str) -> str:
    """打码显示 key：前 6 后 4；过短时完全隐藏。"""
    return f"{value[:6]}...{value[-4:]}" if len(value) > 12 else "***"


def route_provider(base_url: str) -> str | None:
    host = (urlparse(str(base_url or "")).hostname or "").lower()
    if not host:
        return None
    for provider_id, domains in _DOMAIN_ROUTING:
        if any(host == domain or host.endswith(f".{domain}") for domain in domains):
            return provider_id
    return None


def canonical_base(base_url: str) -> str:
    """CCSwitch 的 Anthropic 兼容地址去掉路径，只保留站点根地址。"""
    parsed = urlparse(str(base_url or ""))
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


@dataclass(frozen=True)
class CandidateRow:
    provider_id: str
    name: str
    notes: str
    token: str
    base_url: str
    is_current: bool
    notes_rank: int
    created_at: int


def _notes_rank(notes: str) -> int:
    # 备注形如“智谱1/智谱2/智谱4”，取末尾数字作为新旧序号；无数字记 0。
    match = _NOTES_NUMBER.search(str(notes or "").strip())
    return int(match.group(1)) if match else 0


def read_candidates(db_path: Path, log=print) -> list[CandidateRow]:
    if not Path(db_path).exists():
        log(f"未找到 CCSwitch 数据库：{db_path}")
        return []
    # 只读打开，导入脚本绝不写 CCSwitch 库。
    connection = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        placeholders = ",".join("?" for _ in APP_TYPES)
        rows = connection.execute(
            f"SELECT name, notes, is_current, settings_config, created_at "
            f"FROM providers WHERE app_type IN ({placeholders})",
            APP_TYPES,
        ).fetchall()
    except sqlite3.Error as exc:
        log(f"读取 CCSwitch 数据库失败：{exc}")
        return []
    finally:
        connection.close()

    candidates: list[CandidateRow] = []
    for name, notes, is_current, settings_config, created_at in rows:
        try:
            settings = json.loads(settings_config or "{}")
        except ValueError:
            continue
        env = settings.get("env") if isinstance(settings, dict) else None
        if not isinstance(env, dict):
            continue
        token = str(env.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
        base = canonical_base(str(env.get("ANTHROPIC_BASE_URL") or ""))
        provider_id = route_provider(base)
        if not token or not provider_id or not base:
            continue
        haystack = f"{name} {notes}".lower()
        if not any(keyword in haystack for keyword in _KEYWORDS[provider_id]):
            continue
        candidates.append(
            CandidateRow(
                provider_id=provider_id,
                name=str(name or ""),
                notes=str(notes or ""),
                token=token,
                base_url=base,
                is_current=bool(is_current),
                notes_rank=_notes_rank(notes),
                created_at=int(created_at or 0),
            )
        )
    return candidates


def build_provider_accounts(
    rows: list[CandidateRow], provider_id: str
) -> tuple[list[dict[str, str]], list[str]]:
    """把该厂商的全部匹配条目整理为账号列表与按下标对应的 token 列表。

    按备注序号排序（智谱1 → 智谱4）；备注为空时用「名称 + 序号」补位。
    """

    matching = [row for row in rows if row.provider_id == provider_id]
    matching.sort(key=lambda row: (row.notes_rank, row.created_at, row.name))
    accounts: list[dict[str, str]] = []
    tokens: list[str] = []
    sequence = 0
    for row in matching:
        label = row.notes.strip()
        if not label:
            sequence += 1
            label = f"{row.name.strip() or provider_id} {sequence}"
        accounts.append({"label": label, "base": row.base_url})
        tokens.append(row.token)
    return accounts, tokens


def _merge_account_entries(
    existing: list,
    existing_tokens: list[str],
    imported_accounts: list[dict[str, str]],
    tokens: list[str],
) -> tuple[list[dict[str, str]], dict[int, str]]:
    """按 label（其次按 token）覆盖合并：已有账号原位更新，新账号追加。

    先跑过应用再导入时，旧单账号可能已被迁移为「默认」账号；同一把 key
    再次导入必须原位改名覆盖，否则会出现重复 key 的账号。
    """

    merged: list[dict[str, str]] = [
        dict(item) if isinstance(item, dict) else {} for item in existing
    ]
    index_by_label: dict[str, int] = {}
    index_by_token: dict[str, int] = {}
    for index, item in enumerate(merged):
        label = str(item.get("label", ""))
        if label and label not in index_by_label:
            index_by_label[label] = index
        token = existing_tokens[index] if index < len(existing_tokens) else ""
        if token and token not in index_by_token:
            index_by_token[token] = index
    imported_tokens: dict[int, str] = {}
    for position, account in enumerate(imported_accounts):
        label = account["label"]
        index = index_by_label.get(label)
        if index is None:
            index = index_by_token.get(tokens[position])
        if index is None:
            merged.append(dict(account))
            index = len(merged) - 1
        else:
            merged[index]["base"] = account["base"]
        merged[index]["label"] = label
        index_by_label[label] = index
        imported_tokens[index] = tokens[position]
    return merged, imported_tokens


def apply_import(
    db_path: Path | None = None,
    *,
    dry_run: bool = False,
    save=None,
    load=None,
    log=print,
) -> dict[str, object]:
    """执行导入，返回写入（或 dry-run 计划写入）的配置键值。"""
    candidates = read_candidates(db_path or DEFAULT_DB_PATH, log=log)
    plans: dict[str, tuple[list[dict[str, str]], list[str]]] = {}
    for provider_id in PROVIDER_IDS:
        accounts, tokens = build_provider_accounts(candidates, provider_id)
        if accounts:
            plans[provider_id] = (accounts, tokens)
        else:
            log(f"[{provider_id}] 未在 CCSwitch 中找到可识别的 Coding Plan 凭据")
    if not plans:
        log("没有可导入的凭据，未修改任何配置")
        return {}
    if save is None or load is None:
        from config import runtime as config_manager

        save = save or config_manager.save_config
        load = load or config_manager.load_config
    # 只合并账号相关键；ACTIVE_PROVIDER 等既有配置原样透传，导入不切换数据源。
    current = dict(load() or {})
    updates: dict[str, object] = {}
    for provider_id, (imported_accounts, tokens) in plans.items():
        upper = provider_id.upper()
        existing_accounts = current.get(f"{upper}_ACCOUNTS") or []
        existing_tokens = [
            str(current.get(f"{upper}_TOKEN_{index}", "") or "")
            for index in range(len(existing_accounts))
        ]
        merged, imported_tokens = _merge_account_entries(
            existing_accounts, existing_tokens, imported_accounts, tokens
        )
        updates[f"{upper}_ACCOUNTS"] = merged
        for index in range(len(merged)):
            token = imported_tokens.get(
                index, str(current.get(f"{upper}_TOKEN_{index}", "") or "")
            )
            updates[f"{upper}_TOKEN_{index}"] = token
            account = merged[index]
            log(
                f"[{provider_id}] 账号 {account['label']} "
                f"key={mask_secret(token)} base={account['base']}"
            )
    if dry_run:
        log("dry-run：仅显示以上计划写入项，未执行写入")
        return updates
    save({**current, **updates})
    log(f"已写入 {len(updates)} 个配置项（TOKEN 保存到 Windows 凭据管理器）")
    return updates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 CCSwitch 导入 Coding Plan 凭据到 TokenMeter")
    parser.add_argument("--db", type=Path, default=None, help="CCSwitch 数据库路径（默认 ~/.cc-switch/cc-switch.db）")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划写入项，不执行写入")
    args = parser.parse_args(argv)
    updates = apply_import(args.db, dry_run=args.dry_run)
    return 0 if updates else 1


if __name__ == "__main__":
    sys.exit(main())
