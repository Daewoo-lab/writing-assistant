"""Payme Merchant API (JSON-RPC 2.0) client + callback dispatcher.

Implements the six merchant methods Payme calls on our endpoint. Business
state (who paid, which subscription) is delegated to a MerchantStore so this
module stays transport-only and testable with mocks.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Protocol

# --- Payme error codes -------------------------------------------------------
E_AUTH = -32504
E_METHOD = -32601
E_ACCOUNT = -31050          # invalid account (e.g. unknown user_id)
E_AMOUNT = -31001           # wrong amount
E_TX_NOT_FOUND = -31003
E_CANNOT_PERFORM = -31008
E_ALREADY_DONE = -31060

STATE_CREATED = 1
STATE_DONE = 2
STATE_CANCELLED = -1
STATE_CANCELLED_AFTER_DONE = -2


class PaymeError(Exception):
    def __init__(self, code: int, message: str, data: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def as_rpc(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return err


@dataclass(frozen=True)
class PaymeTx:
    id: str
    user_id: int
    amount: int           # tiyin
    state: int
    create_time: int
    perform_time: int = 0
    cancel_time: int = 0
    reason: int | None = None


class MerchantStore(Protocol):
    async def resolve_user(self, user_id: int) -> bool: ...
    async def validate_amount(self, user_id: int, amount: int) -> bool: ...
    async def get_tx(self, tx_id: str) -> PaymeTx | None: ...
    async def create_tx(self, tx_id: str, user_id: int, amount: int, create_time: int) -> PaymeTx: ...
    async def mark_performed(self, tx_id: str, perform_time: int) -> PaymeTx: ...
    async def mark_cancelled(self, tx_id: str, cancel_time: int, reason: int) -> PaymeTx: ...
    async def statement(self, frm: int, to: int) -> list[PaymeTx]: ...


def check_auth(authorization: str | None, secret_key: str) -> None:
    if not authorization or not authorization.startswith("Basic "):
        raise PaymeError(E_AUTH, "Insufficient privileges")
    try:
        decoded = base64.b64decode(authorization[6:]).decode()
        _, _, password = decoded.partition(":")
    except Exception as exc:
        raise PaymeError(E_AUTH, "Insufficient privileges") from exc
    if password != secret_key:
        raise PaymeError(E_AUTH, "Insufficient privileges")


def _account_user_id(params: dict[str, Any]) -> int:
    account = params.get("account") or {}
    raw = account.get("user_id")
    if raw is None:
        raise PaymeError(E_ACCOUNT, "user_id required", data="user_id")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise PaymeError(E_ACCOUNT, "invalid user_id", data="user_id") from exc


def _tx_view(tx: PaymeTx) -> dict[str, Any]:
    return {
        "create_time": tx.create_time,
        "perform_time": tx.perform_time,
        "cancel_time": tx.cancel_time,
        "transaction": tx.id,
        "state": tx.state,
        "reason": tx.reason,
    }


class PaymeCallback:
    def __init__(self, store: MerchantStore, secret_key: str) -> None:
        self._store = store
        self._secret = secret_key

    async def handle(self, authorization: str | None, body: dict[str, Any]) -> dict[str, Any]:
        rpc_id = body.get("id")
        try:
            check_auth(authorization, self._secret)
            method = body.get("method")
            params = body.get("params") or {}
            result = await self._dispatch(method, params)
            return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
        except PaymeError as err:
            return {"jsonrpc": "2.0", "id": rpc_id, "error": err.as_rpc()}

    async def _dispatch(self, method: str | None, p: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "CheckPerformTransaction": self._check_perform,
            "CreateTransaction": self._create,
            "PerformTransaction": self._perform,
            "CancelTransaction": self._cancel,
            "CheckTransaction": self._check,
            "GetStatement": self._statement,
        }
        handler = handlers.get(method or "")
        if handler is None:
            raise PaymeError(E_METHOD, "Method not found")
        return await handler(p)

    async def _check_perform(self, p: dict[str, Any]) -> dict[str, Any]:
        user_id = _account_user_id(p)
        if not await self._store.resolve_user(user_id):
            raise PaymeError(E_ACCOUNT, "user not found", data="user_id")
        if not await self._store.validate_amount(user_id, int(p.get("amount", 0))):
            raise PaymeError(E_AMOUNT, "wrong amount")
        return {"allow": True}

    async def _create(self, p: dict[str, Any]) -> dict[str, Any]:
        tx_id = str(p["id"])
        existing = await self._store.get_tx(tx_id)
        if existing is not None:
            if existing.state != STATE_CREATED:
                raise PaymeError(E_CANNOT_PERFORM, "transaction in terminal state")
            return {"create_time": existing.create_time, "transaction": existing.id, "state": existing.state}

        user_id = _account_user_id(p)
        if not await self._store.resolve_user(user_id):
            raise PaymeError(E_ACCOUNT, "user not found", data="user_id")
        if not await self._store.validate_amount(user_id, int(p.get("amount", 0))):
            raise PaymeError(E_AMOUNT, "wrong amount")

        tx = await self._store.create_tx(tx_id, user_id, int(p["amount"]), int(p["time"]))
        return {"create_time": tx.create_time, "transaction": tx.id, "state": tx.state}

    async def _perform(self, p: dict[str, Any]) -> dict[str, Any]:
        tx = await self._store.get_tx(str(p["id"]))
        if tx is None:
            raise PaymeError(E_TX_NOT_FOUND, "transaction not found")
        if tx.state == STATE_DONE:
            return {"transaction": tx.id, "perform_time": tx.perform_time, "state": tx.state}
        if tx.state != STATE_CREATED:
            raise PaymeError(E_CANNOT_PERFORM, "cannot perform")
        done = await self._store.mark_performed(tx.id, _now_ms())
        return {"transaction": done.id, "perform_time": done.perform_time, "state": done.state}

    async def _cancel(self, p: dict[str, Any]) -> dict[str, Any]:
        tx = await self._store.get_tx(str(p["id"]))
        if tx is None:
            raise PaymeError(E_TX_NOT_FOUND, "transaction not found")
        if tx.state in (STATE_CANCELLED, STATE_CANCELLED_AFTER_DONE):
            return {"transaction": tx.id, "cancel_time": tx.cancel_time, "state": tx.state}
        cancelled = await self._store.mark_cancelled(tx.id, _now_ms(), int(p.get("reason", 0)))
        return {"transaction": cancelled.id, "cancel_time": cancelled.cancel_time, "state": cancelled.state}

    async def _check(self, p: dict[str, Any]) -> dict[str, Any]:
        tx = await self._store.get_tx(str(p["id"]))
        if tx is None:
            raise PaymeError(E_TX_NOT_FOUND, "transaction not found")
        return _tx_view(tx)

    async def _statement(self, p: dict[str, Any]) -> dict[str, Any]:
        txs = await self._store.statement(int(p["from"]), int(p["to"]))
        return {
            "transactions": [
                {
                    "id": t.id,
                    "time": t.create_time,
                    "amount": t.amount,
                    "account": {"user_id": t.user_id},
                    "create_time": t.create_time,
                    "perform_time": t.perform_time,
                    "cancel_time": t.cancel_time,
                    "transaction": t.id,
                    "state": t.state,
                    "reason": t.reason,
                }
                for t in txs
            ]
        }


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


def payment_link(checkout_base: str, merchant_id: str, user_id: int, amount_tiyin: int) -> str:
    payload = f"m={merchant_id};ac.user_id={user_id};a={amount_tiyin}"
    token = base64.b64encode(payload.encode()).decode()
    return f"{checkout_base.rstrip('/')}/{token}"
