"""Frank's background information, kept ready (2026-11-14).

Every message to Frank carries a block of background information in his instructions: memory, Alpha Mode, Joshx, personal,
people, finance, operations, trading. It used to be built from the database at the start of every message. On the Mac
that took ~30 s (measured 2026-11-14: finance 21-22 s every run, Joshx 3.1 s, Alpha Mode 2.0 s, the rest ~2 s), because the
Mac reaches the cloud Postgres from South Africa (~0.3 s a query, and the finance summary asks one small question per account
and asset) and the finance section also fetches live Luno prices. Josh waited that long before Frank wrote a word.

Now the block is built in the background and kept ready:
  * refreshed every REFRESH_SECONDS, on a connection borrowed from the pool for one pass and handed straight back (the
    2026-10-06 outage was a connection left idle in a transaction -- `pool.connection()` resets it on exit);
  * refreshed straight away after Frank uses a tool (he may have just changed a memory, a goal or a balance) -- `changed()`;
  * a message uses the ready copy. Only when there is none yet (just after startup) or it is far too old (the refresher
    died) does a message build it itself, as before.
Trade-off Josh accepted: what Frank knows can be up to ~2 minutes old (plus one refresh, ~30 s on the Mac). What he did
himself in this conversation is in the conversation anyway.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

REFRESH_SECONDS = 120
# A ready copy older than this isn't trusted (the refresher must have stopped): the message builds its own, as before.
MAX_AGE_SECONDS = 600

Builder = Callable[[Any], Awaitable[str]]


class FrankContext:
    def __init__(self, builders: list[Builder], refresh_seconds: float = REFRESH_SECONDS, max_age_seconds: float = MAX_AGE_SECONDS):
        self.builders = builders
        self.refresh_seconds = refresh_seconds
        self.max_age_seconds = max_age_seconds
        self.text: str | None = None
        self.built_at = 0.0
        self.last_build_seconds: float | None = None
        self._refreshing: asyncio.Task | None = None
        self._again = False
        self._connect: Callable[[], Any] | None = None   # returns an async context manager yielding a connection (or None)

    async def build(self, conn) -> str:
        started = time.monotonic()
        parts = [await builder(conn) for builder in self.builders]
        self.last_build_seconds = time.monotonic() - started
        return "".join(parts)

    def _fresh_enough(self) -> bool:
        return self.text is not None and time.monotonic() - self.built_at < self.max_age_seconds

    async def get(self, conn) -> str:
        """The block for a message: the ready copy, or (none yet / far too old) one built now on the message's connection."""
        if self._fresh_enough():
            return self.text
        if self._refreshing is not None and not self._refreshing.done():
            # The first build is under way (just after startup): wait for it rather than starting a second one.
            try:
                await asyncio.shield(self._refreshing)
            except Exception:
                pass
            if self._fresh_enough():
                return self.text
        text = await self.build(conn)
        self.text, self.built_at = text, time.monotonic()
        return text

    async def _refresh_once(self) -> None:
        while True:
            self._again = False
            try:
                if self._connect is None:
                    text = await self.build(None)
                else:
                    async with self._connect() as conn:
                        text = await self.build(conn)
                first = self.text is None
                self.text, self.built_at = text, time.monotonic()
                if first:
                    print(f"[frank_context] ready in {self.last_build_seconds:.1f} s ({len(text)} chars); refreshed every {self.refresh_seconds:g} s")
            except Exception as exc:
                print(f"[frank_context] refresh failed: {type(exc).__name__}: {exc}")
            if not self._again:
                return

    def refresh_soon(self) -> None:
        """Start a refresh now, or run one more right after the one under way."""
        if self._refreshing is not None and not self._refreshing.done():
            self._again = True
            return
        try:
            self._refreshing = asyncio.get_running_loop().create_task(self._refresh_once())
        except RuntimeError:
            pass   # no running loop (a script/test): the next get() builds it

    def changed(self) -> None:
        """Frank (or something else) may have changed what the block says."""
        self.refresh_soon()

    async def run(self, connect: Callable[[], Any] | None) -> None:
        """The background loop: build now, then every refresh_seconds."""
        self._connect = connect
        while True:
            self.refresh_soon()
            await asyncio.sleep(self.refresh_seconds)
