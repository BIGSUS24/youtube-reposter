"""Tenacity-based retry decorator factory with logging + Discord notification hook."""

from __future__ import annotations

from typing import Callable

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from logger import get_logger
from notifier import COLOR_WARNING

logger = get_logger(__name__)

_MAX_WAIT_SECONDS = 300


def build_retry(
    max_attempts: int,
    base_delay: float,
    notifier=None,
    retry_on: tuple = (Exception,),
    exclude: tuple = (),
) -> Callable:
    """`exclude` lets a subclass of something in `retry_on` opt out of retrying
    (e.g. QuotaExceededError is a YouTubeAPIError but must propagate immediately,
    not be retried like a transient network error)."""

    def before_sleep(retry_state: RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        fn_name = retry_state.fn.__name__ if retry_state.fn else "unknown"
        message = f"{fn_name} attempt {retry_state.attempt_number}/{max_attempts}: {exc}"
        logger.warning(message)
        if notifier is not None:
            notifier.send("Retry attempt", message, color=COLOR_WARNING)

    condition = retry_if_exception_type(retry_on)
    if exclude:
        condition = condition & retry_if_not_exception_type(exclude)

    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=base_delay, min=base_delay, max=_MAX_WAIT_SECONDS)
        + wait_random(0, 3),
        retry=condition,
        reraise=True,
        before_sleep=before_sleep,
    )


def _demo() -> None:
    calls = {"n": 0}

    @build_retry(max_attempts=3, base_delay=0.01, retry_on=(ValueError,))
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("not yet")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3

    @build_retry(max_attempts=2, base_delay=0.01, retry_on=(ValueError,))
    def always_fails() -> None:
        raise ValueError("nope")

    try:
        always_fails()
        raise AssertionError("expected ValueError to propagate")
    except ValueError:
        pass
    print("retry self-check OK")


if __name__ == "__main__":
    _demo()
