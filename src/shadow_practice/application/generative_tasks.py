"""Small executor wrapper that keeps background work out of wx views."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")


class GenerativeTaskService:
    def __init__(self, max_workers: int = 2):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="generative")
        self._closed = False

    def submit(self, work: Callable[[], T], complete: Callable[[T | None, Exception | None], None]) -> Future[T]:
        if self._closed:
            raise RuntimeError("O executor generativo já foi encerrado.")
        future = self._executor.submit(work)

        def done(result: Future[T]) -> None:
            try:
                complete(result.result(), None)
            except Exception as error:  # Completion decides how to surface errors.
                complete(None, error)

        future.add_done_callback(done)
        return future

    def close(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
