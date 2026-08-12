"""Backward-compatible alias for :mod:`api.deepseek_pricing`."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.deepseek_pricing import *  # noqa: F403 - 静态检查需要识别旧计价接口
else:
    from api import deepseek_pricing as _pricing

    # 兼容旧导入，同时避免在根目录重复维护计价规则。
    sys.modules[__name__] = _pricing
