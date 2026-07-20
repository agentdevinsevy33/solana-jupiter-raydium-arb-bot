from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any

import requests

from arbitrage_bot.wallet import SolanaWallet


class ExecutorError(RuntimeError):
    pass


class ExecutorDependencyError(ExecutorError):
    pass


class RpcResponseError(ExecutorError):
    pass


class TransactionConfirmationError(ExecutorError):
    pass


@dataclass(slots=True)
class SolanaRpcClient:
    rpc_url: str
    session: requests.Session | None = None
    timeout: int = 20

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()

    def _rpc(self, method: str, params: list[Any]) -> Any:
        assert self.session is not None
        response = self.session.post(
            self.rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=self.timeout,
            headers={"Content-Type": "application/json", "User-Agent": "solana-jupiter-raydium-arb-bot/0.1"},
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RpcResponseError(f"RPC {method} failed: {payload['error']}")
        if "result" not in payload:
            raise RpcResponseError(f"RPC {method} response missing result: {payload}")
        return payload["result"]

    def send_transaction(
        self,
        signed_transaction_base64: str,
        *,
        skip_preflight: bool,
        preflight_commitment: str,
        max_retries: int,
    ) -> str:
        result = self._rpc(
            "sendTransaction",
            [
                signed_transaction_base64,
                {
                    "encoding": "base64",
                    "skipPreflight": skip_preflight,
                    "preflightCommitment": preflight_commitment,
                    "maxRetries": max_retries,
                },
            ],
        )
        if not isinstance(result, str) or not result:
            raise RpcResponseError(f"sendTransaction returned unexpected result: {result!r}")
        return result

    def get_signature_status(self, signature: str) -> dict[str, Any] | None:
        result = self._rpc("getSignatureStatuses", [[signature], {"searchTransactionHistory": True}])
        if not isinstance(result, dict):
            raise RpcResponseError(f"getSignatureStatuses returned unexpected result: {result!r}")
        values = result.get("value")
        if not isinstance(values, list) or not values:
            raise RpcResponseError(f"getSignatureStatuses returned malformed value list: {result!r}")
        status = values[0]
        if status is not None and not isinstance(status, dict):
            raise RpcResponseError(f"getSignatureStatuses returned malformed status: {status!r}")
        return status


class TradeExecutor:
    def __init__(
        self,
        *,
        rpc_url: str,
        session: requests.Session | None = None,
        timeout: int = 20,
        confirm_timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 1.0,
        skip_preflight: bool = False,
        commitment: str = "confirmed",
        max_retries: int = 3,
        rebuild_leg: Callable[[dict[str, Any], int], "object"] | None = None,
        max_leg_retries: int = 3,
    ) -> None:
        self.rpc_client = SolanaRpcClient(rpc_url=rpc_url, session=session, timeout=timeout)
        self.confirm_timeout_seconds = confirm_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.skip_preflight = skip_preflight
        self.commitment = commitment
        self.max_retries = max_retries
        # Optional callback that re-derives a single leg (by index) from a fresh
        # quote. Used to retry a later leg whose broadcast failed because its
        # pre-built transaction went stale (e.g. Jupiter 0x1771).
        self.rebuild_leg = rebuild_leg
        self.max_leg_retries = max(0, int(max_leg_retries))

    def execute_prepared_swaps(self, wallet: SolanaWallet, prepared_swaps: list[dict[str, Any]]) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        stop_reason: str | None = None
        for plan in prepared_swaps:
            try:
                plan_result = self.execute_plan(wallet, plan)
            except ExecutorError as exc:
                plan_result = {
                    "venue": plan.get("venue", "unknown"),
                    "ok": False,
                    "error": str(exc),
                    "transactions": [],
                }
                stop_reason = str(exc)
                results.append(plan_result)
                break
            results.append(plan_result)
            if not plan_result.get("ok", False):
                stop_reason = plan_result.get("error") or "plan execution failed"
                break

        submitted_count = sum(len(item.get("transactions", [])) for item in results)
        confirmed_count = sum(
            1
            for item in results
            for tx in item.get("transactions", [])
            if tx.get("confirmation_status") in {"processed", "confirmed", "finalized"} and tx.get("err") is None
        )
        return {
            "execution_results": results,
            "execution_summary": {
                "rpc_url": self.rpc_client.rpc_url,
                "plan_count": len(prepared_swaps),
                "plans_executed": len(results),
                "submitted_transaction_count": submitted_count,
                "confirmed_transaction_count": confirmed_count,
                "completed": stop_reason is None and len(results) == len(prepared_swaps),
                "stop_reason": stop_reason,
                "commitment": self.commitment,
                "skip_preflight": self.skip_preflight,
            },
        }

    def execute_plan(self, wallet: SolanaWallet, plan: dict[str, Any]) -> dict[str, Any]:
        transactions = plan.get("transactions_base64") or []
        if not transactions:
            raise ExecutorError(f"Prepared swap for venue {plan.get('venue', 'unknown')} did not include any transactions")

        tx_results: list[dict[str, Any]] = []
        for index, transaction_base64 in enumerate(transactions):
            tx_to_send = transaction_base64
            confirmed = False
            last_exc: Exception | None = None
            # Later legs can be re-derived from a fresh quote if they fail at
            # broadcast/simulation (e.g. stale Jupiter quote -> 0x1771). The
            # first leg is the entry point and is never re-derived.
            can_retry = index > 0 and self.rebuild_leg is not None
            for attempt in range(1 + (self.max_leg_retries if can_retry else 0)):
                try:
                    signed_transaction_base64, local_signature = self._sign_transaction_base64(wallet, tx_to_send)
                    send_started = time.monotonic()
                    rpc_signature = self.rpc_client.send_transaction(
                        signed_transaction_base64,
                        skip_preflight=self.skip_preflight,
                        preflight_commitment=self.commitment,
                        max_retries=self.max_retries,
                    )
                    send_latency_ms = round((time.monotonic() - send_started) * 1000, 3)
                    confirm_started = time.monotonic()
                    status = self._confirm_signature(rpc_signature)
                    confirm_latency_ms = round((time.monotonic() - confirm_started) * 1000, 3)
                    tx_results.append(
                        {
                            "transaction_index": index,
                            "attempt": attempt,
                            "local_signature": local_signature,
                            "rpc_signature": rpc_signature,
                            "send_latency_ms": send_latency_ms,
                            "confirm_latency_ms": confirm_latency_ms,
                            "slot": status.get("slot") if status else None,
                            "confirmations": status.get("confirmations") if status else None,
                            "confirmation_status": status.get("confirmationStatus") if status else None,
                            "err": status.get("err") if status else None,
                        }
                    )
                    confirmed = True
                    break
                except (ExecutorError, RpcResponseError) as exc:
                    last_exc = exc
                    if can_retry and attempt < self.max_leg_retries:
                        fresh = self.rebuild_leg(plan, index)
                        if fresh is not None and getattr(fresh, "transactions_base64", None):
                            tx_to_send = fresh.transactions_base64[0]
                            continue
                    break
            if not confirmed:
                # Surface the failure so the caller records + stops the plan.
                raise last_exc if last_exc else ExecutorError(f"Leg {index} failed to confirm")

        confirmed_count = sum(
            1
            for tx in tx_results
            if tx.get("confirmation_status") in {"processed", "confirmed", "finalized"} and tx.get("err") is None
        )
        return {
            "venue": plan.get("venue", "unknown"),
            "public_key": plan.get("public_key", wallet.public_key),
            "transaction_count": len(tx_results),
            "confirmed_transaction_count": confirmed_count,
            "partial": 0 < confirmed_count < len(transactions),
            "ok": confirmed_count == len(transactions),
            "transactions": tx_results,
            "metadata": dict(plan.get("metadata") or {}),
        }

    def _confirm_signature(self, signature: str) -> dict[str, Any]:
        deadline = time.monotonic() + max(self.confirm_timeout_seconds, 0.0)
        while True:
            status = self.rpc_client.get_signature_status(signature)
            if status is not None:
                if status.get("err") is not None:
                    raise TransactionConfirmationError(f"Transaction {signature} failed: {status['err']}")
                confirmation_status = status.get("confirmationStatus")
                if self._commitment_satisfied(confirmation_status):
                    return status
            if time.monotonic() >= deadline:
                raise TransactionConfirmationError(
                    f"Timed out waiting for {self.commitment} confirmation for transaction {signature}"
                )
            time.sleep(max(self.poll_interval_seconds, 0.0))

    def _commitment_satisfied(self, confirmation_status: str | None) -> bool:
        levels = {None: -1, "processed": 0, "confirmed": 1, "finalized": 2}
        required = levels.get(self.commitment, 1)
        current = levels.get(confirmation_status, -1)
        return current >= required

    def _sign_transaction_base64(self, wallet: SolanaWallet, transaction_base64: str) -> tuple[str, str]:
        keypair_cls, versioned_transaction_cls = self._load_solders()
        keypair = keypair_cls.from_bytes(bytes(wallet.secret_key))
        unsigned_tx = versioned_transaction_cls.from_bytes(base64.b64decode(transaction_base64))
        signed_tx = versioned_transaction_cls(unsigned_tx.message, [keypair])
        signed_bytes = bytes(signed_tx)
        signature = str(signed_tx.signatures[0]) if getattr(signed_tx, "signatures", None) else ""
        return base64.b64encode(signed_bytes).decode("ascii"), signature

    @staticmethod
    def _load_solders():
        try:
            from solders.keypair import Keypair
            from solders.transaction import VersionedTransaction
        except ModuleNotFoundError as exc:
            raise ExecutorDependencyError(
                "The solders package is required for execute-swaps mode. Install it first, for example with: "
                "python3 -m pip install solders requests"
            ) from exc
        return Keypair, VersionedTransaction
