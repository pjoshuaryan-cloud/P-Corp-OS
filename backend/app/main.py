"""
P Corp OS backend. Proves the IPC contract decided in TECH_STACK.md (local
HTTP + WebSocket via FastAPI, bound to 127.0.0.1) and carries real Claude
reasoning through it — via the plain `anthropic` package, not the full
Claude Agent SDK.

That's a deliberate, confirmed scoping decision: the Agent SDK turned out to
require installing the actual Claude Code CLI and brings full tool-use
capabilities (file access, bash execution) with it. SECURITY.md's agent-
sandboxing/permission model doesn't exist yet, so giving Frank general
tool-use before that's designed would be running ahead of an unresolved
decision, not just a technical step.

Frank has two tools (app/memory.py's `save_memory` and `forget_memory`) via
the plain SDK's tool-use/function-calling — a different, much smaller risk
category than the deferred Agent SDK: hardcoded actions, no file or shell
access, confirmed with Joshua specifically (2026-07-24) as distinct from the
general tool-use deferral above. `forget_memory` is a soft-delete
(app/db.py's `deleted_at`), not a real DELETE — that reversibility is what
keeps it in the same "regular" permission tier as save_memory.

Conversation history persists in SQLite (app/db.py) as real conversations —
reopened from the earlier "one continuous conversation" decision based on
real usage (Joshua wanted to start fresh chats once he actually used the
thread). Durable memory (app/memory.py), not the transcript, is what now
carries "there is only ever one Frank" forward — see app/db.py's docstring.
Every route now checks a local auth token (app/auth.py) — SECURITY.md's
first concrete fix, closing the "any local process can connect" gap.

Notifications (Layer 1's responsibility per FOUNDER_BRIEF.md, TECH_STACK.md's
already-decided "WebSocket carries unprompted push notifications from Frank
to the UI") ride the same WebSocket as chat text, via a "\n[notify]" sentinel
— same pattern as the existing "\n[done]" end-of-turn marker, not a new
message envelope. Triggered by the one thing Frank already does
deterministically (save_memory firing), not a new "should Frank decide to
notify" policy — that's a bigger, fuzzier design question for later.

Still NOT here: semantic/vector search over memory, the full per-device-
keypair auth, SMAppService packaging.
"""

import asyncio
import base64
import json
import os
import secrets
import threading
import urllib.error
import urllib.request
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import httpx
import psycopg
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.alpha_mode_agent import (
    ALPHA_MODE_AGENT_TOOL_NAMES,
    ALPHA_MODE_AGENT_TOOLS,
    execute_alpha_mode_agent_tool_call,
)
from app.alpha_mode_db import init_alpha_mode_db
from app.alpha_mode_supabase import dashboard_snapshot as alpha_mode_dashboard_snapshot
from app.alpha_mode_tools import ALPHA_MODE_TOOLS, build_alpha_mode_block, execute_alpha_mode_tool_call
from app.auth import get_or_create_token
from app.auth_db import create_device_session, init_auth_db, verify_device_session
from app.agents_registry import list_agents
from app.audit_db import init_audit_db, record_tool_call
from app.automations import check_and_fire as check_and_fire_automation
from app.automations_db import init_automations_db, list_runs as list_automation_runs
from app.automation_rules_db import (
    init_automation_rules_db,
    list_rules as list_automation_rules,
    set_rule_enabled as set_automation_rule_enabled,
    delete_rule as delete_automation_rule,
)
from app.automation_tools import AUTOMATION_TOOL_NAMES, AUTOMATION_TOOLS, execute_automation_tool_call
from app.communications_agent import (
    COMMUNICATIONS_AGENT_TOOL_NAMES,
    COMMUNICATIONS_AGENT_TOOLS,
    execute_communications_agent_tool_call,
)
from app.creative_director_agent import (
    CREATIVE_DIRECTOR_AGENT_TOOL_NAMES,
    CREATIVE_DIRECTOR_AGENT_TOOLS,
    execute_creative_director_agent_tool_call,
)
from app.design_agent import DESIGN_AGENT_TOOL_NAMES, DESIGN_AGENT_TOOLS, execute_design_agent_tool_call
from app.debate import DEBATE_TOOL_NAMES, DEBATE_TOOLS, execute_debate_tool_call
from app.knowledge import list_docs as list_knowledge_docs, read_doc as read_knowledge_doc
from app.personal_db import dashboard_snapshot as personal_dashboard_snapshot, init_personal_db
from app.personal_tools import PERSONAL_TOOL_NAMES, PERSONAL_TOOLS, build_personal_block, execute_personal_tool_call
from app.joshx_db import (
    PROJECT_PAYMENT_STATUS_VALUES,
    PROJECT_STATUS_VALUES,
    compute_performance_metrics as joshx_performance_metrics,
    dashboard_snapshot as joshx_dashboard_snapshot,
    delete_client_by_id,
    delete_lead_by_id,
    delete_project_by_id,
    init_joshx_db,
    set_project_payment_status_by_id,
    set_project_status_by_id,
)
from app.joshx_tools import JOSHX_TOOL_NAMES, JOSHX_TOOLS, build_joshx_block, execute_joshx_tool_call
from app.people_db import dashboard_snapshot as people_dashboard_snapshot, init_people_db
from app.people_tools import PEOPLE_TOOL_NAMES, PEOPLE_TOOLS, build_people_block, execute_people_tool_call
from app.finance_db import (
    dashboard_snapshot as finance_dashboard_snapshot,
    get_balance_history,
    get_hf_markets_schedule,
    get_luno_schedule,
    init_finance_db,
)
from app.calendar_tools import CALENDAR_TOOL_NAMES, CALENDAR_TOOLS, execute_calendar_tool_call
from app.calendar_db import init_calendar_db, sync_calendar_cache
from app.system_calendar import check_calendar_available
from app.email_db import init_email_db
from app.email_tools import EMAIL_TOOL_NAMES, EMAIL_TOOLS, execute_email_tool_call
from app import google_oauth
from app.finance_tools import FINANCE_TOOL_NAMES, FINANCE_TOOLS, build_finance_block, execute_finance_tool_call
from app.documents import DOCS_DIR, DOCUMENTS_TOOL_NAMES, DOCUMENTS_TOOLS, execute_documents_tool_call
from app.supabase_storage import download_document
from app.finance import (
    compute_concentration_metrics,
    compute_luno_zar_value,
    get_hf_markets_live_status,
    maybe_snapshot_hf_markets,
    maybe_snapshot_luno,
)
from app.market_movers import maybe_snapshot_market_prices
from app.trading_division import build_trading_division_block, dashboard_snapshot as trading_division_dashboard_snapshot
from app.trading_division_agent import (
    TRADING_DIVISION_AGENT_TOOL_NAMES,
    TRADING_DIVISION_AGENT_TOOLS,
    execute_trading_division_agent_tool_call,
)
from app.legacy_vault import LEGACY_VAULT_TOOL_NAMES, LEGACY_VAULT_TOOLS, execute_legacy_vault_tool_call
from app.memory_agent import MEMORY_AGENT_TOOL_NAMES, MEMORY_AGENT_TOOLS, execute_memory_agent_tool_call
from app.operations_agent import OPERATIONS_TOOL_NAMES, OPERATIONS_TOOLS, build_operations_block, execute_operations_tool_call
from app.research_agent import RESEARCH_AGENT_TOOL_NAMES, RESEARCH_AGENT_TOOLS, execute_research_agent_tool_call
from app.web_tools import SERVER_TOOL_LABELS, WEB_TOOLS
from app.engineering_agent import (
    ENGINEERING_AGENT_TOOL_NAMES,
    ENGINEERING_AGENT_TOOLS,
    execute_engineering_agent_tool_call,
)
from app.brief import compute_brief
from app.insights import compute_insights
from app.situation_room import compute_situation_room_alerts
from app.connected_apps import (
    CONNECTED_APPS_TOOL_NAMES,
    CONNECTED_APPS_TOOLS,
    compute_connected_apps_status,
    execute_connected_apps_tool_call,
    refresh_connected_apps_cache,
)
from app.search import search_all
from app.triggers import compute_status as compute_trigger_status, maybe_run_daily_digest, run_daily_digest
from app.triggers_db import (
    get_digest_schedule,
    get_market_movers_schedule,
    init_triggers_db,
    list_rules as list_trigger_rules,
    set_rule_enabled,
)
from app.operations_db import init_operations_db, list_open_tasks
from app.db import (
    clear_credits_exhausted,
    create_new_conversation,
    forget_memory_by_id,
    get_active_conversation_id,
    get_credits_exhausted_since,
    get_focus_objective,
    get_local_node_last_seen_at,
    init_db,
    list_conversations,
    load_history,
    load_memory_records,
    log_activity,
    mark_local_node_seen,
    save_message,
    set_active_conversation,
    set_credits_exhausted,
)
from app.memory import FORGET_MEMORY_TOOL, SAVE_MEMORY_TOOL, build_memory_block, execute_tool_call
from app.focus import FOCUS_TOOL_NAMES, FOCUS_TOOLS, execute_focus_tool_call
from app.tool_labels import label_for_tool
from app.document_attachments import (
    ATTACHMENT_CAPABILITY_NOTE,
    ATTACHMENTS_DIR,
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS_PER_MESSAGE,
    MAX_TOTAL_ATTACHMENT_BYTES,
    build_content_block,
)
from app.data_analysis import DATA_ANALYSIS_TOOL_NAMES, DATA_ANALYSIS_TOOLS, execute_data_analysis_tool_call

# Real bug found live (2026-09-05): uvicorn/websockets defaults to a 16MB
# max frame size -- MAX_TOTAL_ATTACHMENT_BYTES (40MB raw) inflates to
# ~55MB once base64-encoded plus JSON structure, well past that default.
# Without raising this, an oversized message never reaches the graceful,
# in-band "[Attached file ... too large]" text block at all -- the
# websocket connection itself gets killed first with a raw protocol error
# (confirmed live: `ConnectionClosedError: ... message too big ... exceeds
# limit of 16777216 bytes`), exactly the "confusing raw error deep in the
# stack" outcome this whole size-cap design was supposed to prevent. Set
# comfortably above MAX_TOTAL_ATTACHMENT_BYTES's own worst-case inflation
# so the application-level cap is what actually governs, not this one.
WS_MAX_SIZE = 64 * 1024 * 1024

# Reliability pass (2026-09-07): one shared constant, reused by every real
# uvicorn bind below and by the hang-watchdog's own health check, so they
# can't silently drift apart the way three independent literal 8731s could.
BACKEND_PORT = 8731
from app.decision_journal import (
    DECISION_JOURNAL_TOOL_NAMES,
    DECISION_JOURNAL_TOOLS,
    execute_decision_journal_tool_call,
)
from app.memory_graph import MEMORY_GRAPH_TOOL_NAMES, MEMORY_GRAPH_TOOLS, execute_memory_graph_tool_call
from app.shadow_mode import SHADOW_MODE_TOOL_NAMES, SHADOW_MODE_TOOLS, execute_shadow_mode_tool_call
from app.personality import SYSTEM_PROMPT
from app.piper_tts import synthesize_wav_bytes

# Explicit path, not load_dotenv()'s default cwd-search — found directly
# (2026-07-28) while testing the SMAppService packaging shim, which can be
# launched from any working directory: load_dotenv() with no argument
# searches from the process's cwd, not from this file's own location, so it
# silently found no .env and left ANTHROPIC_API_KEY unset. Same class of bug
# as the Swift-side cwd assumptions fixed in ProjectPaths.swift — deriving
# from __file__ instead of cwd is the actual fix, not a workaround.
load_dotenv(Path(__file__).parent.parent / ".env")

# Stage 4 prep (2026-09-10): a dual-backend read path, proven against a
# local Postgres instance ahead of any real cloud one existing. Deliberately
# a different variable from the Stage 3 migration tool's own
# MIGRATION_POSTGRES_DSN (app/migration/replicate.py) -- that's a one-off
# script's destination, this is the live app's read source; today they'd
# point at the same local database for testing, but they're different
# concerns that could legitimately diverge later (e.g. testing a fresh
# migration while the live app keeps reading an already-verified copy).
# Defaults to "sqlite" -- today's exact, unchanged behavior -- so leaving
# this unset changes nothing about the other 11 domains or any write route.
DATA_BACKEND = os.environ.get("DATA_BACKEND", "sqlite")
CLOUD_POSTGRES_DSN = os.environ.get("CLOUD_POSTGRES_DSN")

MODEL = "claude-sonnet-5"
# Real bug found 2026-07-31: 1024 was cutting off longer replies mid-
# generation (confirmed directly -- a multi-phase SOP relayed from the
# Operations Agent got truncated, twice, in real use). Raising the
# ceiling doesn't undo personality.py's brevity instruction for ordinary
# replies -- that's a soft prompt-level default, not a hard token cap --
# it just stops hard-truncating the genuinely longer replies (relaying a
# drafted document, etc.) that need more room.
MAX_TOKENS = 4096
AUTH_TOKEN = get_or_create_token()

# Optional — cloud text-to-speech (see .env.example). Confirmed decision
# (2026-07-29): tried free-tier ElevenLabs first, which turned out to
# block API access to Voice Library voices entirely; then a genuinely
# free local fallback (Piper, app/piper_tts.py); then Joshua decided the
# specific stylized "dark and tough" character voice was worth actually
# paying for. Both paths are kept, not because the free one is a
# placeholder, but because we've already hit two different real
# ElevenLabs failures in one sitting (missing permission, then payment
# required) — /speak below tries ElevenLabs first when configured, and
# falls back to Piper on ANY failure, so Frank never just goes silent.
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID")


ALPHA_MODE_TOOL_NAMES = {tool["name"] for tool in ALPHA_MODE_TOOLS}


class SpeakRequest(BaseModel):
    text: str


class ActivityLogRequest(BaseModel):
    app_name: str


class RegisterDeviceRequest(BaseModel):
    device_name: str


async def verify_token(token: str, request: Request) -> None:
    # Stage 7 prep (2026-09-10): additive, not a replacement -- today's
    # real AUTH_TOKEN keeps working unmodified (the desktop/iOS apps
    # already deployed use it, indefinitely), and a valid per-device
    # session (auth_db.py) is now ALSO accepted. A request must satisfy
    # one of the two; neither existing route protection is weakened, nor
    # is any new route left unprotected.
    #
    # request: Request added (2026-09-11, iPhone independence pass) so
    # this dependency can read app.state.postgres_conn itself -- FastAPI
    # resolves it automatically for every one of the 44+ Depends(verify_token)
    # call sites with zero changes needed at any of them.
    if token == AUTH_TOKEN:
        return
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    if await verify_device_session(token, postgres_conn):
        return
    raise HTTPException(status_code=403, detail="invalid or missing token")


# Proactive Triggers Layer's scheduler (2026-08-21) -- the first time-based
# background loop in this backend (every prior "automation" is event-
# driven, fired inline from tool-dispatch; see triggers_db.py's docstring).
# A plain asyncio loop, not a new dependency like APScheduler -- one job,
# checked a few times an hour, doesn't earn a scheduling library. 15
# minutes is frequent enough that the digest fires within 15min of
# send_hour without polling so tightly it'd matter if a tick's work took a
# while; maybe_run_daily_digest() itself is a no-op past the first
# successful run each day.
TRIGGER_CHECK_INTERVAL_SECONDS = 900


async def _trigger_scheduler_loop() -> None:
    while True:
        # Stage 6 prep: same guarded app.state.postgres_conn access as
        # Stage 5's WebSocket call site -- None on every real deployment
        # today (DATA_BACKEND unset), so this changes nothing unless
        # that's explicitly configured.
        postgres_conn = getattr(app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
        try:
            await maybe_run_daily_digest(postgres_conn)
        except Exception as exc:
            print(f"[triggers] scheduler tick failed: {exc}")
        try:
            # Finance's daily Luno balance snapshot (2026-08-21) rides
            # this same tick rather than starting a second background
            # loop -- see app/finance.py's own docstring.
            await maybe_snapshot_luno(postgres_conn)
        except Exception as exc:
            print(f"[finance] Luno snapshot tick failed: {exc}")
        try:
            # HF Markets' daily balance snapshot (2026-08-24) -- same
            # shared-tick reasoning as Luno's above.
            await maybe_snapshot_hf_markets(postgres_conn)
        except Exception as exc:
            print(f"[finance] HF Markets snapshot tick failed: {exc}")
        try:
            # Market movers' daily price-history snapshot (2026-08-25) --
            # same shared-tick reasoning as Luno/HF Markets above.
            await maybe_snapshot_market_prices(postgres_conn)
        except Exception as exc:
            print(f"[triggers] market movers snapshot tick failed: {exc}")
        try:
            # Reliability pass (2026-09-07): Connected Apps' cache, feeding
            # situation_room.py's disconnection alert. Not gated to once a
            # day like the three jobs above -- it re-checks unconditionally
            # every tick, see connected_apps.py's own docstring.
            await refresh_connected_apps_cache(postgres_conn)
        except Exception as exc:
            print(f"[connected_apps] cache refresh tick failed: {exc}")
        await asyncio.sleep(TRIGGER_CHECK_INTERVAL_SECONDS)


# Google Calendar sync (2026-08-27) -- a second periodic loop rather than
# folding into _trigger_scheduler_loop above, since this one needs its own
# cadence (calendar events change often enough that 15 minutes is worth
# keeping tight, independent of the Triggers/Finance ticks living on the
# same 900s interval already). Keeps the cache in calendar_db.py warm so
# list_calendar_events reads it instantly rather than paying Google API
# latency on every Frank turn. A no-op (fails soft, returns immediately)
# until Google is actually connected via /auth/google/start.
CALENDAR_SYNC_INTERVAL_SECONDS = 900


async def _calendar_sync_loop() -> None:
    while True:
        # Same guarded app.state access as _trigger_scheduler_loop -- this
        # loop only ever runs in Mac mode (never started in cloud mode, see
        # run()), but still writes to shared Postgres when DATA_BACKEND=
        # postgres so the cloud instance's own reads see the same fresh
        # calendar data, not a Mac-only-visible cache.
        postgres_conn = getattr(app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
        try:
            await sync_calendar_cache(postgres_conn)
        except Exception as exc:
            print(f"[calendar] sync tick failed: {exc}")
        await asyncio.sleep(CALENDAR_SYNC_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Real bug found live during the reliability pass (2026-09-07): adding
    # a nullable app_state column (db.py's credits_exhausted_since)
    # crashed startup with "sqlite3.OperationalError: duplicate column
    # name" -- _run_dual's two concurrent lifespan entries (see the
    # elevenlabs_client/scheduler-task guards below) both ran init_db()'s
    # check-then-ALTER migration at the same time, so both saw the column
    # missing before either had committed adding it. CREATE TABLE IF NOT
    # EXISTS tolerates a concurrent double-run fine, which is presumably
    # why this block was never guarded before -- but a plain ALTER TABLE
    # migration doesn't, and every init_*_db() function has at least one.
    # Same app.state guard as the block below, just covering this whole
    # sequence instead of one task/client each. Critically, the flag is
    # set BEFORE any of the awaits below, not after: both lifespan
    # entries run on the same single-threaded event loop, so a plain
    # synchronous check-then-set with no `await` between them can't be
    # interleaved by the other coroutine -- setting it only after all the
    # awaits finished would reopen the exact same race, since the second
    # entry could reach this check during any one of those await points.
    if not hasattr(app.state, "db_initialized"):
        app.state.db_initialized = True
        await init_db()
        await init_alpha_mode_db()
        await init_operations_db()
        await init_personal_db()
        await init_joshx_db()
        await init_people_db()
        await init_finance_db()
        await init_automations_db()
        await init_automation_rules_db()
        await init_audit_db()
        await init_triggers_db()
        await init_email_db()
        await init_calendar_db()
        await init_auth_db()
    # A single reused httpx client, not one per /speak call — real bug
    # found and fixed 2026-07-30: creating a fresh AsyncClient() per
    # request meant paying a full DNS+TLS handshake to ElevenLabs every
    # single time, confirmed directly (curl timing showed the exact same
    # request taking 4.9s cold vs 1.1s with a warm connection). One
    # long-lived client with connection keep-alive removes that entirely.
    # Real bug found live (2026-08-24, via Finance's Luno snapshot
    # writing every asset twice with identical timestamps): when
    # TAILSCALE_IP is set, run() below starts TWO uvicorn.Server
    # instances against this same `app` object (_run_dual -- one for
    # 127.0.0.1, one for the Tailscale IP). Each server's ASGI lifecycle
    # independently enters this lifespan on startup, so without a guard,
    # both the ElevenLabs client and the scheduler task were being
    # created twice -- two competing copies of _trigger_scheduler_loop
    # racing in the same process, both hitting the same SQLite files.
    # `app.state` is the one thing genuinely shared between both
    # lifespan entries (same Python object underneath), so it's used
    # here as the guard. This was pre-existing and affected the Triggers
    # Layer's own digest scheduling too, not just Finance -- Finance's
    # snapshot just made it visible first.
    if not hasattr(app.state, "elevenlabs_client"):
        app.state.elevenlabs_client = httpx.AsyncClient(timeout=30.0)
    # Stage 4 prep: only touched when DATA_BACKEND=postgres is explicitly
    # set -- SQLite-mode startup (today's default, every real deployment
    # right now) never reaches this block at all. Fails loud on a missing/
    # unreachable DSN rather than silently falling back to SQLite, matching
    # this codebase's own "fail loud on config errors" discipline elsewhere
    # (e.g. digest_notification.py's check=True) -- a silent fallback here
    # would mean a misconfigured cloud-read test looked like it passed
    # while actually still reading local SQLite the whole time.
    if DATA_BACKEND == "postgres" and not hasattr(app.state, "postgres_conn"):
        if not CLOUD_POSTGRES_DSN:
            raise RuntimeError("DATA_BACKEND=postgres requires CLOUD_POSTGRES_DSN to be set.")
        app.state.postgres_conn = await psycopg.AsyncConnection.connect(CLOUD_POSTGRES_DSN)
    # Cloud mode never runs these loops at all (2026-09-10): there's no
    # lock of any kind (advisory or otherwise) preventing the Mac and a
    # cloud instance from both independently running the daily digest,
    # Luno/HF Markets/market-mover snapshots, and calendar sync against
    # the same shared Postgres once more domains go live there -- rather
    # than build new distributed-locking infrastructure, the Mac stays the
    # sole runner of background jobs, exactly today's behavior. This is
    # also the only place the digest's Mac-only notification delivery
    # could run anyway, so it's not a real loss.
    if not os.environ.get("PORT"):
        if not hasattr(app.state, "trigger_scheduler_task"):
            app.state.trigger_scheduler_task = asyncio.create_task(_trigger_scheduler_loop())
        if not hasattr(app.state, "calendar_sync_task"):
            app.state.calendar_sync_task = asyncio.create_task(_calendar_sync_loop())
    yield
    if hasattr(app.state, "trigger_scheduler_task"):
        app.state.trigger_scheduler_task.cancel()
        del app.state.trigger_scheduler_task
    if hasattr(app.state, "calendar_sync_task"):
        app.state.calendar_sync_task.cancel()
        del app.state.calendar_sync_task
    if hasattr(app.state, "elevenlabs_client"):
        await app.state.elevenlabs_client.aclose()
        del app.state.elevenlabs_client
    if hasattr(app.state, "postgres_conn"):
        await app.state.postgres_conn.close()
        del app.state.postgres_conn


app = FastAPI(title="P Corp OS Backend", lifespan=lifespan)
# Just the apple-touch-icon for now (mobile.html's "Add to Home Screen"
# support) -- unauthenticated like /mobile itself, since it's a static
# icon with no sensitive content.
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/health")
async def health(_: None = Depends(verify_token)) -> dict[str, str]:
    return {"status": "ok"}


@app.get("/status")
async def status(request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    # Real observability endpoint (2026-09-09, Infrastructure Independence
    # Stage 2) -- deliberately separate from /health above, not an
    # extension of it: the hang-watchdog calls /health every 30s expecting
    # a fast response within a 2s timeout, and a real DB/integration check
    # here could itself run slow under real load, which would make the
    # watchdog misdiagnose a slow check as a hung process. Every field
    # below traces to a real, already-existing check -- no fabricated
    # status, same discipline connected_apps.py/trading_division.py
    # already apply to their own domains.
    try:
        await get_active_conversation_id(postgres_conn)
        database_reachable = True
    except Exception:
        database_reachable = False

    integrations = await compute_connected_apps_status(postgres_conn)
    digest_schedule = await get_digest_schedule(postgres_conn)
    market_movers_schedule = await get_market_movers_schedule(postgres_conn)
    luno_schedule = await get_luno_schedule(postgres_conn)
    hf_markets_schedule = await get_hf_markets_schedule(postgres_conn)

    # Stage 8 prep: "Is the Mac Local Node online?" -- answered here rather
    # than fabricated. 150s = 2.5x the 60s heartbeat interval
    # (ActivityTracker.swift), tolerating one missed beat without flapping
    # to "offline" on ordinary network jitter.
    #
    # Real bug found live: SQLite's datetime('now') (used to write
    # local_node_last_seen_at) returns UTC, not local time -- comparing it
    # against datetime.now() (local) made "online" false immediately after
    # a fresh heartbeat on any machine not already at UTC+0. Both sides
    # must be UTC: naive-UTC now, compared against the naive-UTC string
    # SQLite actually stored.
    local_node_last_seen = await get_local_node_last_seen_at(postgres_conn)
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    local_node_online = (
        local_node_last_seen is not None
        and (now_utc - datetime.fromisoformat(local_node_last_seen)).total_seconds() < 150
    )
    # Second Local Node capability (2026-09-10): a live check each call,
    # not cached -- it's a local subprocess call (~1s), not a network
    # round trip, and /status isn't on any hot polling path today
    # (confirmed during the audit: no Swift-side caller exists yet).
    # Structured under "capabilities" deliberately, leaving room for
    # Trading Division/HF Markets to land the same way later.
    calendar_available = await check_calendar_available()

    return {
        "backend": "online",
        "database_reachable": database_reachable,
        "credits_exhausted_since": await get_credits_exhausted_since(postgres_conn),
        "integrations": integrations,
        "background_jobs": {
            "daily_digest": digest_schedule,
            "market_movers_snapshot": market_movers_schedule,
            "luno_snapshot": luno_schedule,
            "hf_markets_snapshot": hf_markets_schedule,
        },
        "local_node": {
            "last_seen_at": local_node_last_seen,
            "online": local_node_online,
            "capabilities": {
                "calendar": {"available": calendar_available},
            },
        },
    }


@app.get("/mobile")
async def mobile() -> Response:
    # Deliberately unauthenticated at the route level -- this is a static
    # page shell with no sensitive content of its own (see mobile.html);
    # it prompts for the real auth token client-side, which is what
    # actually gates the WebSocket/REST calls that matter. Reachable only
    # via this Mac's Tailscale IP (see run()/TAILSCALE_IP) or localhost,
    # never the public internet.
    html = (Path(__file__).parent / "mobile.html").read_text()
    return Response(content=html, media_type="text/html")


# In-memory only, single-user, single-Mac -- this backend never has more
# than one in-flight OAuth attempt at a time, so a plain module-level
# variable is enough state for the CSRF check between /start and
# /callback. Not persisted, so a restart mid-flow just means the state
# check fails and Josh re-starts the flow, which is a fine failure mode.
_google_oauth_state: str | None = None


@app.get("/auth/google/start")
async def auth_google_start() -> RedirectResponse:
    # Deliberately unauthenticated at the route level, same reasoning as
    # /mobile above: this backend is only reachable via Tailscale/
    # localhost by design, and this flow's real security boundary is
    # Google's own login screen, not this app's local token.
    global _google_oauth_state
    _google_oauth_state = secrets.token_urlsafe(16)
    return RedirectResponse(google_oauth.get_authorization_url(_google_oauth_state))


@app.get("/auth/google/callback")
async def auth_google_callback(
    request: Request, code: str | None = None, state: str | None = None, error: str | None = None
) -> Response:
    global _google_oauth_state
    if error:
        body = f"<html><body><h3>Google sign-in was cancelled or failed: {error}</h3></body></html>"
    elif not code or not state or state != _google_oauth_state:
        body = "<html><body><h3>This sign-in link is invalid or expired -- start again from P Corp OS.</h3></body></html>"
    else:
        postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
        ok = await google_oauth.exchange_code_for_tokens(code, postgres_conn)
        _google_oauth_state = None
        if ok:
            body = "<html><body><h3>Connected. You can close this tab -- P Corp OS is now connected to Google.</h3></body></html>"
        else:
            body = "<html><body><h3>Something went wrong exchanging the authorization code. Try again.</h3></body></html>"
    return Response(content=body, media_type="text/html")


@app.get("/auth/google/status")
async def auth_google_status(request: Request, _: None = Depends(verify_token)) -> dict[str, bool]:
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return {"connected": await google_oauth.is_connected(postgres_conn)}


@app.post("/auth/register-device")
async def register_device(body: RegisterDeviceRequest, token: str, request: Request) -> dict[str, str]:
    # Stage 7 prep: deliberately gated by today's real AUTH_TOKEN directly,
    # not Depends(verify_token) -- minting a NEW per-device session can't
    # itself require an existing device session (nothing to bootstrap
    # from). Possessing today's one shared secret is what lets you mint a
    # new, distinct per-device credential going forward -- the exact same
    # trust boundary that exists today, just the starting point for
    # something better rather than a new hole.
    if token != AUTH_TOKEN:
        raise HTTPException(status_code=403, detail="invalid or missing token")
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    new_token = await create_device_session(body.device_name, postgres_conn)
    return {"token": new_token}


@app.get("/connected-apps")
async def connected_apps_endpoint(request: Request, _: None = Depends(verify_token)) -> list[dict]:
    # First real UI surface for connection health on Gmail/Calendar/
    # Supabase -- see app/connected_apps.py's docstring for why each
    # row's "connected"/"last synced" means something different per
    # service. Supersedes GET /auth/google/status for UI purposes (that
    # endpoint has had zero Swift call sites since it shipped 2026-08-27);
    # left in place since nothing else calls it either.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await compute_connected_apps_status(postgres_conn)


@app.get("/memory")
async def memory(request: Request, _: None = Depends(verify_token)) -> list[dict]:
    # View of what Frank has saved via the save_memory tool, excluding
    # anything forgotten (app/db.py's deleted_at) — the desktop shell's
    # "Frank" section reads this to make memory visible, rather than it
    # only being inspectable by querying SQLite directly.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await load_memory_records(postgres_conn)


@app.get("/operations/tasks")
async def operations_tasks(request: Request, _: None = Depends(verify_token)) -> list[dict]:
    # Makes the "Agents" nav section's task list real, rather than only
    # visible to Frank himself via the system-prompt snapshot.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await list_open_tasks(postgres_conn)


@app.get("/agents")
async def agents_endpoint(_: None = Depends(verify_token)) -> list[dict]:
    # Backs the "Agents" section's list of specialist cards -- see
    # agents_registry.py's docstring for why this is a small hand-kept
    # list rather than introspecting main.py's tool-use schemas.
    return await list_agents()


@app.get("/automations/rules")
async def automations_rules(request: Request, _: None = Depends(verify_token)) -> list[dict]:
    # Backs the "Automations" section's list of configured rules --
    # real, persisted, user-creatable rules (automation_rules_db.py) as
    # of 2026-09-06, not a hardcoded Python list.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await list_automation_rules(postgres_conn)


@app.get("/automations/runs")
async def automations_runs(request: Request, _: None = Depends(verify_token)) -> list[dict]:
    # Backs the "Automations" section's real firing history -- makes
    # automations visible when they happen, not something silent.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await list_automation_runs(postgres_conn)


class AutomationRuleUpdate(BaseModel):
    enabled: bool


@app.patch("/automations/rules/{rule_id}")
async def automation_rule_update(
    rule_id: str, body: AutomationRuleUpdate, request: Request, _: None = Depends(verify_token)
) -> dict:
    # UI-driven pause/resume -- id-based, not fuzzy, same reasoning as
    # Joshx's own UI-driven PATCH endpoints (the UI already knows the
    # exact row it's showing).
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    await set_automation_rule_enabled(rule_id, body.enabled, postgres_conn)
    await record_tool_call(
        "update_automation_rule_ui", {"rule_id": rule_id, "enabled": body.enabled}, "ok", postgres_conn
    )
    return {"rule_id": rule_id, "enabled": body.enabled}


@app.delete("/automations/rules/{rule_id}")
async def automation_rule_delete(rule_id: str, request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    deleted = await delete_automation_rule(rule_id, postgres_conn)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No automation rule with id {rule_id}")
    await record_tool_call("delete_automation_rule_ui", {"rule_id": rule_id}, "ok", postgres_conn)
    return {"rule_id": rule_id, "deleted": True}


@app.get("/knowledge")
async def knowledge_list(_: None = Depends(verify_token)) -> list[dict]:
    # Backs the iOS "Knowledge" section's doc list -- desktop reads these
    # same files directly off local disk instead (see app/knowledge.py's
    # docstring for why the phone needs this network path that desktop
    # doesn't).
    return await list_knowledge_docs()


@app.get("/knowledge/{filename}")
async def knowledge_content(filename: str, _: None = Depends(verify_token)) -> dict[str, str]:
    # filename is validated against a fixed allowlist inside read_doc, not
    # trusted as a free-form path -- see app/knowledge.py.
    return {"content": await read_knowledge_doc(filename)}


@app.get("/documents/{filename}")
async def generated_document(filename: str, _: None = Depends(verify_token)) -> Response:
    # Real gap found live (2026-09-09): generate_pdf_document() only ever
    # returned a raw Mac-local absolute path -- meaningless on iOS, which
    # has no filesystem access to this Mac at all. Desktop reads generated
    # PDFs straight off local disk instead (ProjectPaths.repoRoot, same
    # "same-machine shortcut" already used for Knowledge docs above); this
    # route exists for iOS. filename isn't a fixed allowlist like
    # Knowledge's own (these are dynamically generated, one per document),
    # so the boundary check is a direct parent-directory match instead --
    # agent_file_safety.py's resolve_repo_path() doesn't apply here, it
    # explicitly denies everything under backend/data.
    #
    # Cloud-mirror read (2026-09-11, iPhone independence pass): tries
    # Supabase Storage first when cloud-aware -- a document generated by
    # *either* backend needs to be readable from *either* backend, not
    # just whichever one happened to write it to its own local disk.
    # Falls through to local disk on a miss (a document generated before
    # this existed, or a genuine Storage error) rather than failing hard,
    # since the local file might still genuinely be there.
    if DATA_BACKEND == "postgres":
        try:
            content = await download_document(filename)
            if content is not None:
                return Response(content=content, media_type="application/pdf")
        except Exception as exc:
            print(f"[documents] Supabase Storage lookup failed for {filename}: {exc}")
    candidate = (DOCS_DIR / filename).resolve()
    if candidate.parent != DOCS_DIR.resolve() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(content=candidate.read_bytes(), media_type="application/pdf")


@app.get("/trading-division/dashboard")
async def trading_division_dashboard(_: None = Depends(verify_token)) -> dict:
    # Backs the desktop "Trading Division" section -- read-only, see
    # app/trading_division.py's own docstring for the full boundary.
    return await trading_division_dashboard_snapshot()


@app.get("/personal/dashboard")
async def personal_dashboard(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the desktop "Personal" section -- goals/habits only, see
    # app/personal_db.py's own docstring for scope. Stage 4 prep: this is
    # the one route currently wired to the dual-backend proof of concept --
    # every other route here is untouched and always reads SQLite.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await personal_dashboard_snapshot(postgres_conn)


@app.get("/joshx/dashboard")
async def joshx_dashboard(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the desktop "Joshx" section -- Josh's independent freelance
    # creative business, completely separate from Alpha Mode Media. Phase
    # 1 scope only (clients/leads/projects) -- see app/joshx_db.py's own
    # docstring.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await joshx_dashboard_snapshot(postgres_conn)


@app.get("/joshx/analytics")
async def joshx_analytics(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the new performance-metrics tiles (2026-09-06, systems audit
    # §3) -- deliberately a separate endpoint from /joshx/dashboard, not
    # new keys on it, matching compute_performance_metrics()'s own
    # docstring on why that boundary matters.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await joshx_performance_metrics(postgres_conn)


class JoshxProjectStatusUpdate(BaseModel):
    status: str


class JoshxProjectPaymentStatusUpdate(BaseModel):
    payment_status: str


@app.patch("/joshx/projects/{project_id}/status")
async def joshx_project_status_update(
    project_id: int, body: JoshxProjectStatusUpdate, request: Request, _: None = Depends(verify_token)
) -> dict:
    # Backs the Joshx detail view's status picker (2026-08-31) -- the
    # first UI-driven write in Joshx; every other Joshx write happens via
    # a Frank chat tool (see joshx_tools.py's update_joshx_project_status,
    # which stays fuzzy-name-matched and untouched by this). This one is
    # id-based (set_project_status_by_id, not the fuzzy _find_row_id
    # path) since the UI already knows the exact row id it's displaying,
    # and validated server-side against the known vocabulary -- the
    # chat-tool path trusts Frank's own judgment, this one can't.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    if body.status not in PROJECT_STATUS_VALUES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status!r}")
    updated = await set_project_status_by_id(project_id, body.status, postgres_conn)
    if not updated:
        raise HTTPException(status_code=404, detail=f"No project with id {project_id}")
    await record_tool_call(
        "update_joshx_project_status_ui", {"project_id": project_id, "status": body.status}, "ok", postgres_conn
    )
    return {"project_id": project_id, "status": body.status}


@app.patch("/joshx/projects/{project_id}/payment-status")
async def joshx_project_payment_status_update(
    project_id: int, body: JoshxProjectPaymentStatusUpdate, request: Request, _: None = Depends(verify_token)
) -> dict:
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    if body.payment_status not in PROJECT_PAYMENT_STATUS_VALUES:
        raise HTTPException(status_code=400, detail=f"Invalid payment_status: {body.payment_status!r}")
    updated = await set_project_payment_status_by_id(project_id, body.payment_status, postgres_conn)
    if not updated:
        raise HTTPException(status_code=404, detail=f"No project with id {project_id}")
    await record_tool_call(
        "update_joshx_project_payment_status_ui",
        {"project_id": project_id, "payment_status": body.payment_status},
        "ok",
        postgres_conn,
    )
    return {"project_id": project_id, "payment_status": body.payment_status}


@app.delete("/joshx/leads/{lead_id}")
async def joshx_lead_delete(lead_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the LEADS section's delete action (2026-08-31) -- soft
    # delete (leads.deleted_at), same reasoning as operations_db.py's
    # delete_task: a lead becoming a real project isn't tracked as a
    # link anywhere, so nothing auto-hides it once it's booked; this is
    # the explicit "get it off my list" action for a dormant one.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    deleted = await delete_lead_by_id(lead_id, postgres_conn)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No lead with id {lead_id}")
    await record_tool_call("delete_joshx_lead_ui", {"lead_id": lead_id}, "ok", postgres_conn)
    return {"lead_id": lead_id, "deleted": True}


@app.delete("/joshx/clients/{client_id}")
async def joshx_client_delete(client_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    # "Everything must be deletable if needed" (2026-08-31) -- same
    # soft-delete shape as the lead/project delete routes.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    deleted = await delete_client_by_id(client_id, postgres_conn)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No client with id {client_id}")
    await record_tool_call("delete_joshx_client_ui", {"client_id": client_id}, "ok", postgres_conn)
    return {"client_id": client_id, "deleted": True}


@app.delete("/joshx/projects/{project_id}")
async def joshx_project_delete(project_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    deleted = await delete_project_by_id(project_id, postgres_conn)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No project with id {project_id}")
    await record_tool_call("delete_joshx_project_ui", {"project_id": project_id}, "ok", postgres_conn)
    return {"project_id": project_id, "deleted": True}


@app.get("/people/dashboard")
async def people_dashboard(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the "PEOPLE" section inside Personal -- Josh's real personal/
    # professional relationship network, deliberately separate from
    # Joshx/Alpha Mode Media clients. See app/people_db.py's own docstring.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await people_dashboard_snapshot(postgres_conn)


@app.get("/finance/dashboard")
async def finance_dashboard(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the desktop "Finance" section -- Josh's personal investment
    # tracking, Luno automatic + four manually-logged accounts. See
    # app/finance_db.py's own docstring for scope.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    snapshot = await finance_dashboard_snapshot(postgres_conn)
    # Real overall Luno value, computed live against Luno's own price
    # feed (2026-08-24) -- see app/finance.py's compute_luno_zar_value()
    # docstring for why this can't just be a naive sum of raw balances.
    for account in snapshot["accounts"]:
        if account["name"] == "Luno" and account["holdings"]:
            account["luno_value"] = await compute_luno_zar_value(account["holdings"])
        elif account["name"] == "Nasdaq / Markets":
            # Real-time equity/floating P&L (2026-08-24) -- Josh wanted
            # to see this live during open trades, not just once a day.
            # See app/finance.py's get_hf_markets_live_status() docstring.
            account["hf_markets_live"] = get_hf_markets_live_status()
    return snapshot


@app.get("/finance/concentration")
async def finance_concentration(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the new concentration-bars section (2026-09-06, systems audit
    # §4) -- two separate views (ZAR accounts, Luno holdings), never one
    # blended number. See app/finance.py's compute_concentration_metrics()
    # docstring for why.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await compute_concentration_metrics(postgres_conn)


@app.get("/finance/history")
async def finance_history(
    account_id: int,
    request: Request,
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    _: None = Depends(verify_token),
) -> list[dict]:
    # Backs the new per-account history drill-down (2026-09-06, systems
    # audit §4's date-range filtering) -- every logged snapshot for one
    # account, optionally bounded by from/to ('YYYY-MM-DD'). Omitting both
    # returns the full history, honest given real accounts here span
    # barely two weeks so far.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await get_balance_history(account_id, from_, to, postgres_conn)


@app.get("/search")
async def search_endpoint(q: str, _: None = Depends(verify_token)) -> list[dict]:
    # The magnifying-glass button's real destination on both platforms --
    # see app/search.py's own docstring for scope (which domains, which
    # fields, the per-domain result cap) and why Memory/Operations/
    # Triggers/Trading Division/Calendar are deliberately excluded.
    return await search_all(q)


@app.get("/focus")
async def focus_endpoint(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the War Room's Mission Status card's "Focus: ..." line --
    # see db.py's get_focus_objective docstring for the deliberately
    # minimal scope (just this one line, no on/off mode, no automatic
    # deprioritization).
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await get_focus_objective(postgres_conn)


@app.post("/activity/log")
async def activity_log_endpoint(
    body: ActivityLogRequest, request: Request, _: None = Depends(verify_token)
) -> dict:
    # Shadow Mode's write path -- called by ActivityTracker.swift whenever
    # the frontmost app changes, not a Frank tool. See shadow_mode.py's
    # docstring for why capture and recall are split this way.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    await log_activity(body.app_name, postgres_conn)
    # Stage 8 prep: a real activity post is real evidence the Mac Local
    # Node is alive, same signal the dedicated heartbeat below sends --
    # free liveness update, no change to this route's own request/
    # response shape.
    await mark_local_node_seen(postgres_conn)
    return {"status": "ok"}


@app.post("/local-node/heartbeat")
async def local_node_heartbeat(request: Request, _: None = Depends(verify_token)) -> dict:
    # Stage 8 prep (2026-09-10): independent of app-switch events --
    # /activity/log only fires when the frontmost app actually changes, so
    # a Mac that's on but idle (no switching) looks identical to a Mac
    # that's off, from the backend's point of view. This is the real,
    # schedule-driven signal ActivityTracker.swift's new periodic loop
    # sends regardless of user activity, answering the audit's own
    # "Is the Mac Local Node online?" observability question.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    await mark_local_node_seen(postgres_conn)
    return {"status": "ok"}


@app.get("/insights")
async def insights_endpoint(request: Request, _: None = Depends(verify_token)) -> list[dict]:
    # Real data behind the right rail's "Frank's Insights" card -- was
    # literal placeholder text before (see app/insights.py's docstring).
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await compute_insights(postgres_conn=postgres_conn)


@app.get("/brief")
async def brief_endpoint(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs "The Brief" (Face-Lift item 09) -- see app/brief.py's own
    # docstring. Calling this marks the brief as viewed (updates
    # app_state.last_brief_viewed_at), so this is a real state-changing
    # read, not side-effect-free -- deliberate, since "what changed"
    # always means "since you last actually looked."
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await compute_brief(postgres_conn)


@app.get("/triggers/rules")
async def trigger_rules_endpoint(request: Request, _: None = Depends(verify_token)) -> list[dict]:
    # Read-only visibility into the Proactive Triggers Layer's rule rows
    # (app/triggers_db.py) -- exists so the rule set can be inspected
    # without opening a SQLite file by hand. GET /triggers/status (below)
    # is the richer endpoint the actual Triggers UI uses; this one stays
    # as the plain rule-only view it always was.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await list_trigger_rules(postgres_conn)


class TriggerRuleUpdate(BaseModel):
    enabled: bool


@app.patch("/triggers/rules/{rule_type}")
async def trigger_rule_update_endpoint(
    rule_type: str, body: TriggerRuleUpdate, request: Request, _: None = Depends(verify_token)
) -> dict:
    # Backs the Triggers UI's per-rule toggle (2026-08-21) -- the first UI
    # control that mutates trigger_rules directly, rather than Frank being
    # the only way state changes (unlike Personal/Alpha Mode's Frank-only
    # writes, this is plain settings-style state with no reason to route
    # through a conversation).
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    await set_rule_enabled(rule_type, body.enabled, postgres_conn)
    return {"rule_type": rule_type, "enabled": body.enabled}


@app.get("/triggers/status")
async def trigger_status_endpoint(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the Triggers UI's main view -- every rule plus its currently
    # live-matching items, each flagged with whether it'd actually be in
    # *today's* digest per the decaying cadence (app/triggers.py's
    # compute_status(), entirely read-only -- viewing this can't consume
    # a cadence slot or alter what the next real digest sends).
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await compute_trigger_status(postgres_conn)


@app.post("/triggers/run-now")
async def trigger_run_now_endpoint(request: Request, _: None = Depends(verify_token)) -> dict:
    # Manual escape hatch for testing the digest without waiting for the
    # scheduler's send_hour gate (app/triggers.py's maybe_run_daily_digest)
    # -- runs the real rule checks and, if anything's due, actually sends
    # the email. Does not touch digest_schedule.last_sent_date, so it
    # won't interfere with the once-a-day scheduled run.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await run_daily_digest(postgres_conn)


@app.get("/alpha-mode/dashboard")
async def alpha_mode_dashboard_endpoint(_: None = Depends(verify_token)) -> dict:
    # Backs the sidebar's real "Alpha Mode Media" section -- see
    # alpha_mode_supabase.dashboard_snapshot's docstring.
    return await alpha_mode_dashboard_snapshot()


@app.get("/situation-room")
async def situation_room_endpoint(request: Request, _: None = Depends(verify_token)) -> list[dict]:
    # Backs War Room's escalated alert banner -- see
    # app/situation_room.py's docstring for how this differs from the
    # routine /insights list.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await compute_situation_room_alerts(postgres_conn)


@app.delete("/memory/{memory_id}")
async def forget_memory(memory_id: int, request: Request, _: None = Depends(verify_token)) -> dict[str, bool]:
    # Manual forgetting from the UI — same soft-delete Frank's own
    # forget_memory tool uses, just addressed by ID instead of title since
    # the UI already has it.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    forgotten = await forget_memory_by_id(memory_id, postgres_conn)
    return {"forgotten": forgotten}


@app.get("/history")
async def history(request: Request, _: None = Depends(verify_token)) -> list[dict]:
    # The active conversation's transcript — always the most recently
    # created one (app/db.py's get_active_conversation_id). This is what
    # backs the real chat thread built into WarRoomView.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    conversation_id = await get_active_conversation_id(postgres_conn)
    return await load_history(conversation_id, postgres_conn)


@app.post("/conversations")
async def new_conversation(request: Request, _: None = Depends(verify_token)) -> dict[str, int]:
    # "New chat" — memory (app/memory.py) still carries continuity forward;
    # this just starts a fresh transcript, and becomes the active one.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    conversation_id = await create_new_conversation(postgres_conn)
    return {"conversation_id": conversation_id}


@app.get("/conversations")
async def conversations(request: Request, q: str | None = None, _: None = Depends(verify_token)) -> list[dict]:
    # Backs the conversation history browser — reopening an older chat
    # needs a way to find it, indefinitely, as history accumulates over
    # time. `q`, when given, searches real message content across each
    # conversation, not just its preview.
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await list_conversations(query=q, postgres_conn=postgres_conn)


@app.post("/conversations/{conversation_id}/activate")
async def activate_conversation(
    conversation_id: int, request: Request, _: None = Depends(verify_token)
) -> dict[str, int]:
    # Reopening an older conversation — makes it active without needing to
    # be the newest row (that's the whole reason app_state exists instead
    # of just "active = newest").
    postgres_conn = getattr(request.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    await set_active_conversation(conversation_id, postgres_conn)
    return {"conversation_id": conversation_id}


async def _speak_via_elevenlabs(client: httpx.AsyncClient, text: str) -> bytes:
    """Raises on any failure — caller decides what that means (fall back
    to Piper, in this case). Not swallowing errors here since the caller
    needs to distinguish "ElevenLabs not configured" (skip straight to
    Piper) from "ElevenLabs configured but the call itself failed" (also
    falls back, but worth knowing which happened if this ever needs
    debugging). Takes the shared client (app.state.elevenlabs_client) as a
    parameter rather than opening its own — a fresh connection per call
    was a real, confirmed latency bug (see lifespan's comment)."""
    response = await client.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
        headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
        json={"text": text, "model_id": "eleven_turbo_v2_5"},
    )
    response.raise_for_status()
    return response.content


@app.post("/speak")
async def speak(request: SpeakRequest, http_request: Request, _: None = Depends(verify_token)) -> Response:
    # ElevenLabs first (genuinely human, stylized voice — the reason it's
    # worth paying for), Piper as the always-available fallback (free,
    # local, no account to lapse) — see the ELEVENLABS_API_KEY comment
    # above for why both paths are kept rather than picking one. Any
    # ElevenLabs failure (missing permission, quota, payment issue,
    # network) falls through silently from Frank's perspective — he still
    # speaks, just via the fallback voice — logged server-side so it's
    # debuggable without being surfaced as a hard error to the UI.
    if ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID:
        try:
            audio = await _speak_via_elevenlabs(http_request.app.state.elevenlabs_client, request.text)
            return Response(content=audio, media_type="audio/mpeg")
        except Exception as error:
            print(f"[speak] ElevenLabs failed, falling back to Piper: {error}")

    audio = await asyncio.to_thread(synthesize_wav_bytes, request.text)
    return Response(content=audio, media_type="audio/wav")


@app.websocket("/ws")
async def websocket_chat(websocket: WebSocket) -> None:
    await websocket.accept()

    # Stage 7 prep: same additive check as verify_token() above. Cheap
    # getattr, not a new connection -- the real postgres_conn (if any) is
    # already sitting on websocket.app.state from lifespan(); this is
    # computed again, identically, further down for the rest of this
    # function's own use.
    ws_token = websocket.query_params.get("token")
    ws_postgres_conn = getattr(websocket.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    if ws_token != AUTH_TOKEN and not await verify_device_session(ws_token or "", ws_postgres_conn):
        await websocket.send_text("[backend error: invalid or missing auth token]")
        await websocket.close()
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        await websocket.send_text(
            "[backend error: ANTHROPIC_API_KEY not set. Copy backend/.env.example "
            "to backend/.env and add a real key.]"
        )
        await websocket.close()
        return

    client = AsyncAnthropic(api_key=api_key)
    # Computed once per connection, not per turn -- app.state.postgres_conn
    # is set once at startup and never changes for the life of the process,
    # so there's nothing to re-check on every message. Reused below both
    # for building Frank's own system-prompt context (build_personal_block)
    # and for the personal-domain tool-dispatch branch further down --
    # a real bug found live (2026-09-10): build_personal_block() was
    # calling summarize() with no connection at all, meaning Frank's own
    # system-prompt view of his goals/habits stayed on SQLite even after
    # DATA_BACKEND=postgres went live, silently stale the moment a write
    # actually landed in Postgres instead.
    postgres_conn = getattr(websocket.app.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    # Whichever conversation is active as of connect time — a client that
    # started a new chat right before reconnecting picks up the fresh one.
    conversation_id = await get_active_conversation_id(postgres_conn)
    # image_path is dropped here, deliberately -- load_history() includes it
    # for GET /history's benefit (the UI's "📎 image attached" placeholder for
    # an old message), but Claude's own `messages=` list only accepts
    # role/content, and reloading old history should show a past image was
    # attached, not re-send it as real vision context on every reconnect
    # (confirmed decision 2026-08-05 -- see load_history()'s docstring).
    history: list[dict[str, str]] = [
        {"role": row["role"], "content": row["content"]} for row in await load_history(conversation_id, postgres_conn)
    ]

    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                payload = json.loads(raw_message)
                user_text = payload.get("text", "")
                all_attachments = payload.get("attachments", [])
                attachments_payload = all_attachments[:MAX_ATTACHMENTS_PER_MESSAGE]
                dropped_count = len(all_attachments) - len(attachments_payload)
            except json.JSONDecodeError:
                user_text = raw_message
                attachments_payload = []
                dropped_count = 0

            # Real bug found live (2026-09-05, multi-attach): oversized/
            # too-many attachments must never fail deep inside the
            # Anthropic SDK call with a confusing raw error -- rejected
            # ones become an honest in-band text block instead, same "the
            # user should always be told why" discipline as everywhere
            # else attachments can fail (see document_attachments.py). The
            # count cap specifically used to just silently slice the list
            # -- confirmed live, Frank had no way to know 2 of 8 attached
            # files never arrived at all. Now says so explicitly too.
            content_blocks: list[dict] = []
            saved_attachments: list[dict] = []
            total_bytes = 0
            if dropped_count > 0:
                content_blocks.append(
                    {"type": "text", "text": f"[{dropped_count} attached file(s) were dropped -- only the first {MAX_ATTACHMENTS_PER_MESSAGE} per message are sent.]"}
                )
            for attachment in attachments_payload:
                media_type = attachment.get("media_type", "")
                filename = attachment.get("filename") or "attachment"
                data = attachment.get("data")
                if not data:
                    continue
                raw_bytes = base64.b64decode(data)
                total_bytes += len(raw_bytes)
                if len(raw_bytes) > MAX_ATTACHMENT_BYTES or total_bytes > MAX_TOTAL_ATTACHMENT_BYTES:
                    content_blocks.append(
                        {"type": "text", "text": f"[Attached file '{filename}' was too large and was not sent.]"}
                    )
                    continue
                ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
                stored_name = f"{uuid.uuid4()}{Path(filename).suffix}"
                (ATTACHMENTS_DIR / stored_name).write_bytes(raw_bytes)
                content_blocks.append(build_content_block(media_type, filename, raw_bytes))
                saved_attachments.append({"filename": stored_name, "original_name": filename, "media_type": media_type})

            user_content = [*content_blocks, {"type": "text", "text": user_text}] if content_blocks else user_text

            history.append({"role": "user", "content": user_content})
            await save_message(
                conversation_id, "user", user_text, attachments=saved_attachments or None, postgres_conn=postgres_conn
            )

            system_prompt = (
                SYSTEM_PROMPT
                + ATTACHMENT_CAPABILITY_NOTE
                + await build_memory_block(postgres_conn)
                + await build_alpha_mode_block(postgres_conn)
                + await build_operations_block(postgres_conn)
                + await build_personal_block(postgres_conn)
                + await build_joshx_block(postgres_conn)
                + await build_people_block(postgres_conn)
                + await build_finance_block(postgres_conn)
                + await build_trading_division_block()
            )

            try:
                assistant_reply, generated_documents = await run_claude_turn(
                    client, system_prompt, history, websocket, conversation_id, attachments=content_blocks
                )
            except WebSocketDisconnect:
                # Real bug found live (2026-08-27): the socket can now die
                # while run_claude_turn is blocked somewhere deeper than
                # this loop's own receive_text() -- specifically,
                # Engineering Agent's propose_file_edit awaiting an
                # approval decision that never arrives (app backgrounded/
                # quit while a card was showing). Re-raise rather than
                # falling into the generic `except Exception` below: that
                # branch's own `continue` would loop back to this
                # function's `receive_text()` a second time on an already-
                # disconnected socket, and Starlette doesn't raise a
                # second WebSocketDisconnect for that -- it raises a bare
                # RuntimeError instead (confirmed live), which would
                # surface as an ugly uncaught traceback instead of the
                # same clean shutdown every other disconnect gets via the
                # outer `except WebSocketDisconnect: pass` below.
                history.pop()
                raise
            except anthropic.APIStatusError as error:
                # Reliability pass (2026-09-07): a real Anthropic billing
                # failure (out of credits) used to fall straight into the
                # generic branch below and show as one confusing raw SDK
                # error string in the chat transcript, with zero
                # persistent signal anywhere else in the app -- the status
                # header stayed "SYSTEM NOMINAL" throughout. Originally
                # checked only `error.type == "billing_error"`, assumed
                # from a synthetic test -- a real credit-exhaustion error
                # hit live during a later feature's own testing that same
                # night proved the actual value Anthropic sends for this
                # exact "credit balance is too low" case is
                # "invalid_request_error", not "billing_error" (confirmed
                # directly from the real response body). Kept the
                # structured-type check (real "billing_error" cases may
                # exist for other billing conditions) and added a message
                # substring fallback for the case actually observed live,
                # rather than trusting the assumed value alone. Must be
                # caught before the generic `except Exception` below,
                # since APIStatusError is a subclass of it.
                is_credit_exhaustion = getattr(error, "type", None) == "billing_error" or (
                    "credit balance" in str(error).lower()
                )
                if is_credit_exhaustion:
                    await set_credits_exhausted(postgres_conn)
                    message = (
                        "Frank is temporarily unavailable — the Anthropic account has run "
                        "out of credits. Add credits at console.anthropic.com/settings/billing, "
                        "then try again."
                    )
                else:
                    message = f"\n[backend error: {error}]"
                try:
                    await websocket.send_text(message)
                except Exception:
                    pass
                history.pop()
                continue
            except Exception as error:
                # A client-initiated stop (BackendClient.stopGenerating())
                # closes the socket mid-stream, which is exactly what
                # causes this branch to fire in the first place -- trying
                # to report the error back over an already-closed socket
                # would just raise a second, noisier exception, so that
                # attempt is best-effort only.
                try:
                    await websocket.send_text(f"\n[backend error: {error}]")
                except Exception:
                    pass
                # Don't record a failed/interrupted turn in memory or on
                # disk — keeps conversation state consistent for the next
                # message (or the reconnect stopGenerating() makes).
                history.pop()
                continue

            # Reliability pass (2026-09-07): clears any earlier billing
            # alert the moment a turn actually succeeds again -- cheap
            # single-row UPDATE, correct as a no-op when nothing was set.
            await clear_credits_exhausted(postgres_conn)
            history.append({"role": "assistant", "content": assistant_reply})
            await save_message(
                conversation_id,
                "assistant",
                assistant_reply,
                attachments=generated_documents or None,
                postgres_conn=postgres_conn,
            )
            await websocket.send_text("\n[done]")
    except WebSocketDisconnect:
        pass


async def run_claude_turn(
    client: AsyncAnthropic,
    system_prompt: str,
    history: list,
    websocket: WebSocket,
    conversation_id: int,
    attachments: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    """Runs one user turn to completion, including any save_memory round
    trips — Frank may call the tool, see the result, then keep talking. Text
    streams to the websocket as it arrives, across every round. `history` is
    mutated in place with any intermediate tool_use/tool_result turns (valid
    context for the rest of this live connection); the caller is responsible
    for appending the single final assistant text turn once this returns,
    since that's the flat, plain-text form persisted to SQLite.

    Also returns any PDFs generated this turn (2026-09-09, "viewable &
    saveable" fix) — same generic `attachments` shape/column db.py's
    save_message already has, just populated for the assistant role for
    the first time, so a generated-document button survives reopening the
    conversation instead of only existing for the live [document_generated]
    websocket sentinel.

    attachments (2026-08-10, Design Critic; generalized 2026-09-05 for
    multi-attach documents) are this turn's already-built content blocks,
    if any -- Frank already sees them directly (they're part of `history`'s
    own content blocks), but a delegated specialist's own isolated Claude
    call doesn't share that history, so if Frank delegates to a
    vision-aware agent (currently just Design Agent), the same blocks are
    forwarded to it directly -- whatever kinds they are (image/PDF/
    extracted-text), uniformly, no per-kind logic needed here. Only ever
    this turn's attachments, not an earlier one in the same conversation --
    same "don't re-inject an old attachment" reasoning as reopening a past
    conversation."""
    assistant_text = ""
    generated_documents: list[dict] = []
    while True:
        async with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=history,
            tools=[
                SAVE_MEMORY_TOOL,
                FORGET_MEMORY_TOOL,
                *FOCUS_TOOLS,
                *DECISION_JOURNAL_TOOLS,
                *MEMORY_GRAPH_TOOLS,
                *SHADOW_MODE_TOOLS,
                *DEBATE_TOOLS,
                *LEGACY_VAULT_TOOLS,
                *ALPHA_MODE_TOOLS,
                *OPERATIONS_TOOLS,
                *ALPHA_MODE_AGENT_TOOLS,
                *DESIGN_AGENT_TOOLS,
                *CREATIVE_DIRECTOR_AGENT_TOOLS,
                *COMMUNICATIONS_AGENT_TOOLS,
                *MEMORY_AGENT_TOOLS,
                *RESEARCH_AGENT_TOOLS,
                *ENGINEERING_AGENT_TOOLS,
                *TRADING_DIVISION_AGENT_TOOLS,
                *PERSONAL_TOOLS,
                *JOSHX_TOOLS,
                *PEOPLE_TOOLS,
                *FINANCE_TOOLS,
                *DOCUMENTS_TOOLS,
                *CONNECTED_APPS_TOOLS,
                *CALENDAR_TOOLS,
                *EMAIL_TOOLS,
                *AUTOMATION_TOOLS,
                *DATA_ANALYSIS_TOOLS,
                *WEB_TOOLS,
            ],
        ) as stream:
            async for event in stream:
                if event.type == "text":
                    assistant_text += event.text
                    await websocket.send_text(event.text)
                elif event.type == "content_block_start" and event.content_block.type == "server_tool_use":
                    # Real gap found live (2026-09-06): web_search/web_fetch
                    # are server-executed -- Anthropic runs them and injects
                    # results back into this same stream, so they never
                    # produce a tool_use block and never reach the dispatch
                    # loop below where every other tool's [tool_start]
                    # indicator fires (tool_labels.py's label_for_tool).
                    # Left alone, a direct web search would be a silent
                    # pause -- the exact thing the tool-execution-indicator
                    # feature shipped earlier tonight to prevent. Detected
                    # here instead, off the raw event stream, purely for
                    # indicator purposes -- nothing is dispatched or
                    # executed on this branch.
                    label = SERVER_TOOL_LABELS.get(event.content_block.name, "Searching the web")
                    await websocket.send_text(f"\n[tool_start]{json.dumps({'label': label})}")
            final_message = await stream.get_final_message()

        if final_message.stop_reason != "tool_use":
            return assistant_text, generated_documents

        history.append({"role": "assistant", "content": final_message.content})
        tool_results = []
        for block in final_message.content:
            if block.type != "tool_use":
                continue
            await websocket.send_text(f"\n[tool_start]{json.dumps({'label': label_for_tool(block.name)})}")
            if block.name in FOCUS_TOOL_NAMES:
                result = await execute_focus_tool_call(block.name, block.input, postgres_conn)
            elif block.name in DECISION_JOURNAL_TOOL_NAMES:
                result = await execute_decision_journal_tool_call(block.name, block.input, postgres_conn)
            elif block.name in MEMORY_GRAPH_TOOL_NAMES:
                result = await execute_memory_graph_tool_call(block.name, block.input, postgres_conn)
            elif block.name in SHADOW_MODE_TOOL_NAMES:
                result = await execute_shadow_mode_tool_call(block.name, block.input, postgres_conn)
            elif block.name in DEBATE_TOOL_NAMES:
                result = await execute_debate_tool_call(block.name, block.input, client, websocket)
                # Same reasoning as consult_operations_agent below --
                # already streamed live, needs to land in the persisted
                # transcript too.
                assistant_text += result
            elif block.name in LEGACY_VAULT_TOOL_NAMES:
                result = await execute_legacy_vault_tool_call(block.name, block.input, postgres_conn)
            elif block.name in ALPHA_MODE_TOOL_NAMES:
                result = await execute_alpha_mode_tool_call(block.name, block.input, websocket, postgres_conn)
            elif block.name in OPERATIONS_TOOL_NAMES:
                # postgres_conn computed once near the top of websocket_chat,
                # reused here -- see that comment for why.
                result = await execute_operations_tool_call(block.name, block.input, client, websocket, postgres_conn)
                if block.name == "consult_operations_agent":
                    # This was already streamed live to the websocket
                    # inside execute_operations_tool_call -- append it to
                    # the persisted transcript too, or reopening this
                    # conversation later would be missing exactly what
                    # was shown on screen, keeping only Frank's own
                    # follow-up remark.
                    assistant_text += result
            elif block.name in ALPHA_MODE_AGENT_TOOL_NAMES:
                result = await execute_alpha_mode_agent_tool_call(block.name, block.input, client, websocket)
                # Same reasoning as consult_operations_agent above --
                # already streamed live, needs to land in the persisted
                # transcript too.
                assistant_text += result
            elif block.name in DESIGN_AGENT_TOOL_NAMES:
                result = await execute_design_agent_tool_call(
                    block.name, block.input, client, websocket, attachments=attachments
                )
                # Same reasoning as consult_operations_agent above --
                # already streamed live, needs to land in the persisted
                # transcript too.
                assistant_text += result
            elif block.name in CREATIVE_DIRECTOR_AGENT_TOOL_NAMES:
                result = await execute_creative_director_agent_tool_call(block.name, block.input, client, websocket)
                # Same reasoning as consult_operations_agent above --
                # already streamed live, needs to land in the persisted
                # transcript too.
                assistant_text += result
            elif block.name in COMMUNICATIONS_AGENT_TOOL_NAMES:
                result = await execute_communications_agent_tool_call(block.name, block.input, client, websocket)
                # Same reasoning as consult_operations_agent above --
                # already streamed live, needs to land in the persisted
                # transcript too.
                assistant_text += result
            elif block.name in MEMORY_AGENT_TOOL_NAMES:
                result = await execute_memory_agent_tool_call(block.name, block.input, client, websocket)
                # Same reasoning as consult_operations_agent above --
                # already streamed live, needs to land in the persisted
                # transcript too.
                assistant_text += result
            elif block.name in RESEARCH_AGENT_TOOL_NAMES:
                result = await execute_research_agent_tool_call(block.name, block.input, client, websocket)
                # Same reasoning as consult_operations_agent above --
                # already streamed live, needs to land in the persisted
                # transcript too.
                assistant_text += result
            elif block.name in ENGINEERING_AGENT_TOOL_NAMES:
                result = await execute_engineering_agent_tool_call(block.name, block.input, client, websocket)
                # Same reasoning as consult_operations_agent above --
                # already streamed live, needs to land in the persisted
                # transcript too.
                assistant_text += result
            elif block.name in TRADING_DIVISION_AGENT_TOOL_NAMES:
                result = await execute_trading_division_agent_tool_call(block.name, block.input, client, websocket)
                # Same reasoning as consult_operations_agent above --
                # already streamed live, needs to land in the persisted
                # transcript too.
                assistant_text += result
            elif block.name in PERSONAL_TOOL_NAMES:
                # postgres_conn computed once near the top of websocket_chat,
                # reused here -- see that comment for why.
                result = await execute_personal_tool_call(block.name, block.input, postgres_conn)
            elif block.name in JOSHX_TOOL_NAMES:
                result = await execute_joshx_tool_call(block.name, block.input, postgres_conn)
            elif block.name in PEOPLE_TOOL_NAMES:
                result = await execute_people_tool_call(block.name, block.input, postgres_conn)
            elif block.name in FINANCE_TOOL_NAMES:
                result = await execute_finance_tool_call(block.name, block.input, postgres_conn)
            elif block.name in DOCUMENTS_TOOL_NAMES:
                result = await execute_documents_tool_call(block.name, block.input, postgres_conn)
            elif block.name in CONNECTED_APPS_TOOL_NAMES:
                result = await execute_connected_apps_tool_call(block.name, block.input, postgres_conn)
            elif block.name in CALENDAR_TOOL_NAMES:
                result = await execute_calendar_tool_call(block.name, block.input, websocket, postgres_conn)
            elif block.name in EMAIL_TOOL_NAMES:
                result = await execute_email_tool_call(block.name, block.input, postgres_conn)
            elif block.name in AUTOMATION_TOOL_NAMES:
                result = await execute_automation_tool_call(block.name, block.input, websocket, postgres_conn)
            elif block.name in DATA_ANALYSIS_TOOL_NAMES:
                result = await execute_data_analysis_tool_call(block.name, block.input, conversation_id, postgres_conn)
            else:
                result = await execute_tool_call(block.name, block.input, postgres_conn)
            # Real audit trail (2026-08-10, SECURITY.md's flagged gap) --
            # every tool call, regardless of which branch above produced
            # it, logged at this one point so no individual agent module
            # needed touching. See audit_db.py's own docstring for why
            # there's no "who" column.
            await record_tool_call(block.name, block.input, result, postgres_conn)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": result}
            )
            if block.name == "save_memory":
                notification = json.dumps(
                    {
                        "title": "Frank remembered something",
                        "body": block.input.get("title", "New memory saved"),
                    }
                )
                await websocket.send_text(f"\n[notify]{notification}")
            elif block.name == "forget_memory" and result.startswith("Forgot:"):
                notification = json.dumps(
                    {"title": "Frank forgot something", "body": result.removeprefix("Forgot: ")}
                )
                await websocket.send_text(f"\n[notify]{notification}")
            elif block.name == "set_focus_objective":
                notification = json.dumps({"title": "Focus updated", "body": block.input.get("objective", "")})
                await websocket.send_text(f"\n[notify]{notification}")
            elif block.name == "log_decision":
                notification = json.dumps({"title": "Decision logged", "body": block.input.get("decision", "")})
                await websocket.send_text(f"\n[notify]{notification}")
            elif block.name == "link_records" and result.startswith("Linked:"):
                notification = json.dumps({"title": "Memories linked", "body": result.removeprefix("Linked: ")})
                await websocket.send_text(f"\n[notify]{notification}")
            elif block.name == "save_to_legacy_vault":
                notification = json.dumps({"title": "Legacy Vault updated", "body": block.input.get("title", "")})
                await websocket.send_text(f"\n[notify]{notification}")
            elif block.name == "delete_from_legacy_vault" and result.startswith("Deleted from Legacy Vault:"):
                notification = json.dumps(
                    {"title": "Legacy Vault entry removed", "body": result.removeprefix("Deleted from Legacy Vault: ")}
                )
                await websocket.send_text(f"\n[notify]{notification}")
            elif block.name in ALPHA_MODE_TOOL_NAMES:
                notification = json.dumps({"title": "Alpha Mode Media updated", "body": result})
                await websocket.send_text(f"\n[notify]{notification}")
            elif block.name in ("add_task", "update_task_status", "delete_task"):
                notification = json.dumps({"title": "Task updated", "body": result})
                await websocket.send_text(f"\n[notify]{notification}")
            elif block.name == "generate_pdf_document" and result.startswith("PDF saved to "):
                # Real fix (2026-09-09): "viewable & saveable" PDFs -- the
                # result string is Frank's own context, still just a raw
                # path; this is the real, structured signal the UI acts on.
                # A distinct sentinel, not folded into [notify], since this
                # attaches to the message itself (a real file to open),
                # not a transient banner.
                document_filename = Path(result.removeprefix("PDF saved to ")).name
                document_title = block.input.get("title", document_filename)
                generated_documents.append({"filename": document_filename, "title": document_title})
                await websocket.send_text(
                    f"\n[document_generated]{json.dumps({'filename': document_filename, 'title': document_title})}"
                )

            automation_notification = await check_and_fire_automation(
                block.name, block.input, client, result, postgres_conn
            )
            if automation_notification:
                # Deliberately a separate notification, not folded into
                # the block above -- this is a rule firing as a real
                # side effect of the tool call, not the tool call's own
                # result, and the two shouldn't be conflated in the UI.
                await websocket.send_text(f"\n[notify]{json.dumps(automation_notification)}")
        history.append({"role": "user", "content": tool_results})


def run() -> None:
    import uvicorn

    # Cloud mode (2026-09-10): Render (and every similar PaaS) assigns the
    # listen port dynamically via $PORT and requires binding 0.0.0.0 --
    # checked first, before any Mac-hosted branching, so the two modes are
    # mutually exclusive by construction. 0.0.0.0 is correct here even
    # though SECURITY.md ruled it out for the Mac-hosted case below: an
    # isolated container's own network boundary is what limits real
    # exposure, not this bind address, and every route is still gated by
    # real auth regardless. No hang-watchdog in this mode -- Render
    # supervises the process itself, and the watchdog's own health-check
    # URL hardcodes BACKEND_PORT (8731), which would be the wrong port to
    # check here (the real bound port is $PORT).
    render_port = os.environ.get("PORT")
    if render_port:
        uvicorn.run(app, host="0.0.0.0", port=int(render_port), ws_max_size=WS_MAX_SIZE)
        return

    # 127.0.0.1 always, regardless of Tailscale — the desktop app must keep
    # working with zero dependency on Tailscale being installed, running,
    # or configured. Confirmed decision (2026-07-31): mobile access adds a
    # SECOND listener on this Mac's Tailscale-assigned IP (not 0.0.0.0,
    # which SECURITY.md already ruled out — that would also expose this to
    # the regular Wi-Fi/Ethernet interface, reachable by anyone else on the
    # same network). TAILSCALE_IP is optional in .env — if unset, this
    # behaves exactly as before, single listener, no behavior change.
    _start_hang_watchdog()

    tailscale_ip = os.environ.get("TAILSCALE_IP")
    if not tailscale_ip:
        uvicorn.run(app, host="127.0.0.1", port=BACKEND_PORT, ws_max_size=WS_MAX_SIZE)
        return

    asyncio.run(_run_dual(tailscale_ip))


async def _run_dual(tailscale_ip: str) -> None:
    import uvicorn

    local_server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=BACKEND_PORT, ws_max_size=WS_MAX_SIZE))
    tailscale_server = uvicorn.Server(
        uvicorn.Config(app, host=tailscale_ip, port=BACKEND_PORT, ws_max_size=WS_MAX_SIZE)
    )
    await asyncio.gather(local_server.serve(), tailscale_server.serve())


_WATCHDOG_GRACE_SECONDS = 30
_WATCHDOG_CHECK_INTERVAL_SECONDS = 30
_WATCHDOG_MAX_CONSECUTIVE_FAILURES = 3


def _start_hang_watchdog() -> None:
    """Reliability pass (2026-09-07): a real incident this week saw the
    launchd-managed backend start and sit at 0% CPU indefinitely, never
    binding this port -- alive, not crashed, so launchd's own
    KeepAlive: true (which only restarts on actual process exit) never
    caught it. Confirmed via uvicorn's own source that the full FastAPI
    lifespan (every init_*_db() call, the shared httpx.AsyncClient(), both
    existing background loops) runs entirely before the port is ever
    bound -- a hang anywhere in there matches that incident exactly.

    Runs as a real OS thread, not an asyncio task, specifically so it
    keeps making progress even if the main asyncio event loop itself is
    what's deadlocked -- urllib's blocking call releases the GIL during
    the actual network wait, so this thread isn't starved by a stuck main
    thread. Checks a real GET /health round trip (accept -> ASGI dispatch
    -> route handler -> response), not just a raw TCP connect -- a bare
    connect only proves the kernel completed a handshake, which a process
    that bound the port fine and wedged afterward would still pass
    forever.

    Timing: first check at t=30s after this thread starts, then every 30s
    -- 3 consecutive failures means the kill fires at t=90s total. Calls
    os._exit(1), not sys.exit(): sys.exit() only raises SystemExit in
    this thread and would do nothing to a hung main thread; os._exit()
    terminates the whole process immediately regardless of which thread
    calls it. No zombie-port risk -- the kernel closes every file
    descriptor on process exit, and uvicorn's listening socket uses
    SO_REUSEADDR, so launchd's KeepAlive-triggered restart binds cleanly.
    Only self-heals when actually running under launchd (the packaged
    desktop app's managed backend); a bare dev process with no supervisor
    would just get hard-killed with nothing to restart it -- accepted,
    since dev mode isn't this fix's target."""

    def _watchdog() -> None:
        import time

        time.sleep(_WATCHDOG_GRACE_SECONDS)
        consecutive_failures = 0
        health_url = f"http://127.0.0.1:{BACKEND_PORT}/health?token={AUTH_TOKEN}"
        while True:
            try:
                with urllib.request.urlopen(health_url, timeout=2) as response:
                    healthy = response.status == 200
            except (urllib.error.URLError, OSError, ValueError):
                healthy = False

            if healthy:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= _WATCHDOG_MAX_CONSECUTIVE_FAILURES:
                    print(
                        f"[watchdog] backend unresponsive for "
                        f"{_WATCHDOG_MAX_CONSECUTIVE_FAILURES} consecutive checks -- forcing exit "
                        f"so launchd's KeepAlive restarts a fresh process"
                    )
                    os._exit(1)

            time.sleep(_WATCHDOG_CHECK_INTERVAL_SECONDS)

    threading.Thread(target=_watchdog, daemon=True, name="hang-watchdog").start()


if __name__ == "__main__":
    run()
