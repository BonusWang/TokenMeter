"""Backward-compatible alias for :mod:`updater.client`."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from updater.client import *  # noqa: F403 - 静态检查需要识别旧更新接口
else:
    from updater import client as _client

    # 直接复用实现模块，确保旧调用方替换测试钩子时仍影响真实更新流程。
    sys.modules[__name__] = _client
