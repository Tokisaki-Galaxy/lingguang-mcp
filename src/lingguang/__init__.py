"""灵光 MCP 与 CLI 工具。"""

try:
    from ._version import __version__
except ImportError:  # 未经构建的源码目录直接运行
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
