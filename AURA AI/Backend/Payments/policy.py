"""Payment lock and TEST/LIVE separation."""
from __future__ import annotations

from dataclasses import dataclass


class PaymentLockedError(PermissionError):
    pass


@dataclass
class PaymentPolicy:
    locked: bool = True
    mode: str = "test"
    live_acknowledged: bool = False

    def __post_init__(self) -> None:
        self.mode = self.mode.lower()
        if self.mode not in {"test", "live"}:
            raise ValueError("payment mode must be test or live")
        if self.mode == "live" and not self.live_acknowledged:
            # Presence of live credentials never flips this flag. The service
            # remains unavailable until deliberate acknowledgement is configured.
            self.locked = True

    @property
    def display_mode(self) -> str:
        return "LIVE MODE" if self.mode == "live" and self.live_acknowledged else "TEST MODE"

    def assert_can_initiate(self) -> None:
        if self.locked:
            raise PaymentLockedError("Payments are locked.")
        if self.mode == "live" and not self.live_acknowledged:
            raise PaymentLockedError("Live payment execution is not acknowledged.")

    def set_lock(self, locked: bool) -> None:
        self.locked = bool(locked)
