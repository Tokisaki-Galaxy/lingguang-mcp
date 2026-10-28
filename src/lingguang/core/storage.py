"""凭据存储。

Windows 用系统凭据管理器，其他平台写文件。

为什么 Windows 单独处理：凭据管理器由系统托管，密钥与用户账户绑定，
不存在用户目录里，同步盘扫不到。
明文 ctoken 被同步盘带走，等于泄露支付宝授权登录态。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "lingguang"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"

WIN_TARGET = "lingguang-mcp"
WIN_USERNAME = "lingguang"


def _file_save(payload: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        os.chmod(CREDENTIALS_FILE, 0o600)
    except (OSError, NotImplementedError):
        pass


def _file_load() -> dict | None:
    if not CREDENTIALS_FILE.exists():
        return None
    try:
        data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _file_clear() -> None:
    if CREDENTIALS_FILE.exists():
        CREDENTIALS_FILE.unlink()


def _win_save(payload: dict) -> None:
    import win32cred

    win32cred.CredWrite(
        {
            "TargetName": WIN_TARGET,
            "Type": win32cred.CRED_TYPE_GENERIC,
            "CredentialBlob": json.dumps(payload, ensure_ascii=False),
            "Comment": "lingguang 登录凭据",
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            "UserName": WIN_USERNAME,
        },
        0,
    )


def _win_load() -> dict | None:
    import win32cred

    try:
        cred = win32cred.CredRead(WIN_TARGET, win32cred.CRED_TYPE_GENERIC)
    except Exception:  # noqa: BLE001  凭据不存在时抛 pywintypes.error
        return None
    blob = cred.get("CredentialBlob") or b""
    # 凭据管理器原生是 UTF-16LE，用别的编码读中文会乱码
    try:
        data = json.loads(blob.decode("utf-16-le"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _win_clear() -> None:
    import win32cred

    try:
        win32cred.CredDelete(WIN_TARGET, win32cred.CRED_TYPE_GENERIC)
    except Exception:  # noqa: BLE001  不存在就当作已清除
        pass


def use_windows_backend() -> bool:
    """Windows 且有 pywin32 时用凭据管理器。"""
    if sys.platform != "win32":
        return False
    try:
        import win32cred  # noqa: F401
    except ImportError:
        return False
    return True


def backend_name() -> str:
    return "windows-credential-manager" if use_windows_backend() else "file"


def save(payload: dict) -> None:
    (_win_save if use_windows_backend() else _file_save)(payload)


def load() -> dict | None:
    return (_win_load if use_windows_backend() else _file_load)()


def clear() -> None:
    (_win_clear if use_windows_backend() else _file_clear)()
