import threading
from dataclasses import dataclass

import pytest
from novel_translate.budget import Budget
from novel_translate.models import CallFailed, Charged, OutOfCredit
from novel_translate.pool import run_paid


@dataclass(frozen=True)
class Done:
    item: int
    charged: Charged


class Cancelled(Exception):
    pass


def calls(release: threading.Event, started: list, fail=None):
    def call(_llm, item):
        started.append(item)
        release.wait(5)
        if fail and item in fail:
            raise fail[item]
        return Done(item, Charged(cost=0.1, requests=1))

    return call


def run(items, call, results, *, budget=None, workers=4, progress=lambda n: None):
    return run_paid(
        items, lambda _item: 0.2, call, lambda item, outcome: results.append((item, outcome)),
        new_llm=lambda cancel: object(), budget=budget or Budget(100), workers=workers, progress=progress,
    )  # fmt: skip


def test_all_calls_run_and_their_cost_is_settled():
    release, started, results = threading.Event(), [], []
    release.set()
    budget = Budget(100)
    outcome = run(range(6), calls(release, started), results, budget=budget)
    assert outcome.finished and outcome.calls == 6 and outcome.cost == pytest.approx(0.6)
    assert sorted(item for item, _ in results) == list(range(6))
    assert budget.spent == pytest.approx(0.6) and budget.reserved == pytest.approx(0)


def test_cancel_sends_nothing_more_and_keeps_what_was_in_flight():
    release, started, results = threading.Event(), [], []

    def progress(n):
        release.set()
        raise Cancelled()

    def call(llm, item):
        if item == 0:
            return Done(0, Charged(cost=0.1))
        release.wait(5)
        return Done(item, Charged(cost=0.1))

    with pytest.raises(Cancelled):
        run(range(20), call, results, workers=4, progress=progress)
    assert len(results) == 4  # the first, plus the three in flight when it was cancelled


def test_failed_calls_are_reported_and_the_rest_go_on():
    release, started, results = threading.Event(), [], []
    release.set()
    outcome = run(range(3), calls(release, started, {1: CallFailed("HTTP 500", Charged(cost=0.05))}), results)
    assert outcome.finished
    failed = [o for _, o in results if isinstance(o, CallFailed)]
    assert len(failed) == 1 and outcome.cost == pytest.approx(0.25)


def test_out_of_credit_stops_sending_and_raises_once_in_flight_calls_end():
    release, started, results = threading.Event(), [], []
    release.set()
    with pytest.raises(OutOfCredit):
        run(range(50), calls(release, started, {0: OutOfCredit("402", Charged())}), results, workers=1)
    assert started == [0]


def test_a_refused_reservation_stops_sending():
    release, started, results = threading.Event(), [], []
    release.set()
    outcome = run(range(10), calls(release, started), results, budget=Budget(0.5), workers=1)
    assert not outcome.finished and outcome.calls == 4  # each holds 0.2 and spends 0.1: a fifth would pass 0.5
