"""Spend against a dollar cap, shared by the threads of one job.

Every call reserves its estimated cost before it is sent and settles with what it
was actually charged, so concurrent calls can never commit more than the cap.
"""

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class Reservation:
    amount: float


class Budget:
    def __init__(self, cap: float):
        if cap <= 0:
            raise ValueError("the cap must be more than $0")
        self.cap = cap
        self._spent = 0.0
        self._reserved = 0.0
        self._lock = threading.Lock()

    def reserve(self, estimate: float) -> Reservation | None:
        """Hold `estimate` dollars, or None when spent + held + estimate would pass the cap."""
        with self._lock:
            if self._spent + self._reserved + estimate > self.cap:
                return None
            self._reserved += estimate
            return Reservation(estimate)

    def settle(self, reservation: Reservation, actual: float) -> None:
        """Release the hold and record the real charge, which may exceed what was held."""
        with self._lock:
            self._reserved -= reservation.amount
            self._spent += actual

    @property
    def spent(self) -> float:
        with self._lock:
            return self._spent

    @property
    def reserved(self) -> float:
        with self._lock:
            return self._reserved
