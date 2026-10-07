"""Subscription/quota gateway on top of Payme.

Tariffs are in UZS; Payme works in tiyin (1 UZS = 100 tiyin).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from writing_assistant.billing.payme import payment_link
from writing_assistant.db.models import FreeQuota, Subscription

Period = Literal["month", "quarter", "half"]

TARIFFS_UZS: dict[Period, int] = {
    "month": 250_000,
    "quarter": 650_000,
    "half": 1_100_000,
}
PERIOD_DAYS: dict[Period, int] = {"month": 30, "quarter": 90, "half": 180}
FREE_RUNS = 2

# Payme works in tiyin: amount -> period, for validating callbacks.
PERIOD_BY_TIYIN: dict[int, Period] = {uzs * 100: p for p, uzs in TARIFFS_UZS.items()}


def period_for_amount_tiyin(amount: int) -> Period | None:
    return PERIOD_BY_TIYIN.get(amount)


@dataclass(frozen=True)
class SubscriptionStatus:
    active: bool
    expires_at: datetime | None
    free_runs_left: int


class PaymeBillingGateway:
    def __init__(
        self,
        session: AsyncSession,
        *,
        checkout_base: str,
        merchant_id: str,
    ) -> None:
        self._s = session
        self._checkout = checkout_base
        self._merchant = merchant_id

    async def get_status(self, user_id: int) -> SubscriptionStatus:
        now = datetime.now(UTC)
        sub = await self._s.scalar(
            select(Subscription)
            .where(Subscription.user_id == user_id, Subscription.status == "active")
            .order_by(Subscription.expires_at.desc())
        )
        quota = await self._s.get(FreeQuota, user_id)
        used = quota.runs_used if quota else 0
        active = bool(sub and sub.expires_at > now)
        return SubscriptionStatus(
            active=active,
            expires_at=sub.expires_at if sub else None,
            free_runs_left=max(0, FREE_RUNS - used),
        )

    async def can_run_task(self, user_id: int) -> bool:
        status = await self.get_status(user_id)
        return status.active or status.free_runs_left > 0

    async def register_run_consumed(self, user_id: int) -> None:
        status = await self.get_status(user_id)
        if status.active:
            return
        quota = await self._s.get(FreeQuota, user_id)
        if quota is None:
            quota = FreeQuota(user_id=user_id, runs_used=0)
            self._s.add(quota)
        quota.runs_used += 1
        await self._s.commit()

    async def create_payment(self, user_id: int, period: Period) -> str:
        amount_tiyin = TARIFFS_UZS[period] * 100
        return payment_link(self._checkout, self._merchant, user_id, amount_tiyin)

    async def activate(self, user_id: int, period: Period, provider_sub_id: str | None = None) -> None:
        now = datetime.now(UTC)
        sub = Subscription(
            user_id=user_id,
            period=period,
            started_at=now,
            expires_at=now + timedelta(days=PERIOD_DAYS[period]),
            status="active",
            payment_provider="payme",
            provider_sub_id=provider_sub_id,
        )
        self._s.add(sub)
        await self._s.commit()
