"""
Keeps a stuck external drive from freezing the whole backend (2026-10-11).

Why this exists: on 2026-10-10 Josh's exFAT SSD stopped answering folder listings for 10+ minutes (the mount stayed up and
`stat` on known paths worked, but `ls` hung with zero disk activity). Request handlers read and write that drive with
plain blocking calls (list a folder, read a plan, save a file), and a blocking call inside an `async def` handler stops
the one event loop every request shares. `/health` then stopped answering, and the hang watchdog (main.py,
`_start_hang_watchdog`: 3 failed /health checks = `os._exit(1)`) restarted the backend, twice.

`on_drive(fn, *args)` runs the blocking work on a separate set of threads and waits for it with a time limit:

  * the event loop never blocks, so /health, the other screens and the chat keep working while the drive is stuck;
  * if the drive doesn't answer in time the caller gets `DriveNotResponding` (main.py turns it into a plain 503);
  * after one timeout the breaker opens: further drive calls fail at once for BREAKER_SECONDS instead of piling more
    stuck threads on a drive that can't answer. After that, the next call is let through as a trial; if it succeeds
    the breaker closes again.

Limits, stated plainly: a thread already stuck inside the drive cannot be killed -- it finishes if and when the drive
comes back (so a write that "timed out" may still land later; the message says so). Only handler-level file work goes
through here; ffmpeg runs as its own subprocess and can't block the loop in the first place.
"""

import asyncio
import functools
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

T = TypeVar("T")

DEFAULT_TIMEOUT_SECONDS = 10.0  # ordinary drive work takes milliseconds; a slow USB wake-up takes a few seconds
BREAKER_SECONDS = 20.0

# Its own thread pool: threads stuck on a dead drive must not starve the default executor other code relies on.
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="drive")

_state: dict[str, Any] = {"open_until": 0.0, "stalled_at": None, "stalls": 0}


class DriveNotResponding(RuntimeError):
    """The drive didn't answer in time (or is known to be stuck right now)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _message(writing: bool, waited: float | None) -> str:
    base = ("The SSD isn't responding right now" + (f" (no answer in {waited:.0f} seconds)" if waited else " (it stopped answering a moment ago)") + ". "
            "Check that it's connected and not busy, then try again.")
    return base + (" This action may or may not have gone through -- check again once the drive is back." if writing else " Nothing was changed.")


def drive_status() -> dict[str, Any]:
    """For /status: is the drive answering, when it last stalled, and how many times since the backend started."""
    now = time.monotonic()
    return {"responsive": now >= _state["open_until"], "last_stall_at": _state["stalled_at"], "stalls_since_start": _state["stalls"]}


def reset() -> None:
    """Closes the breaker (tests; nothing in the app needs it)."""
    _state.update({"open_until": 0.0, "stalled_at": None, "stalls": 0})


async def on_drive(fn: Callable[..., T], *args: Any, timeout: float | None = None, writing: bool = False, **kwargs: Any) -> T:
    """Runs `fn(*args, **kwargs)` (blocking drive work) off the event loop and returns its result. Exceptions `fn` raises
    come back unchanged. Raises DriveNotResponding on a timeout or while the breaker is open."""
    now = time.monotonic()
    if now < _state["open_until"]:
        raise DriveNotResponding(_message(writing, None))
    limit = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(_EXECUTOR, functools.partial(fn, *args, **kwargs))
    try:
        return await asyncio.wait_for(future, limit)
    except asyncio.TimeoutError:
        if future.done() and not future.cancelled():
            return future.result()  # the call itself finished (or raised its own TimeoutError): not a stalled drive
        _state["open_until"] = time.monotonic() + BREAKER_SECONDS
        _state["stalled_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _state["stalls"] += 1
        print(f"[drive] not responding: {getattr(fn, '__name__', 'drive call')} gave no answer in {limit:.0f}s; failing drive requests fast for {BREAKER_SECONDS:.0f}s")
        raise DriveNotResponding(_message(writing, limit)) from None
