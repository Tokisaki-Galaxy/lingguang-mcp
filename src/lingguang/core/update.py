"""版本检查与更新提示。

只查 PyPI，不做任何自动检查。
访问 PyPI 仅发生在用户显式执行 version 命令时。

工具本身除了访问灵光接口，不对外发送任何信息。
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

import requests

from .. import __version__

PYPI_URL = "https://pypi.org/pypi/lingguang/json"
REPO = "Tokisaki-Galaxy/lingguang-mcp"
TIMEOUT = 5

CURRENT = __version__


def is_dev_version(version: str) -> bool:
    """本地构建的版本，带 .dev 或本地哈希，不该提示升级。"""
    return ".dev" in version or "+" in version or version == "0.0.0+unknown"


def parse_version(version: str) -> tuple[int, ...]:
    """把 0.3.0 拆成 (0, 3, 0)。非纯数字段丢弃，够用且不引依赖。"""
    parts = re.findall(r"\d+", version.split("+")[0].split("-")[0])
    return tuple(int(p) for p in parts[:3]) or (0,)


def is_newer(latest: str, current: str) -> bool:
    """按元组比较，避免字符串比较下 0.10.0 < 0.9.0 的坑。"""
    return parse_version(latest) > parse_version(current)


@dataclass
class UpdateInfo:
    current: str
    latest: str | None
    error: str | None
    is_dev: bool

    @property
    def has_update(self) -> bool:
        if self.latest is None or self.is_dev:
            return False
        return is_newer(self.latest, self.current)

    @property
    def report_url(self) -> str | None:
        """更新说明地址，优先给两个版本之间的提交对比。"""
        if not self.latest:
            return None
        if _is_release_tag(self.current) and _is_release_tag(self.latest):
            return f"https://github.com/{REPO}/compare/v{self.current}...v{self.latest}"
        return f"https://github.com/{REPO}/tags"


def _is_release_tag(version: str) -> bool:
    """判断能否拼成合法的 tag，非标准版本走 tags 页面兜底。"""
    return bool(re.fullmatch(r"\d+\.\d+\.\d+", version))


def install_method() -> str:
    """判断当前是怎么装的，给出对应的升级命令。

    uv tool 装的解释器一定在 uv 的 tools 目录下，这个特征可靠。
    """
    exe = sys.executable.replace("\\", "/")
    if "/uv/tools/" in exe or "/.local/share/uv/tools/" in exe:
        return "uv tool upgrade lingguang"
    if "pipx" in exe:
        return "pipx upgrade lingguang"
    if sys.prefix != sys.base_prefix or os.environ.get("VIRTUAL_ENV"):
        return "pip install -U lingguang"
    return "pip install -U lingguang"


def check_pypi(timeout: int = TIMEOUT) -> UpdateInfo:
    """查 PyPI 最新版本。失败不抛异常，把错误写进结果。"""
    if is_dev_version(CURRENT):
        return UpdateInfo(CURRENT, None, None, is_dev=True)
    try:
        resp = requests.get(PYPI_URL, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        latest = str(data["info"]["version"])
    except requests.RequestException as exc:
        return UpdateInfo(CURRENT, None, f"无法连接 PyPI: {exc}", is_dev=False)
    except (ValueError, KeyError) as exc:
        return UpdateInfo(CURRENT, None, f"PyPI 返回格式异常: {exc}", is_dev=False)
    return UpdateInfo(CURRENT, latest, None, is_dev=False)
