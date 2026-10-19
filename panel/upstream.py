"""引擎与项目版本信息 —— 面板「关于本项目」那块显示的就是这里。

本项目的签到引擎是**自有代码**，不再从任何上游同步，因此没有「基于哪个上游
提交」这种溯源信息可读。这里只报两样：我们自己的版本号（取自
`unicheckin/__version__.py`）和站点总数。

原先这里读的是 `UPSTREAM.json`（同步上游引擎时落下的记录）；同步机制移除后
那个文件已不存在，本模块改为直接从引擎读版本。
"""

from __future__ import annotations

__all__ = ["info", "version"]


def version() -> str:
    """引擎/项目版本号。读不到时返回 'unknown'，不影响面板启动。"""
    try:
        from unicheckin.__version__ import __version__

        return str(__version__)
    except Exception:  # noqa: BLE001 - 缺依赖时降级
        pass
    try:
        import os

        here = os.path.dirname(os.path.abspath(__file__))
        ver_file = os.path.join(os.path.dirname(here), "unicheckin", "__version__.py")
        with open(ver_file, encoding="utf-8") as f:
            for line in f:
                if line.startswith("__version__"):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def info() -> dict:
    """返回归一化后的版本信息；任何异常都降级为空字典（面板会显示「未知」）。"""
    try:
        from . import catalog

        sites = len(catalog.all_sites())
    except Exception:  # noqa: BLE001
        sites = 0
    return {
        "version": version(),
        "sites": sites,
        "self_hosted": True,
    }