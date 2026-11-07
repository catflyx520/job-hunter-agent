"""API key 加密。金钥来自 `.env` 的 APP_SECRET_KEY（Fernet 格式）。

产生新金钥：`uv run python -m app.core.security`
"""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class SecretKeyMissing(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = get_settings().app_secret_key
    if not key:
        raise SecretKeyMissing(
            "未设定 APP_SECRET_KEY，无法加密保存 API key。"
            "请执行 `uv run python -m app.core.security` 产生金钥并写入 .env。"
        )
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise SecretKeyMissing("APP_SECRET_KEY 格式不正确，必须是 Fernet 金钥。") from exc


def encrypt_secret(plain: str) -> bytes:
    return _fernet().encrypt(plain.encode("utf-8"))


def decrypt_secret(token: bytes) -> str:
    try:
        return _fernet().decrypt(bytes(token)).decode("utf-8")
    except InvalidToken as exc:
        raise SecretKeyMissing("无法解密已保存的 key：APP_SECRET_KEY 可能已更换，请重新输入 key。") from exc


def last4(plain: str) -> str:
    return plain[-4:] if len(plain) >= 4 else ""


if __name__ == "__main__":
    print(Fernet.generate_key().decode())
