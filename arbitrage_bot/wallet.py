from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


class WalletError(RuntimeError):
    pass


@dataclass(slots=True)
class SolanaWallet:
    public_key: str
    secret_key: list[int]
    network: str = "devnet"

    def to_public_dict(self) -> dict[str, str]:
        return {
            "public_key": self.public_key,
            "network": self.network,
        }


def _base58_encode(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    encoded = ""
    while number > 0:
        number, remainder = divmod(number, 58)
        encoded = _BASE58_ALPHABET[remainder] + encoded
    leading_zeros = len(raw) - len(raw.lstrip(b"\x00"))
    return ("1" * leading_zeros) + (encoded or "1")


def _normalize_secret_key(values: list[int]) -> bytes:
    if len(values) == 64:
        return bytes(values[:32])
    if len(values) == 32:
        return bytes(values)
    raise WalletError(f"Expected 32 or 64 secret-key bytes, got {len(values)}")


def _wallet_from_private_key(private_key: Ed25519PrivateKey, *, network: str) -> SolanaWallet:
    secret_seed = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return SolanaWallet(
        public_key=_base58_encode(public_bytes),
        secret_key=list(secret_seed + public_bytes),
        network=network,
    )


def create_devnet_wallet(path: str | Path, *, network: str = "devnet") -> SolanaWallet:
    wallet_path = Path(path)
    wallet_path.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    wallet = _wallet_from_private_key(private_key, network=network)
    wallet_path.write_text(json.dumps(wallet.secret_key), encoding="utf-8")
    return wallet


def load_wallet(path: str | Path, *, network: str = "devnet") -> SolanaWallet:
    wallet_path = Path(path)
    if not wallet_path.exists():
        raise WalletError(f"Wallet file not found: {wallet_path}")
    values = json.loads(wallet_path.read_text(encoding="utf-8"))
    if not isinstance(values, list) or not all(isinstance(item, int) for item in values):
        raise WalletError(f"Wallet file must contain a JSON array of ints: {wallet_path}")
    secret_seed = _normalize_secret_key(values)
    private_key = Ed25519PrivateKey.from_private_bytes(secret_seed)
    return _wallet_from_private_key(private_key, network=network)
