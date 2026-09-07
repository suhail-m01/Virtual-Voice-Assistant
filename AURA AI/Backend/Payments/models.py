"""Money and payment intent value objects. Money is integer minor units."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
import re
from typing import Optional


class PaymentStatus(str, Enum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Money:
    minor: int
    currency: str = "INR"

    def __post_init__(self) -> None:
        if not isinstance(self.minor, int) or self.minor <= 0:
            raise ValueError("amount must be a positive integer in minor units")
        if self.currency != self.currency.upper() or not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("currency must be an ISO-4217 code")

    @classmethod
    def from_major(cls, amount: str | int | float | Decimal, currency: str = "INR") -> "Money":
        try:
            value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("invalid monetary amount") from exc
        if value <= 0 or value > Decimal("1000000000"):
            raise ValueError("amount is outside the allowed range")
        return cls(int(value * 100), currency.upper())

    def major_text(self) -> str:
        return f"{Decimal(self.minor) / Decimal(100):,.2f}"


def parse_inr_amount(value: str | int | float | Decimal) -> Money:
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        cleaned = re.sub(r"^(?:₹|rs\.?|inr|rupees?)\s*", "", cleaned, flags=re.I)
        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", cleaned):
            raise ValueError("amount must be a positive INR number")
        value = cleaned
    return Money.from_major(value, "INR")


@dataclass(frozen=True)
class PaymentIntent:
    user_id: str
    amount: Money
    description: str
    operation: str
    approval_reference: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.user_id or not self.description.strip() or len(self.description) > 255:
            raise ValueError("payment description is required and must be short")
        if self.operation not in {"CREATE_PAYMENT_LINK", "CREATE_ORDER"}:
            raise ValueError("unsupported payment operation")
