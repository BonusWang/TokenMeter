"""Backward-compatible alias for :mod:`data.directory`."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data.directory import *  # noqa: F403 - 静态检查需要识别旧数据目录接口
else:
    from data import directory as _directory

    # 数据迁移测试会替换模块级路径对象；模块别名可保持旧钩子的既有行为。
    sys.modules[__name__] = _directory
