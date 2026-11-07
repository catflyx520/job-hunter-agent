"""记录本机 CLI 的登录是否已失效。

`claude auth status` 在 token 过期时仍会回报 loggedIn=true，所以要从实际调用的错误判断：
调用回报 401 / token 过期 → 标记失效；调用成功或重新登录成功 → 清除。只存在记忆体，不碰任何凭证。
"""

from __future__ import annotations

import re
import threading

AUTH_ERROR = re.compile(
    r"\b401\b|OAuth access token|token has expired|not logged in|please run /login|invalid_api_key|authentication_error",
    re.I,
)

_invalid: set[str] = set()
_lock = threading.Lock()


def is_auth_error(text: str) -> bool:
    return bool(AUTH_ERROR.search(text or ""))


def mark_invalid(cli: str) -> None:
    with _lock:
        _invalid.add(cli)


def clear(cli: str) -> None:
    with _lock:
        _invalid.discard(cli)


def is_invalid(cli: str) -> bool:
    with _lock:
        return cli in _invalid
