"""Per-job metadata shared with that job's asyncio.to_thread workers."""

from contextlib import contextmanager
from contextvars import ContextVar


_state: ContextVar[dict | None] = ContextVar("media_download_state", default=None)


def current_download_state() -> dict | None:
    return _state.get()


@contextmanager
def download_scope():
    # The dict is intentionally mutable: to_thread copies the context, but
    # worker updates must remain visible to the coroutine awaiting that worker.
    token = _state.set({})
    try:
        yield
    finally:
        _state.reset(token)
