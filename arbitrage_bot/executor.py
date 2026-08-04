from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from arbitrage_bot.wallet import SolanaWallet


class ExecutorError(RuntimeError):
    pass


class ExecutorDependencyError(ExecutorError):
    pass


class RpcResponseError(ExecutorError):
    pass


class TransactionConfirmationError(ExecutorError):
    """A confirmation failure, optionally with the definitive chain status."""

    def __init__(self, message: str, *, status: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status


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

    def get_wallet_lamport_delta(self, signature: str, public_key: str, commitment: str) -> int | None:
        result = self._rpc(
            "getTransaction",
            [signature, {"encoding": "jsonParsed", "commitment": commitment, "maxSupportedTransactionVersion": 0}],
        )
        if not isinstance(result, dict):
            return None
        transaction = result.get("transaction") or {}
        message = transaction.get("message") or {}
        keys = message.get("accountKeys") or []
        normalized = [item.get("pubkey") if isinstance(item, dict) else item for item in keys]
        try:
            index = normalized.index(public_key)
        except ValueError:
            return None
        meta = result.get("meta") or {}
        pre = meta.get("preBalances") or []
        post = meta.get("postBalances") or []
        if index >= len(pre) or index >= len(post):
            return None
        return int(post[index]) - int(pre[index])


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
        rebuild_leg: Callable[..., "object"] | None = None,
        balance_reader: Callable[[str], int] | None = None,
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
        self.balance_reader = balance_reader
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

        metadata = dict(plan.get("metadata") or {})
        deferred_leg_index = metadata.get("deferred_leg_index")
        legs = metadata.get("legs") or []
        deferred_mint: str | None = None
        balance_before: int | None = None
        if deferred_leg_index is not None:
            if self.commitment == "processed":
                raise ExecutorError("Deferred two-leg execution requires confirmed or finalized commitment")
            if self.rebuild_leg is None or self.balance_reader is None:
                raise ExecutorError("Deferred second leg requires rebuild_leg and balance_reader")
            if not isinstance(deferred_leg_index, int) or deferred_leg_index >= len(legs):
                raise ExecutorError("Deferred second-leg metadata is malformed")
            deferred_mint = legs[deferred_leg_index].get("in_mint")
            if not deferred_mint:
                raise ExecutorError("Deferred second leg did not specify an input mint")
            balance_before = int(self.balance_reader(deferred_mint))

        tx_results: list[dict[str, Any]] = []
        for index, transaction_base64 in enumerate(transactions):
            tx_to_send = transaction_base64
            confirmed = False
            last_exc: Exception | None = None
            local_signature: str | None = None
            rpc_signature: str | None = None
            # Later legs can be re-derived from a fresh quote if they fail at
            # broadcast/simulation (e.g. stale Jupiter quote -> 0x1771). The
            # first leg is the entry point and is never re-derived.
            can_retry = deferred_leg_index is None and index > 0 and self.rebuild_leg is not None
            for attempt in range(1 + (self.max_leg_retries if can_retry else 0)):
                try:
                    local_signature = None
                    rpc_signature = None
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
                            "wallet_lamport_delta": self._wallet_delta_safe(rpc_signature, wallet.public_key),
                        }
                    )
                    confirmed = True
                    break
                except (ExecutorError, RpcResponseError, requests.RequestException) as exc:
                    last_exc = exc
                    if can_retry and attempt < self.max_leg_retries:
                        try:
                            fresh = self.rebuild_leg(plan, index)
                        except Exception as rebuild_exc:  # noqa: BLE001
                            # A rebuild failure must NEVER crash execute_plan: the caller
                            # needs the partial result so mid-route recovery can sell the
                            # intermediate asset back. Raising here previously stranded funds.
                            last_exc = rebuild_exc
                            fresh = None
                        if fresh is not None and getattr(fresh, "transactions_base64", None):
                            tx_to_send = fresh.transactions_base64[0]
                            continue
                    break
            if not confirmed:
                # Once RPC may have accepted a transaction, a transport error or
                # confirmation timeout is ambiguous. A structured RPC simulation
                # rejection is definitive and remains eligible for recovery.
                ambiguous = rpc_signature is not None or (
                    local_signature is not None and isinstance(last_exc, requests.RequestException)
                )
                if ambiguous:
                    metadata["recovery_blocked_ambiguous_broadcast"] = True
                tx_results.append(
                    {
                        "transaction_index": index,
                        "attempt": attempt,
                        "local_signature": local_signature,
                        "rpc_signature": rpc_signature,
                        "send_latency_ms": None,
                        "confirm_latency_ms": None,
                        "slot": None,
                        "confirmations": None,
                        "confirmation_status": None,
                        "err": str(last_exc) if last_exc else "leg failed to confirm",
                        "ambiguous_broadcast": ambiguous,
                    }
                )
                break

        entry_confirmed = len(tx_results) == len(transactions) and all(
            tx.get("confirmation_status") in {"confirmed", "finalized"} and tx.get("err") is None
            for tx in tx_results
        )
        if deferred_leg_index is not None and entry_confirmed:
            received_amount = 0
            # Keep these defined for the outer structured-error path if balance
            # reading or fresh-plan building fails before a send is attempted.
            local_signature: str | None = None
            rpc_signature: str | None = None
            try:
                balance_after = int(self.balance_reader(deferred_mint))  # type: ignore[arg-type, misc]
                received_amount = balance_after - int(balance_before or 0)
                if received_amount <= 0:
                    raise ExecutorError(f"Confirmed entry leg produced no positive {deferred_mint} balance delta")
                metadata["actual_intermediate_amount"] = received_amount
                fresh_plan = self.rebuild_leg(plan, deferred_leg_index, received_amount)  # type: ignore[misc]
                fresh_transactions = list(getattr(fresh_plan, "transactions_base64", None) or [])
                if not fresh_transactions:
                    raise ExecutorError("Fresh second-leg builder returned no transactions")
                for transaction_base64 in fresh_transactions:
                    # A confirmed on-chain failure (for example Jupiter's 6001
                    # slippage error) is not ambiguous: the signature proves it
                    # cannot later fill. Requote and retry the exact balance delta
                    # before declaring a partial round trip. Transport/time-out
                    # failures remain fail-closed and never trigger a retry sell.
                    tx_to_send = transaction_base64
                    completed_second_leg = False
                    for attempt in range(1 + self.max_leg_retries):
                        local_signature: str | None = None
                        rpc_signature: str | None = None
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
                            tx_results.append(
                                {
                                    "transaction_index": len(tx_results), "leg_index": deferred_leg_index,
                                    "attempt": attempt, "local_signature": local_signature,
                                    "rpc_signature": rpc_signature, "send_latency_ms": send_latency_ms,
                                    "confirm_latency_ms": round((time.monotonic() - confirm_started) * 1000, 3),
                                    "slot": status.get("slot"), "confirmations": status.get("confirmations"),
                                    "confirmation_status": status.get("confirmationStatus"), "err": None,
                                    "wallet_lamport_delta": self._wallet_delta_safe(rpc_signature, wallet.public_key),
                                    "actual_input_amount": received_amount,
                                }
                            )
                            completed_second_leg = True
                            break
                        except Exception as exc:  # noqa: BLE001 - return a structured partial result
                            status = getattr(exc, "status", None)
                            definitively_failed = isinstance(status, dict) and status.get("err") is not None
                            can_retry = definitively_failed and attempt < self.max_leg_retries
                            tx_results.append(
                                {
                                    "transaction_index": len(tx_results), "leg_index": deferred_leg_index,
                                    "attempt": attempt, "local_signature": local_signature,
                                    "rpc_signature": rpc_signature, "send_latency_ms": None,
                                    "confirm_latency_ms": None,
                                    "slot": status.get("slot") if isinstance(status, dict) else None,
                                    "confirmations": status.get("confirmations") if isinstance(status, dict) else None,
                                    "confirmation_status": status.get("confirmationStatus") if isinstance(status, dict) else None,
                                    "err": str(exc), "actual_input_amount": received_amount,
                                    "ambiguous_broadcast": not definitively_failed and (
                                        rpc_signature is not None or
                                        (local_signature is not None and isinstance(exc, requests.RequestException))
                                    ),
                                    "superseded_by_retry": can_retry,
                                }
                            )
                            if not can_retry:
                                if tx_results[-1]["ambiguous_broadcast"]:
                                    metadata["recovery_blocked_ambiguous_broadcast"] = True
                                break
                            try:
                                retry_plan = self.rebuild_leg(plan, deferred_leg_index, received_amount)  # type: ignore[misc]
                                retry_transactions = list(getattr(retry_plan, "transactions_base64", None) or [])
                                if not retry_transactions:
                                    raise ExecutorError("Fresh second-leg retry builder returned no transactions")
                                tx_to_send = retry_transactions[0]
                            except Exception as rebuild_exc:  # noqa: BLE001
                                tx_results[-1]["superseded_by_retry"] = False
                                tx_results.append({
                                    "transaction_index": len(tx_results), "leg_index": deferred_leg_index,
                                    "attempt": attempt + 1, "err": f"second_leg_retry_build_failed: {rebuild_exc}",
                                    "actual_input_amount": received_amount, "ambiguous_broadcast": False,
                                })
                                break
                    if not completed_second_leg:
                        break
            except Exception as exc:  # noqa: BLE001 - preserve partial state
                # A returned RPC signature means the transaction may still land.
                # Never launch an automatic recovery sell in that ambiguous state.
                ambiguous = rpc_signature is not None or (
                    local_signature is not None and isinstance(exc, requests.RequestException)
                )
                if ambiguous:
                    metadata["recovery_blocked_ambiguous_broadcast"] = True
                tx_results.append(
                    {
                        "transaction_index": len(tx_results),
                        "leg_index": deferred_leg_index,
                        "attempt": 0,
                        "local_signature": local_signature,
                        "rpc_signature": rpc_signature,
                        "send_latency_ms": None,
                        "confirm_latency_ms": None,
                        "slot": None,
                        "confirmations": None,
                        "confirmation_status": None,
                        "err": str(exc),
                        "actual_input_amount": received_amount or None,
                        "ambiguous_broadcast": ambiguous,
                    }
                )

        confirmed_count = sum(
            1
            for tx in tx_results
            if tx.get("confirmation_status") in {"processed", "confirmed", "finalized"} and tx.get("err") is None
        )
        deferred_confirmed = deferred_leg_index is None or any(
            tx.get("leg_index") == deferred_leg_index
            and tx.get("confirmation_status") in {"processed", "confirmed", "finalized"}
            and tx.get("err") is None
            for tx in tx_results
        )
        all_recorded_ok = bool(tx_results) and all(
            tx.get("err") is None or tx.get("superseded_by_retry") for tx in tx_results
        )
        plan_ok = entry_confirmed and deferred_confirmed and all_recorded_ok
        return {
            "venue": plan.get("venue", "unknown"),
            "public_key": plan.get("public_key", wallet.public_key),
            "transaction_count": len(tx_results),
            "confirmed_transaction_count": confirmed_count,
            "partial": confirmed_count > 0 and not plan_ok,
            "ok": plan_ok,
            "transactions": tx_results,
            "metadata": metadata,
        }

    def _wallet_delta_safe(self, signature: str, public_key: str) -> int | None:
        try:
            return self.rpc_client.get_wallet_lamport_delta(signature, public_key, self.commitment)
        except Exception:  # telemetry failure must not change execution outcome
            return None

    def _confirm_signature(self, signature: str) -> dict[str, Any]:
        deadline = time.monotonic() + max(self.confirm_timeout_seconds, 0.0)
        while True:
            status = self.rpc_client.get_signature_status(signature)
            if status is not None:
                if status.get("err") is not None:
                    raise TransactionConfirmationError(
                        f"Transaction {signature} failed: {status['err']}", status=status
                    )
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
