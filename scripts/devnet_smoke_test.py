"""Devnet smoke test for the arbitrage executor's sign + broadcast + confirm path.

This validates the DANGEROUS part of execute-swaps (real solders signing + live RPC
broadcast + confirmation) WITHOUT touching mainnet funds:

  Tier 1 (always runs): build a VersionedTransaction, sign it with the devnet wallet
          key via solders, and verify the signature is valid off-chain. Proves keypair
          loading + signing work and won't broadcast garbage.
  Tier 2 (if the devnet wallet can be funded): airdrop devnet SOL, broadcast a real
          self-transfer, and confirm it on-chain via TradeExecutor.

Nothing here touches mainnet or the mainnet wallet. Run with:
    python3 scripts/devnet_smoke_test.py
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction

from arbitrage_bot.executor import TradeExecutor
from arbitrage_bot.wallet import load_wallet

DEVNET_RPC = "https://api.devnet.solana.com"


def _rpc(method: str, params: list, rpc_url: str = DEVNET_RPC) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(rpc_url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    if "error" in data:
        raise RuntimeError(f"RPC {method} failed: {data['error']}")
    return data["result"]


def _build_self_transfer_tx(secret_key: list[int], blockhash_b58: str, lamports: int) -> str:
    kp = Keypair.from_bytes(bytes(secret_key))
    pub = kp.pubkey()
    ix = transfer(TransferParams(from_pubkey=pub, to_pubkey=pub, lamports=lamports))
    msg = MessageV0.try_compile(pub, [ix], [], Hash.from_string(blockhash_b58))
    tx = VersionedTransaction(msg, [kp])
    return base64.b64encode(bytes(tx)).decode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wallet-path", default="wallets/devnet-test.json")
    parser.add_argument("--rpc-url", default=DEVNET_RPC)
    args = parser.parse_args()

    wallet = load_wallet(args.wallet_path, network="devnet")
    print(f"[devnet-smoke] wallet public_key = {wallet.public_key}")

    # ---- Tier 1: off-chain signing + signature verification ----
    blockhash = _rpc("getLatestBlockhash", [{"commitment": "finalized"}])["value"]["blockhash"]
    tx_b64 = _build_self_transfer_tx(wallet.secret_key, blockhash, lamports=0)
    kp = Keypair.from_bytes(bytes(wallet.secret_key))
    vt = VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
    # Recover signer index 0 and verify the signature matches the message.
    sig = vt.signatures[0]
    # For MessageV0 the signature is over the version prefix (0x80) + serialized message.
    signed_msg = b"\x80" + bytes(vt.message)
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(bytes(kp.pubkey())).verify(bytes(sig), signed_msg)
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    print(f"[devnet-smoke] Tier1 signing OK, signature verifies = {ok}")
    if not ok:
        print("[devnet-smoke] FAILED: signature did not verify", file=sys.stderr)
        return 1

    # ---- Tier 2: live broadcast + confirm (only if funded) ----
    try:
        bal = _rpc("getBalance", [str(wallet.public_key)])["value"]
    except Exception as exc:  # noqa: BLE001
        bal = 0
        print(f"[devnet-smoke] getBalance error ({exc}); assuming unfunded")
    if bal == 0:
        try:
            _rpc("requestAirdrop", [str(wallet.public_key), 100_000_000, {"commitment": "finalized"}])
            print("[devnet-smoke] airdrop requested; confirming balance...")
            _rpc("getLatestBlockhash", [])  # no-op to let airdrop land
            import time
            time.sleep(3)
            bal = _rpc("getBalance", [str(wallet.public_key)])["value"]
        except Exception as exc:  # noqa: BLE001
            print(f"[devnet-smoke] airdrop failed ({exc}); skipping live broadcast")
            bal = 0
    if bal == 0:
        print("[devnet-smoke] Tier2 skipped (devnet wallet unfunded; Tier1 signing verified).")
        return 0

    blockhash = _rpc("getLatestBlockhash", [{"commitment": "finalized"}])["value"]["blockhash"]
    tx_b64 = _build_self_transfer_tx(wallet.secret_key, blockhash, lamports=1_000)
    executor = TradeExecutor(rpc_url=args.rpc_url, confirm_timeout_seconds=30.0, poll_interval_seconds=1.0)
    result = executor.execute_prepared_swaps(
        wallet,
        [{"venue": "devnet-self-transfer", "public_key": wallet.public_key, "transactions_base64": [tx_b64]}],
    )
    summary = result["execution_summary"]
    print(f"[devnet-smoke] Tier2 broadcast: submitted={summary['submitted_transaction_count']} confirmed={summary['confirmed_transaction_count']} completed={summary['completed']}")
    for res in result["execution_results"]:
        for tx in res.get("transactions", []):
            print(f"[devnet-smoke]   sig={tx.get('rpc_signature')} status={tx.get('confirmation_status')} err={tx.get('err')}")
    if not summary["completed"]:
        print("[devnet-smoke] FAILED: live broadcast did not complete", file=sys.stderr)
        return 1
    print("[devnet-smoke] PASS: sign + broadcast + confirm verified on devnet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
