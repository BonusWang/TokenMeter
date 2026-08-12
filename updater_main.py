"""Backward-compatible launcher for :mod:`updater.main`."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from updater.main import *  # noqa: F403 - 静态检查需要识别旧更新器入口
elif __name__ == "__main__":
    from updater.main import main

    raise SystemExit(main())
else:
    from updater import main as _main

    # 被导入时保留完整模块别名；作为脚本执行时则显式转发到新入口。
    sys.modules[__name__] = _main
