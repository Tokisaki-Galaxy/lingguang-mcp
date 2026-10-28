"""MCP stdio server 与工具定义。

注意：这里不 import server 模块。
server 在导入时会把 sys.stdout 重定向到 stderr，
如果包初始化时就导入，`python -m lingguang.mcp.server` 的
顶层执行顺序会被打乱，导致协议帧写进 stderr。
所以 run 用延迟导入。
"""

from .tools import TOOL_DEFINITIONS, dispatch

__all__ = ["TOOL_DEFINITIONS", "dispatch", "run"]


def run() -> None:
    from .server import run as _run

    _run()
