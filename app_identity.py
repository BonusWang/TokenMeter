"""Backward-compatible alias for :mod:`core.identity`."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.identity import *  # noqa: F403 - 静态检查需要识别旧入口的公开常量
else:
    from core import identity as _identity

    # 保留模块对象别名，使旧脚本对常量的读取与新包路径始终指向同一份定义。
    sys.modules[__name__] = _identity
