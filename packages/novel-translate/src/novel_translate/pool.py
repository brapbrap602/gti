"""Paid model calls on worker threads, under a budget, with one writer.

Each call reserves its estimated cost just before it is submitted, so no more
than `workers` reservations are ever outstanding and the cap is never passed.
Results come back to the calling (coordinating) thread, which alone writes the
stores and reports progress; progress may raise to cancel (Cancelled from a job,
or Ctrl-C), and then the calls already sent are waited for and their paid
results kept before the exception goes on. A second Ctrl-C while waiting gives up
on them. The coordinator wakes every half second, so Ctrl-C works on Windows.
"""

import threading
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Protocol

from novel_translate.budget import Budget, Reservation
from novel_translate.models import LLM, CallFailed, Charged, OutOfCredit

POLL_S = 0.5


class Paid(Protocol):
    charged: Charged


@dataclass(frozen=True)
class PoolResult:
    finished: bool  # False: the budget refused a reservation, so some calls were never sent
    calls: int
    cost: float


def run_paid[P, R: Paid](
    items: Iterable[P],
    reserve: Callable[[P], float],
    call: Callable[[LLM, P], R],
    on_result: Callable[[P, R | CallFailed], None],
    *,
    new_llm: Callable[[threading.Event], LLM],
    budget: Budget,
    workers: int,
    progress: Callable[[int], None],
) -> PoolResult:
    """Run `call` for each item until done or the budget says no.

    `on_result` gets each result or CallFailed on this thread, in completion order.
    Raises OutOfCredit (or a worker's unexpected error) once the calls in flight have ended.
    """
    cancel = threading.Event()
    local = threading.local()

    def work(item: P) -> R:
        if getattr(local, "llm", None) is None:
            local.llm = new_llm(cancel)  # one client per thread: httpx clients are bound to their thread's loop
        return call(local.llm, item)

    pending = iter(items)
    in_flight: dict[Future, tuple[P, Reservation]] = {}
    refused = False
    fatal: BaseException | None = None
    calls, cost = 0, 0.0

    def settle(future: Future) -> None:
        nonlocal fatal, calls, cost
        item, reservation = in_flight.pop(future)
        error = future.exception()
        if error is None or isinstance(error, (CallFailed, OutOfCredit)):
            outcome = future.result() if error is None else error
            spent = outcome.charged.cost
        else:
            outcome, spent = None, reservation.amount  # cost unknown: count the whole hold as spent
        budget.settle(reservation, spent)
        calls, cost = calls + 1, cost + spent
        if outcome is None or isinstance(outcome, OutOfCredit):
            fatal = fatal or error
        else:
            on_result(item, outcome)

    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="paid")
    try:
        while True:
            while not refused and fatal is None and len(in_flight) < workers:
                item = next(pending, _END)
                if item is _END:
                    break
                reservation = budget.reserve(reserve(item))
                if reservation is None:
                    refused = True
                    break
                in_flight[pool.submit(work, item)] = (item, reservation)
            if not in_flight:
                break
            done, _ = wait(in_flight, timeout=POLL_S, return_when=FIRST_COMPLETED)
            for future in done:
                settle(future)
                progress(calls)
    except BaseException:
        cancel.set()  # retry waits end at once; nothing new is sent
        try:
            while in_flight:
                done, _ = wait(in_flight, timeout=POLL_S, return_when=FIRST_COMPLETED)
                for future in done:
                    settle(future)
        except KeyboardInterrupt:  # a second Ctrl-C: stop waiting for them
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        pool.shutdown()
        raise
    pool.shutdown()
    if fatal is not None:
        raise fatal
    return PoolResult(not refused, calls, cost)


_END = object()
