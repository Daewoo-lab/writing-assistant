from __future__ import annotations

import base64

import pytest

from writing_assistant.billing.payme import (
    E_AMOUNT,
    E_AUTH,
    E_METHOD,
    E_TX_NOT_FOUND,
    STATE_CANCELLED,
    STATE_CREATED,
    STATE_DONE,
    PaymeCallback,
    PaymeTx,
    payment_link,
)

SECRET = "s3cret"
AMOUNT = 25_000_000  # 250 000 UZS in tiyin


class FakeStore:
    def __init__(self) -> None:
        self.txs: dict[str, PaymeTx] = {}
        self.users = {42}

    async def resolve_user(self, user_id: int) -> bool:
        return user_id in self.users

    async def validate_amount(self, user_id: int, amount: int) -> bool:
        return amount == AMOUNT

    async def get_tx(self, tx_id: str) -> PaymeTx | None:
        return self.txs.get(tx_id)

    async def create_tx(self, tx_id, user_id, amount, create_time):  # type: ignore[no-untyped-def]
        tx = PaymeTx(id=tx_id, user_id=user_id, amount=amount, state=STATE_CREATED, create_time=create_time)
        self.txs[tx_id] = tx
        return tx

    async def mark_performed(self, tx_id, perform_time):  # type: ignore[no-untyped-def]
        old = self.txs[tx_id]
        tx = PaymeTx(old.id, old.user_id, old.amount, STATE_DONE, old.create_time, perform_time=perform_time)
        self.txs[tx_id] = tx
        return tx

    async def mark_cancelled(self, tx_id, cancel_time, reason):  # type: ignore[no-untyped-def]
        old = self.txs[tx_id]
        tx = PaymeTx(old.id, old.user_id, old.amount, STATE_CANCELLED, old.create_time, cancel_time=cancel_time, reason=reason)
        self.txs[tx_id] = tx
        return tx

    async def statement(self, frm, to):  # type: ignore[no-untyped-def]
        return [t for t in self.txs.values() if frm <= t.create_time <= to]


def _auth(secret: str = SECRET) -> str:
    return "Basic " + base64.b64encode(f"Paycom:{secret}".encode()).decode()


def _rpc(method: str, params: dict, rpc_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}


@pytest.fixture
def cb() -> PaymeCallback:
    return PaymeCallback(FakeStore(), SECRET)


@pytest.mark.asyncio
async def test_auth_rejected(cb: PaymeCallback) -> None:
    res = await cb.handle("Basic " + base64.b64encode(b"Paycom:wrong").decode(),
                          _rpc("CheckPerformTransaction", {"amount": AMOUNT, "account": {"user_id": 42}}))
    assert res["error"]["code"] == E_AUTH


@pytest.mark.asyncio
async def test_check_perform_ok(cb: PaymeCallback) -> None:
    res = await cb.handle(_auth(), _rpc("CheckPerformTransaction", {"amount": AMOUNT, "account": {"user_id": 42}}))
    assert res["result"] == {"allow": True}


@pytest.mark.asyncio
async def test_check_perform_wrong_amount(cb: PaymeCallback) -> None:
    res = await cb.handle(_auth(), _rpc("CheckPerformTransaction", {"amount": 1, "account": {"user_id": 42}}))
    assert res["error"]["code"] == E_AMOUNT


@pytest.mark.asyncio
async def test_create_then_perform_then_check(cb: PaymeCallback) -> None:
    p = {"id": "tx1", "time": 1000, "amount": AMOUNT, "account": {"user_id": 42}}
    created = await cb.handle(_auth(), _rpc("CreateTransaction", p))
    assert created["result"]["state"] == STATE_CREATED

    performed = await cb.handle(_auth(), _rpc("PerformTransaction", {"id": "tx1"}))
    assert performed["result"]["state"] == STATE_DONE

    checked = await cb.handle(_auth(), _rpc("CheckTransaction", {"id": "tx1"}))
    assert checked["result"]["state"] == STATE_DONE


@pytest.mark.asyncio
async def test_create_idempotent(cb: PaymeCallback) -> None:
    p = {"id": "tx2", "time": 1, "amount": AMOUNT, "account": {"user_id": 42}}
    a = await cb.handle(_auth(), _rpc("CreateTransaction", p))
    b = await cb.handle(_auth(), _rpc("CreateTransaction", p))
    assert a["result"]["transaction"] == b["result"]["transaction"]


@pytest.mark.asyncio
async def test_cancel(cb: PaymeCallback) -> None:
    p = {"id": "tx3", "time": 1, "amount": AMOUNT, "account": {"user_id": 42}}
    await cb.handle(_auth(), _rpc("CreateTransaction", p))
    res = await cb.handle(_auth(), _rpc("CancelTransaction", {"id": "tx3", "reason": 3}))
    assert res["result"]["state"] == STATE_CANCELLED


@pytest.mark.asyncio
async def test_check_missing_tx(cb: PaymeCallback) -> None:
    res = await cb.handle(_auth(), _rpc("CheckTransaction", {"id": "nope"}))
    assert res["error"]["code"] == E_TX_NOT_FOUND


@pytest.mark.asyncio
async def test_statement(cb: PaymeCallback) -> None:
    await cb.handle(_auth(), _rpc("CreateTransaction", {"id": "a", "time": 50, "amount": AMOUNT, "account": {"user_id": 42}}))
    res = await cb.handle(_auth(), _rpc("GetStatement", {"from": 0, "to": 100}))
    assert len(res["result"]["transactions"]) == 1


@pytest.mark.asyncio
async def test_unknown_method(cb: PaymeCallback) -> None:
    res = await cb.handle(_auth(), _rpc("Nope", {}))
    assert res["error"]["code"] == E_METHOD


def test_payment_link() -> None:
    link = payment_link("https://checkout.paycom.uz", "merch1", 42, AMOUNT)
    token = link.rsplit("/", 1)[1]
    decoded = base64.b64decode(token).decode()
    assert "m=merch1" in decoded and "ac.user_id=42" in decoded and f"a={AMOUNT}" in decoded
