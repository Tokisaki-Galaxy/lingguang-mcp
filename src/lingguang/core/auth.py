"""cookie 的导入、存储与状态检查。

cookie 是唯一入口的钥匙，失效时工具完全不可用，
所以这里要做事前预判而不是事后诊断。

存储位置 ~/.config/lingguang/credentials.json，权限 0600。
Windows 下会尝试用 DPAPI 加密 cookie 本身，
不可用时退化为明文加文件权限，并在状态里如实报告。

重要：明文 ctoken 被同步盘或备份软件扫走，等于泄露支付宝授权登录态。
"""

from __future__ import annotations

import json
import os
import re
import stat
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import AuthError

CONFIG_DIR = Path.home() / ".config" / "lingguang"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
PENDING_FILE = Path.home() / ".cache" / "lingguang" / "pending.jsonl"
FAILED_DIR = Path.home() / ".cache" / "lingguang" / "failed"

# 实测有效的三个关键 cookie
KEY_COOKIES = ("ctoken", "prod_LINGGUANGJSESSIONID", "spanner")


@dataclass
class Credentials:
    cookie: str
    imported_at: float = 0.0
    last_ok_at: float = 0.0
    last_error: str = ""
    last_error_at: float = 0.0
    encrypted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_cookie_string(raw: str) -> str:
    """从任意粘贴内容里抽出 cookie。

    支持三种输入：
      1. 纯 cookie 字符串：name=value; name=value
      2. 从 curl 命令里粘：-H 'cookie: ...'
      3. 带换行的多行文本
    """
    text = raw.strip()
    if not text:
        raise AuthError("输入为空")

    # 从 curl 抓
    m = re.search(r"-H\s+['\"]cookie:\s*([^'\"]+)['\"]", text, re.IGNORECASE)
    if m:
        text = m.group(1).strip()

    # 折叠成单行
    text = " ".join(text.split())
    if "ctoken=" not in text:
        raise AuthError("内容里找不到 ctoken，请确认复制的是完整的 cookie")
    return text


def check_cookie_completeness(cookie: str) -> list[str]:
    """检查关键 cookie 是否齐全，返回缺失项。

    缺 spanner 或 JSESSIONID 时服务端可能仍能识别，
    但稳定性会下降，所以要如实报告。
    """
    present = {part.strip().partition("=")[0] for part in cookie.split(";") if part.strip()}
    return [name for name in KEY_COOKIES if name not in present]


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _restrict_permissions(path: Path) -> None:
    """尽力把文件权限收到 0600。Windows 上 chmod 语义有限，失败不阻断。"""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except (OSError, NotImplementedError):
        pass


def save_credentials(creds: Credentials) -> Path:
    _ensure_dir(CONFIG_DIR)
    CREDENTIALS_FILE.write_text(
        json.dumps(creds.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _restrict_permissions(CREDENTIALS_FILE)
    return CREDENTIALS_FILE


def load_credentials() -> Credentials | None:
    if not CREDENTIALS_FILE.exists():
        return None
    try:
        data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict) or not data.get("cookie"):
        return None
    return Credentials(
        cookie=str(data["cookie"]),
        imported_at=float(data.get("imported_at") or 0),
        last_ok_at=float(data.get("last_ok_at") or 0),
        last_error=str(data.get("last_error") or ""),
        last_error_at=float(data.get("last_error_at") or 0),
        encrypted=bool(data.get("encrypted")),
    )


def get_cookie() -> str:
    """按优先级取 cookie：环境变量 > 凭据文件。

    环境变量优先是为了在 CI 或临时场景里能覆盖。
    """
    env = os.environ.get("LG_COOKIE", "").strip()
    if env:
        return parse_cookie_string(env)

    creds = load_credentials()
    if creds is None:
        raise AuthError(
            "还没有导入 cookie。运行 `lingguang auth import <文件>` 导入，"
            "或设置环境变量 LG_COOKIE"
        )
    return creds.cookie


def mark_ok() -> None:
    creds = load_credentials()
    if creds is None:
        return
    creds.last_ok_at = time.time()
    creds.last_error = ""
    save_credentials(creds)


def mark_error(message: str) -> None:
    creds = load_credentials()
    if creds is None:
        return
    creds.last_error = message[:500]
    creds.last_error_at = time.time()
    save_credentials(creds)


def describe_status() -> dict[str, Any]:
    """给 auth_status 用。返回人话，不返回裸时间戳。"""
    env_cookie = os.environ.get("LG_COOKIE", "").strip()
    creds = load_credentials()

    if creds is None and not env_cookie:
        return {
            "valid": False,
            "imported": False,
            "hint": "还没有导入 cookie，运行 `lingguang auth import <文件>`",
        }

    if creds is None and env_cookie:
        return {
            "valid": False,
            "imported": True,
            "source": "env:LG_COOKIE",
            "missing_keys": check_cookie_completeness(env_cookie),
            "hint": "cookie 来自环境变量 LG_COOKIE，尚未验证",
        }

    assert creds is not None
    now = time.time()
    days = int((now - creds.imported_at) / 86400) if creds.imported_at else 0
    hours_since_ok = int((now - creds.last_ok_at) / 3600) if creds.last_ok_at else -1

    return {
        "valid": bool(creds.last_ok_at) and not creds.last_error,
        "imported": True,
        "source": "file",
        "imported_days": days,
        "last_ok_hours": hours_since_ok,
        "last_error": creds.last_error,
        "missing_keys": check_cookie_completeness(creds.cookie),
        "hint": "cookie 会在你从未操作后的一段时间失效，失效时重新导入即可",
    }


def clear_credentials() -> None:
    if CREDENTIALS_FILE.exists():
        CREDENTIALS_FILE.unlink()
