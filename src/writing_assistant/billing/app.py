"""FastAPI app exposing the Payme callback endpoint."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Header, Request
from sqlalchemy import select

from writing_assistant.billing.gateway import PERIOD_BY_TIYIN, PERIOD_DAYS, period_for_amount_tiyin
from writing_assistant.billing.payme import (
    STATE_CANCELLED,
    STATE_CANCELLED_AFTER_DONE,
    STATE_CREATED,
    STATE_DONE,
    PaymeCallback,
    PaymeTx,
)
from writing_assistant.core.settings import settings
from writing_assistant.db.models import Subscription, Transaction, User
from writing_assistant.db.session import SessionFactory

app = FastAPI(title="writing-assistant billing")


class SqlMerchantStore:
    """Maps Payme transactions onto the Transaction table."""

    def __init__(self, session_factory: Any = SessionFactory) -> None:
        self._sf = session_factory

    async def resolve_user(self, user_id: int) -> bool:
        async with self._sf() as s:
            return await s.scalar(select(User.id).where(User.id == user_id)) is not None

    async def validate_amount(self, user_id: int, amount: int) -> bool:
        return amount in PERIOD_BY_TIYIN

    async def get_tx(self, tx_id: str) -> PaymeTx | None:
        async with self._sf() as s:
            row = await s.scalar(select(Transaction).where(Transaction.provider_tx_id == tx_id))
            if row is None:
                return None
            return _to_tx(row)

    async def create_tx(self, tx_id: str, user_id: int, amount: int, create_time: int) -> PaymeTx:
        async with self._sf() as s:
            row = Transaction(
                user_id=user_id,
                amount_uzs=amount // 100,
                provider="payme",
                provider_tx_id=tx_id,
                status="created",
                raw_payload={"state": STATE_CREATED, "create_time": create_time},
            )
            s.add(row)
            await s.commit()
            return _to_tx(row)

    async def mark_performed(self, tx_id: str, perform_time: int) -> PaymeTx:
        async with self._sf() as s:
            row = await s.scalar(select(Transaction).where(Transaction.provider_tx_id == tx_id))
            assert row is not None
            row.status = "done"
            row.raw_payload = {**row.raw_payload, "state": STATE_DONE, "perform_time": perform_time}

            period = period_for_amount_tiyin(row.amount_uzs * 100)
            if period is not None:
                now = datetime.now(UTC)
                s.add(
                    Subscription(
                        user_id=row.user_id,
                        period=period,
                        started_at=now,
                        expires_at=now + timedelta(days=PERIOD_DAYS[period]),
                        status="active",
                        payment_provider="payme",
                        provider_sub_id=tx_id,
                    )
                )
            await s.commit()
            return _to_tx(row)

    async def mark_cancelled(self, tx_id: str, cancel_time: int, reason: int) -> PaymeTx:
        async with self._sf() as s:
            row = await s.scalar(select(Transaction).where(Transaction.provider_tx_id == tx_id))
            assert row is not None
            prev = row.raw_payload.get("state", STATE_CREATED)
            state = STATE_CANCELLED_AFTER_DONE if prev == STATE_DONE else STATE_CANCELLED
            row.status = "cancelled"
            row.raw_payload = {**row.raw_payload, "state": state, "cancel_time": cancel_time, "reason": reason}
            await s.commit()
            return _to_tx(row)

    async def statement(self, frm: int, to: int) -> list[PaymeTx]:
        async with self._sf() as s:
            rows = (await s.scalars(select(Transaction).where(Transaction.provider == "payme"))).all()
            out = [_to_tx(r) for r in rows]
            return [t for t in out if frm <= t.create_time <= to]


def _to_tx(row: Transaction) -> PaymeTx:
    p = row.raw_payload or {}
    return PaymeTx(
        id=row.provider_tx_id,
        user_id=row.user_id,
        amount=row.amount_uzs * 100,
        state=int(p.get("state", STATE_CREATED)),
        create_time=int(p.get("create_time", 0)),
        perform_time=int(p.get("perform_time", 0)),
        cancel_time=int(p.get("cancel_time", 0)),
        reason=p.get("reason"),
    )


_callback = PaymeCallback(SqlMerchantStore(), settings.payme_secret_key)


@app.post("/payme/callback")
async def payme_callback(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    body = await request.json()
    return await _callback.handle(authorization, body)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
