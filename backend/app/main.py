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
import re
import secrets
import threading
import urllib.error
import urllib.request
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic
import httpx
from psycopg_pool import AsyncConnectionPool
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
from app.audit_db import init_audit_db, list_recent_calls, record_tool_call
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
from app.personal_db import add_goal, add_habit, dashboard_snapshot as personal_dashboard_snapshot, init_personal_db
from app.personal_tools import PERSONAL_TOOL_NAMES, PERSONAL_TOOLS, build_personal_block, execute_personal_tool_call
from app.joshx_db import (
    PROJECT_PAYMENT_STATUS_VALUES,
    PROJECT_STATUS_VALUES,
    compute_performance_metrics as joshx_performance_metrics,
    convert_lead_to_project,
    dashboard_snapshot as joshx_dashboard_snapshot,
    delete_client_by_id,
    delete_lead_by_id,
    delete_project_by_id,
    init_joshx_db,
    set_project_payment_status_by_id,
    set_project_status_by_id,
)
from app.joshx_tools import JOSHX_TOOL_NAMES, JOSHX_TOOLS, build_joshx_block, execute_joshx_tool_call
from app.people_db import add_person, dashboard_snapshot as people_dashboard_snapshot, init_people_db, update_person
from app.people_tools import PEOPLE_TOOL_NAMES, PEOPLE_TOOLS, build_people_block, execute_people_tool_call
from app.finance_db import (
    get_balance_history,
    get_hf_markets_schedule,
    get_luno_schedule,
    init_finance_db,
    log_balance,
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
    get_hf_markets_live_status_for_dashboard,
    live_finance_dashboard,
    maybe_snapshot_hf_markets,
    maybe_snapshot_luno,
)
from app.market_movers import maybe_snapshot_market_prices
from app.trading_division import (
    build_trading_division_block,
    dashboard_snapshot as trading_division_dashboard_snapshot,
    live_account_summary,
)
from app.trading_division_agent import (
    TRADING_DIVISION_AGENT_TOOL_NAMES,
    TRADING_DIVISION_AGENT_TOOLS,
    execute_trading_division_agent_tool_call,
    get_holding_update,
    get_stock_update,
)
from app.trade_intelligence_db import (
    SETUP_TAGS,
    TIMEFRAMES,
    add_trade as ti_add_trade,
    compute_breakdown_stats as ti_compute_breakdown_stats,
    delete_trade as ti_delete_trade,
    init_trade_intelligence_db,
    list_trades as ti_list_trades,
)
from app.trade_intelligence_agent import (
    TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT,
    TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT_WITH_SUGGESTION,
    analyze_chart as ti_analyze_chart,
    analyze_trade_setup,
    extract_trade_suggestion,
    generate_signal as ti_generate_signal,
    narrate_trade_breakdown,
    review_position as ti_review_position,
    run_conversational_turn,
)
from app.trade_proposals_db import (
    DIRECTIONS as PROPOSAL_DIRECTIONS,
    create_proposal,
    delete_proposal,
    init_trade_proposals_db,
    list_proposals,
    mark_command_written,
    record_execution_result,
    resolve_proposal,
)
from app.ventures_db import (
    AUTOMATION_SUGGESTION_STATUSES,
    CHECKLIST_ITEM_STATUSES,
    CONFIDENCE_LEVELS as VENTURE_CONFIDENCE_LEVELS,
    CUSTOMER_STATUSES,
    FULFILLMENT_ITEM_STATUSES,
    LEVELS as VENTURE_LEVELS,
    MARKETING_CONTENT_TYPES,
    OPPORTUNITY_STATUSES,
    REVENUE_EVENT_TYPES,
    VENTURE_STATUSES,
    compute_customer_metrics,
    create_automation_suggestion,
    create_checklist_item,
    create_customer,
    create_fulfillment_item,
    create_marketing_content,
    create_opportunity,
    create_revenue_event,
    create_validation_report,
    create_venture,
    dashboard_snapshot as ventures_dashboard_snapshot,
    delete_checklist_item,
    delete_customer,
    delete_fulfillment_item,
    delete_venture,
    dismiss_opportunity,
    get_opportunity,
    get_venture,
    init_ventures_db,
    list_automation_suggestions,
    list_checklist_items,
    list_customers,
    list_fulfillment_items,
    list_marketing_content,
    list_opportunities,
    list_revenue_events,
    list_validation_reports,
    list_ventures,
    promote_opportunity,
    recompute_and_store_health,
    update_automation_suggestion_status,
    update_checklist_item_status,
    update_customer_status,
    update_fulfillment_item_status,
    update_venture_concept,
    update_venture_operations_sop,
    update_venture_status,
)
from app.ventures_agent import (
    build_venture_content,
    generate_marketing_content,
    generate_operations_sop,
    narrate_financial_health,
    run_validation,
    scan_for_opportunities,
    scout_automation_opportunities,
)
from app.hf_markets_client import (
    PENDING_ORDER_FILE_PATH,
    read_order_result as read_bridge_order_result,
    write_pending_order as write_bridge_pending_order,
    clear_order_result as clear_bridge_order_result,
)
from app.legacy_vault import LEGACY_VAULT_TOOL_NAMES, LEGACY_VAULT_TOOLS, execute_legacy_vault_tool_call
from app.memory_agent import MEMORY_AGENT_TOOL_NAMES, MEMORY_AGENT_TOOLS, execute_memory_agent_tool_call
from app.operations_agent import OPERATIONS_TOOL_NAMES, OPERATIONS_TOOLS, build_operations_block, execute_operations_tool_call
from app.research_agent import RESEARCH_AGENT_TOOL_NAMES, RESEARCH_AGENT_TOOLS, execute_research_agent_tool_call
from app.web_tools import SERVER_TOOL_LABELS, WEB_FETCH_TOOL, WEB_SEARCH_TOOL, WEB_TOOLS
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
    get_ventures_last_viewed_at,
    init_db,
    list_conversations,
    list_decisions_for_venture,
    load_history,
    load_memory_records,
    log_activity,
    log_decision,
    mark_local_node_seen,
    mark_ventures_viewed,
    save_message,
    set_active_conversation,
    set_credits_exhausted,
    set_hf_markets_live_status_postgres,
)
from app.memory import FORGET_MEMORY_TOOL, SAVE_MEMORY_TOOL, build_memory_block, execute_tool_call
from app.focus import FOCUS_TOOL_NAMES, FOCUS_TOOLS, execute_focus_tool_call
from app.scheduled_notifications import (
    SCHEDULED_NOTIFICATION_TOOL_NAMES,
    SCHEDULED_NOTIFICATION_TOOLS,
    execute_scheduled_notification_tool_call,
)
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
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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


@asynccontextmanager
async def _pooled_postgres_conn():
    """Yields a fresh, pool-validated connection for the caller's own
    scope when DATA_BACKEND=postgres, else None (SQLite mode -- every
    *_db.py function already handles postgres_conn=None by using SQLite
    instead, unchanged). Replaces the old pattern of reading one
    long-lived app.state.postgres_conn shared across every background
    loop and HTTP request, kept alive by a separate task that could
    swap it out mid-use -- confirmed live (2026-09-22) to silently lose
    a write when a request's own commit raced that swap. A pool checkout
    is validated at checkout time and returned when this scope exits, so
    no two callers ever fight over the same connection object, and nothing
    needs to guess whether it's still alive."""
    if DATA_BACKEND != "postgres" or not hasattr(app.state, "postgres_pool"):
        yield None
        return
    async with app.state.postgres_pool.connection() as conn:
        yield conn


async def _trigger_scheduler_loop() -> None:
    while True:
        async with _pooled_postgres_conn() as postgres_conn:
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
        # Same pooled-checkout pattern as _trigger_scheduler_loop -- this
        # loop only ever runs in Mac mode (never started in cloud mode, see
        # run()), but still writes to shared Postgres when DATA_BACKEND=
        # postgres so the cloud instance's own reads see the same fresh
        # calendar data, not a Mac-only-visible cache.
        async with _pooled_postgres_conn() as postgres_conn:
            try:
                await sync_calendar_cache(postgres_conn)
            except Exception as exc:
                print(f"[calendar] sync tick failed: {exc}")
        await asyncio.sleep(CALENDAR_SYNC_INTERVAL_SECONDS)


HF_MARKETS_LIVE_PUSH_INTERVAL_SECONDS = 60


async def _hf_markets_live_push_loop(app: FastAPI) -> None:
    """Bridges HF Markets' live floating P&L to the cloud (2026-09-12) --
    hf_markets_client.py's local MT5 file only ever exists on this Mac's
    disk, so Render (what iOS talks to) had no way to see it at all.
    Mac-only (see its lifespan() registration, gated the same as
    _trigger_scheduler_loop/_calendar_sync_loop) -- Render could never
    read the file anyway. 60s matches the MT5 Expert Advisor's own write
    cadence (PcorpBalanceExport.mq5, see hf_markets_client.py's
    docstring) -- polling more often than the source itself updates
    would just resend the same number. Fails soft on every path (no EA
    running yet, a transient write failure) -- app/finance.py's
    get_hf_markets_live_status_for_dashboard() already treats a stale-or-
    missing cloud value as "nothing to show," same honest posture as
    every other local-file read in this app."""
    while True:
        await asyncio.sleep(HF_MARKETS_LIVE_PUSH_INTERVAL_SECONDS)
        if not hasattr(app.state, "postgres_pool"):
            continue
        status = get_hf_markets_live_status()
        if status is None:
            continue
        try:
            # A fresh checkout every tick (2026-09-22, replacing one
            # long-lived shared connection + a racing background health
            # check) -- the pool validates the connection at checkout
            # time, so there's no longer a window where this loop's own
            # write can land on a connection another task just closed
            # out from under it. See lifespan()'s own comment for the
            # full reasoning behind this change.
            async with app.state.postgres_pool.connection() as conn:
                await set_hf_markets_live_status_postgres(
                    conn, status["balance"], status["equity"], status["currency"], status["updated_at"]
                )
        except Exception as exc:
            print(f"[hf_markets_live_push] failed: {type(exc).__name__}: {exc}")


# 5s (was 20s, 2026-09-22) -- matches PCorpBridge_PollSeconds' own drop
# to 5s: a real live test showed the combined ~40s worst-case latency
# (this loop's 20s + the bridge's own 20s) let USA100 drift several
# points past the 50-point price-staleness tolerance before an approval
# was even checked. ~10s worst-case latency now, tolerance unchanged.
TRADE_PROPOSAL_SYNC_INTERVAL_SECONDS = 5
# Matches the plan doc's PCorpBridge_MaxCommandAgeSeconds -- if the bridge
# EA hasn't produced a result within this window (MT5 not running, chart
# not attached, Wine/MT5 crashed), stop waiting on it rather than polling
# forever; the proposal is left 'approved' with no result, visible to Josh
# as stuck rather than silently retried.
TRADE_PROPOSAL_RESULT_TIMEOUT_SECONDS = 900


async def _trade_proposal_sync_loop(app: FastAPI) -> None:
    """The Mac-only bridge between a phone-approved proposal (a row in the
    shared Postgres trade_proposals table, reachable from anywhere) and
    PCorpExecutionBridge.mq5 (a separate MQL5 Expert Advisor that can only
    ever see this Mac's own filesystem, via MT5 running under Wine). An
    approval from the phone only ever changes a Postgres row -- nothing
    else bridges it to the Mac's MQL5 Files directory unless this loop
    does. Mac-only for the same reason as the two scheduler loops and
    hf_markets_live_push_loop above: this literally cannot run anywhere
    else, since only the Mac can see the bridge EA's files at all.

    One proposal in flight at a time, by construction: it only starts a
    new one once pcorp_pending_order.json is confirmed absent (the
    previous cycle's write already consumed), so a slow/stuck bridge
    naturally serializes rather than racing multiple command files."""
    while True:
        await asyncio.sleep(TRADE_PROPOSAL_SYNC_INTERVAL_SECONDS)
        if not hasattr(app.state, "postgres_pool"):
            continue
        try:
            # A fresh pool checkout for this whole tick (2026-09-22,
            # replacing the old shared app.state.postgres_conn + racing
            # background health check) -- this is the exact loop whose
            # own approve-write got silently lost to that race during
            # live testing. The pool validates the connection at
            # checkout, so there's no longer a window for another task's
            # reconnect to swap it out mid-use.
            async with app.state.postgres_pool.connection() as conn:
                try:
                    approved = await list_proposals(status="approved", postgres_conn=conn)
                except Exception as exc:
                    print(f"[trade_proposal_sync] failed to list approved proposals: {type(exc).__name__}: {exc}")
                    continue

                for proposal in approved:
                    if proposal["command_written_at"] is None:
                        # Never write a second command file while one is
                        # still outstanding -- if PENDING_ORDER_FILE_PATH
                        # already exists, a previous proposal's command
                        # hasn't been picked up by the bridge yet; wait
                        # rather than overwrite it.
                        if PENDING_ORDER_FILE_PATH.exists():
                            continue
                        try:
                            # MQL5's StringToTime only parses
                            # "yyyy.mm.dd hh:mi:ss" (dot-separated date)
                            # -- Postgres/SQLite both return
                            # "yyyy-mm-dd hh:mi:ss[.ffffff]" (dash-
                            # separated). Reformatted here rather than in
                            # MQL5 (no datetime library there beyond
                            # StringToTime itself) so
                            # PCorpBridge_MaxCommandAgeSeconds' staleness
                            # check actually has a parseable timestamp to
                            # compare against -- a silent parse failure
                            # would otherwise mean that check never fires
                            # at all.
                            approved_dt = datetime.fromisoformat(proposal["resolved_at"])
                            write_bridge_pending_order({
                                "proposal_id": proposal["id"],
                                "symbol": proposal["symbol"],
                                "direction": proposal["direction"],
                                "entry_price": proposal["entry_price"],
                                "stop_loss": proposal["stop_loss"],
                                "take_profit": proposal["take_profit"],
                                "risk_pct": proposal["risk_pct"],
                                "approved_at": approved_dt.strftime("%Y.%m.%d %H:%M:%S"),
                                "comment": f"pcorp-{proposal['id']}",
                            })
                            await mark_command_written(proposal["id"], postgres_conn=conn)
                        except Exception as exc:
                            print(f"[trade_proposal_sync] failed to write command for #{proposal['id']}: {type(exc).__name__}: {exc}")
                        continue

                    # Command already written -- watching for the bridge's result.
                    result = read_bridge_order_result()
                    if result is None or result.get("proposal_id") != proposal["id"]:
                        # Real timeout, checked against when THIS proposal's
                        # command was written, not wall-clock since the loop
                        # started -- an old stuck proposal must not block a later
                        # one from ever timing out too.
                        written_at = datetime.fromisoformat(proposal["command_written_at"])
                        if written_at.tzinfo is None:
                            written_at = written_at.replace(tzinfo=timezone.utc)
                        age = (datetime.now(timezone.utc) - written_at).total_seconds()
                        if age > TRADE_PROPOSAL_RESULT_TIMEOUT_SECONDS:
                            try:
                                await record_execution_result(
                                    proposal["id"], success=False, ticket=None,
                                    result_summary="Timed out waiting for the execution bridge -- MT5/the bridge EA may not be running.",
                                    postgres_conn=conn,
                                )
                            except Exception as exc:
                                print(f"[trade_proposal_sync] failed to record timeout for #{proposal['id']}: {type(exc).__name__}: {exc}")
                        continue

                    try:
                        await record_execution_result(
                            proposal["id"],
                            success=bool(result.get("success")),
                            ticket=str(result["ticket"]) if result.get("ticket") else None,
                            result_summary=json.dumps(result),
                            postgres_conn=conn,
                        )
                        clear_bridge_order_result()
                    except Exception as exc:
                        print(f"[trade_proposal_sync] failed to record result for #{proposal['id']}: {type(exc).__name__}: {exc}")
        except Exception as exc:
            print(f"[trade_proposal_sync] tick failed: {type(exc).__name__}: {exc}")


# Automated market scan (2026-09-22, confirmed with Josh directly: hourly,
# USA100/NDX only, in-app banner rather than a push notification -- real
# push requires a paid Apple Developer account, which he's declined
# before). This loop ONLY EVER CREATES a proposal (status='pending'),
# exactly the same inert row a manually-typed one is -- it never
# approves or executes anything itself. The human-approval boundary this
# whole feature exists to enforce is completely unchanged by this: the
# only thing automated here is noticing a setup might be worth looking
# at, never authorizing money to move.
MARKET_SCAN_INTERVAL_SECONDS = 3600
MARKET_SCAN_SYMBOL = "USA100"
# Distinguishes a scan-generated proposal from one Josh typed himself --
# no separate DB column for this; a plain, greppable prefix on reasoning
# is enough for the loop's own duplicate-avoidance check below and for
# the UI to label these differently.
MARKET_SCAN_REASONING_PREFIX = "[Automated hourly scan] "


async def _market_scan_loop(app: FastAPI) -> None:
    """Once an hour, asks the same Trading Signals agent
    (generate_signal) Josh can already trigger by hand whether USA100
    has a real, concrete setup worth a look -- if it comes back with an
    actual suggested_trade (the same well-defined block extract_trade_
    suggestion already parses for the UI's own "Propose This Trade"
    button, never free-form prose), stages it as a normal pending
    proposal. If the model says there's no clear setup right now (the
    common case), suggested_trade is None and nothing is created --
    this loop doesn't lower the bar for what counts as worth proposing
    just because it's running unattended.

    Skips the tick entirely if a scan-generated proposal for this
    symbol is already sitting pending -- otherwise every quiet hour
    with the same lingering setup would pile up a fresh duplicate
    before Josh has even seen the last one."""
    while True:
        await asyncio.sleep(MARKET_SCAN_INTERVAL_SECONDS)
        if not hasattr(app.state, "postgres_pool"):
            continue
        try:
            async with app.state.postgres_pool.connection() as conn:
                pending = await list_proposals(status="pending", postgres_conn=conn)
                already_queued = any(
                    p["symbol"] == MARKET_SCAN_SYMBOL and p["reasoning"].startswith(MARKET_SCAN_REASONING_PREFIX)
                    for p in pending
                )
                if already_queued:
                    continue

                api_key = os.environ.get("ANTHROPIC_API_KEY")
                if not api_key:
                    continue
                client = AsyncAnthropic(api_key=api_key)
                reply, _history = await ti_generate_signal(client, MARKET_SCAN_SYMBOL)
                _cleaned_reply, suggested_trade = extract_trade_suggestion(reply)
                if suggested_trade is None:
                    continue

                await create_proposal(
                    suggested_trade["symbol"],
                    suggested_trade["direction"],
                    suggested_trade["entry_price"],
                    suggested_trade["stop_loss"],
                    suggested_trade["take_profit"],
                    suggested_trade["risk_pct"],
                    MARKET_SCAN_REASONING_PREFIX + _cleaned_reply,
                    postgres_conn=conn,
                )
                print(f"[market_scan] proposed a {suggested_trade['direction']} on {suggested_trade['symbol']}")
        except Exception as exc:
            print(f"[market_scan] tick failed: {type(exc).__name__}: {exc}")


# VENTURES Opportunity Radar (2026-09-23, Phase 1) -- daily, not hourly
# like the trading market scan: opportunity discovery is inherently
# slower-moving than a trading signal, and a daily cadence avoids
# showing Josh the same idea repeated many times before he's even
# looked at the last one. Flagged for his own adjustment once he's
# tried it. Same "only ever creates an inert record" boundary as the
# trading scan -- an opportunity needs Josh's own explicit "Promote"
# tap to become a real venture; nothing here spends money, launches
# anything, or contacts a customer.
VENTURE_SCAN_INTERVAL_SECONDS = 86400
# A short hand-maintained frame (who Josh is, what kind of builder he
# is) -- still genuinely useful and not something raw DB rows replace --
# followed by his REAL, live Alpha Mode Media/Joshx business data below.
# Previously (Phase 1-4) this was a static string with no live read of
# his actual business systems, flagged as open after every phase.
VENTURES_JOSH_CONTEXT_FRAMING = (
    "Josh is a filmmaker and entrepreneur, co-founder of Alpha Mode Media (a creative/content production "
    "business) and a freelance creative doing client video/photo work (tracked in P Corp OS's own Joshx "
    "division). He's technically comfortable, is building a systematic algorithmic trading setup, and has "
    "existing production workflows, editing templates, and client-facing processes from his creative work "
    "that could plausibly be repackaged as products or services beyond one-off client jobs. Below is his "
    "REAL, current business data -- ground opportunity/validation/marketing/financial/automation output in "
    "this specifically (his actual clients, projects, deliverables, invoices), not just the general framing "
    "above."
)


async def build_ventures_josh_context(postgres_conn=None) -> str:
    """Reuses the exact same block-builders already folded into Frank's
    own system prompt (build_alpha_mode_block/build_joshx_block) -- no
    new summarize logic, just composing already-proven real data."""
    parts = [VENTURES_JOSH_CONTEXT_FRAMING]
    alpha_mode_block = await build_alpha_mode_block(postgres_conn)
    if alpha_mode_block:
        parts.append(alpha_mode_block)
    joshx_block = await build_joshx_block(postgres_conn)
    if joshx_block:
        parts.append(joshx_block)
    return "".join(parts)
# Avoids piling up review work if Josh hasn't opened the app in a
# while -- past this many un-reviewed opportunities, the scan skips
# rather than adding more on top of a backlog he hasn't seen yet.
VENTURE_SCAN_MAX_PENDING = 10


async def _venture_scan_loop(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(VENTURE_SCAN_INTERVAL_SECONDS)
        if not hasattr(app.state, "postgres_pool"):
            continue
        try:
            async with app.state.postgres_pool.connection() as conn:
                pending = await list_opportunities(status="new", postgres_conn=conn)
                if len(pending) >= VENTURE_SCAN_MAX_PENDING:
                    continue

                api_key = os.environ.get("ANTHROPIC_API_KEY")
                if not api_key:
                    continue
                client = AsyncAnthropic(api_key=api_key)
                josh_context = await build_ventures_josh_context(conn)
                _reply, opportunities = await scan_for_opportunities(client, josh_context)
                for opp in opportunities:
                    await create_opportunity(
                        opp["name"], opp["description"], opp["revenue_model"], opp["setup_cost"],
                        opp["automation_potential"], opp["owner_time_required"], opp["confidence"],
                        opp["risks"], opp["recommended_next_step"], source="radar", postgres_conn=conn,
                    )
                if opportunities:
                    print(f"[venture_scan] surfaced {len(opportunities)} new opportunit{'y' if len(opportunities) == 1 else 'ies'}")
        except Exception as exc:
            print(f"[venture_scan] tick failed: {type(exc).__name__}: {exc}")


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
        await init_trade_intelligence_db()
        await init_trade_proposals_db()
        await init_ventures_db()
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
    if DATA_BACKEND == "postgres" and not hasattr(app.state, "postgres_pool"):
        if not CLOUD_POSTGRES_DSN:
            raise RuntimeError("DATA_BACKEND=postgres requires CLOUD_POSTGRES_DSN to be set.")
        # Real connection pool (2026-09-22), replacing one long-lived
        # shared connection plus a periodic health-check-and-swap task.
        # That combination caused a real, confirmed live bug: a request
        # (the trade-proposal approve route) would capture
        # app.state.postgres_conn, then the health-check loop -- a
        # SEPARATE asyncio task -- would detect it dead and silently
        # replace it mid-request, so the request's own later commit()
        # either raised (a real psycopg.OperationalError: connection
        # socket closed, seen live) or, worse, appeared to succeed while
        # the actual write never landed. That outage-era comment (2026-
        # 09-11) that used to live here explains the ORIGINAL problem
        # (a connection can go silently dead) but the fix it describes
        # (swap-in-place, read fresh via getattr) is exactly what
        # created the NEW race. A pool has no such race by construction:
        # every caller checks out its OWN connection for its OWN scope
        # (a request, a background-loop tick), gets it health-validated
        # at checkout time, and returns it when done -- nothing else can
        # ever swap a connection out from under a caller still using it.
        # min_size=1 keeps at least one warm; max_size=10 comfortably
        # covers real concurrent usage (confirmed live: 30 fully
        # concurrent create+approve+verify cycles ran clean; a
        # deliberately unrealistic 60-way burst hit PoolTimeout at
        # max_size=5, which is why this is 10, not 5 -- real usage here
        # is one person on at most two devices plus a handful of
        # background loops, nowhere near even the 30-way figure) without
        # over-provisioning Postgres-side connections.
        app.state.postgres_pool = AsyncConnectionPool(
            conninfo=CLOUD_POSTGRES_DSN,
            min_size=1,
            max_size=10,
            kwargs={"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3},
            open=False,
        )
        await app.state.postgres_pool.open()
        async with app.state.postgres_pool.connection() as conn:
            await init_trade_intelligence_db(postgres_conn=conn)
            await init_trade_proposals_db(postgres_conn=conn)
            await init_ventures_db(postgres_conn=conn)
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
        # HF Markets' live bridge (2026-09-12) -- Mac-only for the same
        # reason as the two loops above, plus there's simply nothing to
        # push in SQLite mode (no shared cloud DB for Render to read from).
        if DATA_BACKEND == "postgres" and not hasattr(app.state, "hf_markets_live_push_task"):
            app.state.hf_markets_live_push_task = asyncio.create_task(_hf_markets_live_push_loop(app))
        # Trade proposal execution bridge (2026-09-22) -- Mac-only for the
        # same reason as hf_markets_live_push_task just above: only this
        # Mac can see PCorpExecutionBridge.mq5's files at all.
        if DATA_BACKEND == "postgres" and not hasattr(app.state, "trade_proposal_sync_task"):
            app.state.trade_proposal_sync_task = asyncio.create_task(_trade_proposal_sync_loop(app))
        # Automated hourly market scan (2026-09-22) -- Mac-only for the
        # same "avoid two instances double-running the same background
        # job against shared Postgres" reasoning as every other loop
        # here (see the comment on _trigger_scheduler_loop's own
        # registration above), not because it needs the filesystem.
        if DATA_BACKEND == "postgres" and not hasattr(app.state, "market_scan_task"):
            app.state.market_scan_task = asyncio.create_task(_market_scan_loop(app))
        # VENTURES Opportunity Radar (2026-09-23) -- same Mac-only
        # reasoning as every other loop here.
        if DATA_BACKEND == "postgres" and not hasattr(app.state, "venture_scan_task"):
            app.state.venture_scan_task = asyncio.create_task(_venture_scan_loop(app))
    yield
    if hasattr(app.state, "trigger_scheduler_task"):
        app.state.trigger_scheduler_task.cancel()
        del app.state.trigger_scheduler_task
    if hasattr(app.state, "calendar_sync_task"):
        app.state.calendar_sync_task.cancel()
        del app.state.calendar_sync_task
    if hasattr(app.state, "hf_markets_live_push_task"):
        app.state.hf_markets_live_push_task.cancel()
        del app.state.hf_markets_live_push_task
    if hasattr(app.state, "trade_proposal_sync_task"):
        app.state.trade_proposal_sync_task.cancel()
        del app.state.trade_proposal_sync_task
    if hasattr(app.state, "market_scan_task"):
        app.state.market_scan_task.cancel()
        del app.state.market_scan_task
    if hasattr(app.state, "venture_scan_task"):
        app.state.venture_scan_task.cancel()
        del app.state.venture_scan_task
    if hasattr(app.state, "elevenlabs_client"):
        await app.state.elevenlabs_client.aclose()
        del app.state.elevenlabs_client
    if hasattr(app.state, "postgres_pool"):
        await app.state.postgres_pool.close()
        del app.state.postgres_pool


app = FastAPI(title="P Corp OS Backend", lifespan=lifespan)


# Real bug found live (2026-09-22, same night as the pool migration
# itself): these specific routes do a brief DB read, then a slow
# external Claude API call (real search/thinking, confirmed to take
# 7+ minutes with an attached image) before returning anything. Holding
# a pooled connection open for that ENTIRE span -- what the middleware
# below does for every other route -- means the connection can go stale
# from simply sitting idle that long (confirmed live: Postgres closed it
# server-side mid-request), so the final commit-on-release fails and a
# request that already did all the expensive LLM work still 500s. It
# also starves the pool of a connection for minutes over something that
# needs it for milliseconds.
#
# Listed as exact paths, not a blanket "/trade-intelligence/" prefix --
# the trades/proposals CRUD routes under that same prefix are fast,
# pure-DB operations with no LLM call at all, and still want (and are
# safe with) the normal whole-request checkout every other route gets.
# Only the ones that actually call a Claude endpoint manage their own,
# much shorter-lived checkout instead (see e.g. trade_intelligence_setup).
_SLOW_ROUTE_PATHS = frozenset({
    "/trade-intelligence/chart-analysis",
    "/trade-intelligence/setup",
    "/trade-intelligence/position-review",
    "/trade-intelligence/signal",
    "/trade-intelligence/trades/breakdown",
    "/ventures/opportunities/scan",
})
# The two above all have literal, static paths -- a plain frozenset membership
# check works. /ventures/{id}/validate and /ventures/{id}/build (2026-09-24,
# Phase 2) are also slow (a real Claude call) but have a dynamic venture_id
# path segment, so they need a pattern match instead of exact-string matching.
_SLOW_VENTURE_ROUTE_RE = re.compile(
    r"^/ventures/\d+/(validate|build|financial-analysis|marketing-content|operations-sop|automation-scan)$"
)


def _is_slow_route(method: str, path: str) -> bool:
    # Method-checked, not just path -- a real bug found live (2026-09-24):
    # GET /ventures/{id}/marketing-content (a fast, plain DB read for the
    # list endpoint) shares the EXACT path string with POST
    # /ventures/{id}/marketing-content (the slow Claude-calling create
    # endpoint). A path-only match excluded the GET from getting a pooled
    # connection too, so it silently fell through to the empty local
    # SQLite file instead of the real shared Postgres. Every slow
    # (Claude-calling) route in this app is a POST, so gating on that is
    # safe, not just a narrow fix for this one collision.
    if method != "POST":
        return False
    return path in _SLOW_ROUTE_PATHS or bool(_SLOW_VENTURE_ROUTE_RE.match(path))


@app.middleware("http")
async def postgres_pool_scope(request: Request, call_next):
    """Checks out a fresh, pool-validated connection for this request's
    own duration and puts it on request.state.postgres_conn -- every
    route already reads exactly that attribute (2026-09-22 migration
    off one shared, long-lived app.state.postgres_conn). Guarantees each
    request gets a connection nothing else can swap out from under it
    mid-flight, which is what silently lost a real write during live
    testing under the old design. A no-op in SQLite mode, before the
    pool exists yet (startup ordering), or for _SLOW_ROUTE_PATHS
    (see that constant's own comment -- those routes manage their own,
    much shorter-lived checkouts instead)."""
    if (
        DATA_BACKEND != "postgres"
        or not hasattr(app.state, "postgres_pool")
        or _is_slow_route(request.method, request.url.path)
    ):
        return await call_next(request)
    async with app.state.postgres_pool.connection() as conn:
        request.state.postgres_conn = conn
        return await call_next(request)


# Just the apple-touch-icon for now (mobile.html's "Add to Home Screen"
# support) -- unauthenticated like /mobile itself, since it's a static
# icon with no sensitive content.
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/health")
async def health(_: None = Depends(verify_token)) -> dict[str, str]:
    return {"status": "ok"}


@app.get("/status")
async def status(request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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
        postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
        ok = await google_oauth.exchange_code_for_tokens(code, postgres_conn)
        _google_oauth_state = None
        if ok:
            body = "<html><body><h3>Connected. You can close this tab -- P Corp OS is now connected to Google.</h3></body></html>"
        else:
            body = "<html><body><h3>Something went wrong exchanging the authorization code. Try again.</h3></body></html>"
    return Response(content=body, media_type="text/html")


@app.get("/auth/google/status")
async def auth_google_status(request: Request, _: None = Depends(verify_token)) -> dict[str, bool]:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await compute_connected_apps_status(postgres_conn)


@app.get("/memory")
async def memory(request: Request, _: None = Depends(verify_token)) -> list[dict]:
    # View of what Frank has saved via the save_memory tool, excluding
    # anything forgotten (app/db.py's deleted_at) — the desktop shell's
    # "Frank" section reads this to make memory visible, rather than it
    # only being inspectable by querying SQLite directly.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await load_memory_records(postgres_conn)


@app.get("/operations/tasks")
async def operations_tasks(request: Request, _: None = Depends(verify_token)) -> list[dict]:
    # Makes the "Agents" nav section's task list real, rather than only
    # visible to Frank himself via the system-prompt snapshot.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await list_automation_rules(postgres_conn)


@app.get("/automations/runs")
async def automations_runs(request: Request, _: None = Depends(verify_token)) -> list[dict]:
    # Backs the "Automations" section's real firing history -- makes
    # automations visible when they happen, not something silent.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    await set_automation_rule_enabled(rule_id, body.enabled, postgres_conn)
    await record_tool_call(
        "update_automation_rule_ui", {"rule_id": rule_id, "enabled": body.enabled}, "ok", postgres_conn
    )
    return {"rule_id": rule_id, "enabled": body.enabled}


@app.delete("/automations/rules/{rule_id}")
async def automation_rule_delete(rule_id: str, request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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
async def trading_division_dashboard(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the desktop/iOS "Trading Division" section -- read-only, see
    # app/trading_division.py's own docstring for the full boundary.
    # postgres_conn added 2026-09-18 -- live_account/stock_movers both
    # need it for the cloud fallback path (iOS/Render), same dispatcher
    # pattern every other dashboard route already uses.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await trading_division_dashboard_snapshot(postgres_conn)


@app.post("/trading-division/holding-update")
async def trading_division_holding_update(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the dashboard tab's own "Get live update" action (2026-09-18,
    # "make everything more detailed and interactive") -- a real,
    # on-demand live web_search/web_fetch call, deliberately a plain
    # REST route rather than routed through the websocket chat, since
    # this tab has never needed BackendClient/chat plumbing at all.
    # Same real API-key guard websocket_chat already has -- this is the
    # first REST route (not just the websocket) to ever construct its
    # own AsyncAnthropic client.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set.")
    client = AsyncAnthropic(api_key=api_key)
    update = await get_holding_update(client, postgres_conn)
    return {"update": update}


class TradingDivisionStockUpdateRequest(BaseModel):
    symbol: str


@app.post("/trading-division/stock-update")
async def trading_division_stock_update(
    body: TradingDivisionStockUpdateRequest, _: None = Depends(verify_token)
) -> dict:
    # Backs "make stock movers clickable and interactive" (2026-09-18,
    # same-day follow-up) -- same shape as the holding-update route
    # above, generalized to any symbol from the movers list rather than
    # the one hardcoded NDX holding. No postgres_conn needed here --
    # get_stock_update doesn't touch account data at all, deliberately
    # (see its own docstring for why that framing would be wrong for a
    # mover Josh may not even hold).
    if not body.symbol.strip():
        raise HTTPException(status_code=400, detail="symbol is required")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set.")
    client = AsyncAnthropic(api_key=api_key)
    update = await get_stock_update(client, body.symbol)
    return {"update": update}


class TradeCreateRequest(BaseModel):
    symbol: str
    direction: str
    entry_price: float
    entry_timestamp: str
    size: float
    setup_tag: str
    timeframe: str
    exit_price: float | None = None
    exit_timestamp: str | None = None
    pnl: float | None = None
    screenshot_path: str | None = None
    notes: str | None = None
    ai_analysis: str | None = None


@app.post("/trade-intelligence/trades")
async def trade_intelligence_trade_create(
    body: TradeCreateRequest, request: Request, _: None = Depends(verify_token)
) -> dict:
    # Backs Trade Breakdown's log-a-trade form -- direct UI write, same
    # shape as Personal's own add_goal/add_habit routes above. Validated
    # here BEFORE ever reaching the DB (real bug found live, 2026-09-20):
    # a rejected INSERT on the shared Postgres connection leaves it in an
    # aborted-transaction state, breaking every other route sharing that
    # connection until something rolls it back -- same "check before
    # writing" discipline as update_person's own name-uniqueness check.
    # The DB's own CHECK constraints stay in place as a backstop, not the
    # primary guard.
    if body.direction not in ("long", "short"):
        raise HTTPException(status_code=400, detail=f"direction must be 'long' or 'short', got {body.direction!r}")
    if body.setup_tag not in SETUP_TAGS:
        raise HTTPException(status_code=400, detail=f"setup_tag must be one of {SETUP_TAGS}, got {body.setup_tag!r}")
    if body.timeframe not in TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"timeframe must be one of {TIMEFRAMES}, got {body.timeframe!r}")
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    try:
        trade_id = await ti_add_trade(
            body.symbol, body.direction, body.entry_price, body.entry_timestamp, body.size,
            body.setup_tag, body.timeframe, body.exit_price, body.exit_timestamp, body.pnl,
            body.screenshot_path, body.notes, body.ai_analysis, postgres_conn,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Could not log trade: {error}") from error
    await record_tool_call("add_trade_ui", body.model_dump(), "ok", postgres_conn)
    return {"id": trade_id}


@app.get("/trade-intelligence/trades")
async def trade_intelligence_trades_list(request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return {"trades": await ti_list_trades(postgres_conn)}


@app.delete("/trade-intelligence/trades/{trade_id}")
async def trade_intelligence_trade_delete(
    trade_id: int, request: Request, _: None = Depends(verify_token)
) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    deleted = await ti_delete_trade(trade_id, postgres_conn)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No trade with id {trade_id}")
    await record_tool_call("delete_trade_ui", {"trade_id": trade_id}, "ok", postgres_conn)
    return {"deleted": True}


class ImagePayload(BaseModel):
    media_type: str
    filename: str
    data: str  # base64


class ChartAnalysisRequest(BaseModel):
    images: list[ImagePayload] = []
    symbol: str | None = None
    note: str | None = None
    # Real back-and-forth conversations (2026-09-21, "I want to be able to
    # respond") -- history is entirely client-held and opaque: empty on
    # the first call (images/symbol/note seed it), non-empty + `message`
    # set on every follow-up. See trade_intelligence_agent.py's own
    # docstring for the full reasoning.
    history: list[dict[str, Any]] = []
    message: str | None = None


def _require_api_key() -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set.")
    return api_key


def _decode_image_payloads(images: list[ImagePayload]) -> list[dict]:
    # Shared by chart-analysis and trade-setup -- reuses the same
    # base64-decode + build_content_block path the websocket chat
    # attachment flow already uses (main.py's websocket_chat), no new
    # image-encoding logic invented. Same per-image MAX_ATTACHMENT_BYTES
    # cap as chat attachments.
    if len(images) > 4:
        raise HTTPException(status_code=400, detail="Attach at most 4 images at once.")
    image_blocks = []
    for image in images:
        try:
            raw_bytes = base64.b64decode(image.data)
        except Exception as error:
            raise HTTPException(status_code=400, detail=f"Could not decode image data: {error}") from error
        if len(raw_bytes) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=400, detail=f"Image exceeds the {MAX_ATTACHMENT_BYTES // (1024*1024)}MB limit.")
        image_block = build_content_block(image.media_type, image.filename, raw_bytes)
        if image_block.get("type") != "image":
            raise HTTPException(status_code=400, detail=f"Unsupported image type: {image.media_type}")
        image_blocks.append(image_block)
    return image_blocks


@app.post("/trade-intelligence/chart-analysis")
async def trade_intelligence_chart_analysis(body: ChartAnalysisRequest, _: None = Depends(verify_token)) -> dict:
    client = AsyncAnthropic(api_key=_require_api_key())
    if body.history:
        if not body.message:
            raise HTTPException(status_code=400, detail="message is required for a follow-up turn")
        history = body.history + [{"role": "user", "content": body.message}]
        reply = await run_conversational_turn(client, TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT_WITH_SUGGESTION, history)
        reply, suggested_trade = extract_trade_suggestion(reply)
        return {"reply": reply, "history": history, "suggested_trade": suggested_trade}

    if not body.images:
        raise HTTPException(status_code=400, detail="At least one image is required to start a chart analysis.")
    image_blocks = _decode_image_payloads(body.images)
    reply, history = await ti_analyze_chart(client, image_blocks, body.symbol, body.note)
    reply, suggested_trade = extract_trade_suggestion(reply)
    return {"reply": reply, "history": history, "suggested_trade": suggested_trade}


class TradeSetupRequest(BaseModel):
    images: list[ImagePayload] = []
    symbol: str | None = None
    question: str | None = None
    history: list[dict[str, Any]] = []
    message: str | None = None


@app.post("/trade-intelligence/setup")
async def trade_intelligence_setup(
    body: TradeSetupRequest, request: Request, _: None = Depends(verify_token)
) -> dict:
    # The comprehensive "should I take this trade" flow (2026-09-22) --
    # unlike chart-analysis/signal/position-review, the seed turn pulls
    # REAL account balance (live_account_summary) and Josh's own real
    # logged trade history (compute_breakdown_stats) as grounding, so
    # position-sizing/hold-duration advice is genuinely personalized, not
    # generic. Images are optional here (0-4) -- Josh may ask a pure text
    # question with no chart. Doesn't replace Chart Analysis/Signals/
    # Position Review; those stay as fast, narrow tools.
    client = AsyncAnthropic(api_key=_require_api_key())
    if body.history:
        if not body.message:
            raise HTTPException(status_code=400, detail="message is required for a follow-up turn")
        history = body.history + [{"role": "user", "content": body.message}]
        reply = await run_conversational_turn(
            client, TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT_WITH_SUGGESTION, history, tools=[WEB_SEARCH_TOOL, WEB_FETCH_TOOL]
        )
        reply, suggested_trade = extract_trade_suggestion(reply)
        return {"reply": reply, "history": history, "suggested_trade": suggested_trade}

    image_blocks = _decode_image_payloads(body.images)
    # Short-lived checkout, released BEFORE the slow Claude call below --
    # see _SLOW_ROUTE_PATHS' own comment for why this route doesn't use
    # the normal whole-request middleware checkout.
    async with _pooled_postgres_conn() as postgres_conn:
        account_context = await live_account_summary(postgres_conn)
        historical_context = await ti_compute_breakdown_stats(postgres_conn)
    reply, history = await analyze_trade_setup(
        client, image_blocks, body.symbol, body.question, account_context, historical_context
    )
    reply, suggested_trade = extract_trade_suggestion(reply)
    return {"reply": reply, "history": history, "suggested_trade": suggested_trade}


class PositionReviewRequest(BaseModel):
    symbol: str
    direction: str
    entry_price: float
    size: float
    current_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    history: list[dict[str, Any]] = []
    message: str | None = None


@app.post("/trade-intelligence/position-review")
async def trade_intelligence_position_review(
    body: PositionReviewRequest, _: None = Depends(verify_token)
) -> dict:
    # Advisory-only, same "second call mechanism" shape as trading-division's
    # own holding-update/stock-update routes -- never a Frank chat tool,
    # never reachable mid-conversation. Reasons only over the numbers
    # given here (trade_intelligence_agent's own hard boundary), never
    # assumes this represents a real open account position.
    client = AsyncAnthropic(api_key=_require_api_key())
    if body.history:
        if not body.message:
            raise HTTPException(status_code=400, detail="message is required for a follow-up turn")
        history = body.history + [{"role": "user", "content": body.message}]
        reply = await run_conversational_turn(client, TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT, history)
        return {"reply": reply, "history": history}

    if body.direction not in ("long", "short"):
        raise HTTPException(status_code=400, detail=f"direction must be 'long' or 'short', got {body.direction!r}")
    reply, history = await ti_review_position(
        client, body.symbol, body.direction, body.entry_price, body.size, body.current_price,
        body.stop_loss, body.take_profit,
    )
    return {"reply": reply, "history": history}


class TradeSignalRequest(BaseModel):
    symbol: str = "NDX"
    history: list[dict[str, Any]] = []
    message: str | None = None


@app.post("/trade-intelligence/signal")
async def trade_intelligence_signal(body: TradeSignalRequest, _: None = Depends(verify_token)) -> dict:
    # Advisory-only -- see PositionReviewRequest's own comment above for
    # the shared reasoning. Output only: no order is ever placed.
    # WEB_SEARCH_TOOL + WEB_FETCH_TOOL stay available on follow-up turns
    # too, so a later question ("what about after the Fed decision") can
    # trigger a fresh search/real economic-calendar fetch rather than
    # reasoning off stale seed-turn context.
    client = AsyncAnthropic(api_key=_require_api_key())
    if body.history:
        if not body.message:
            raise HTTPException(status_code=400, detail="message is required for a follow-up turn")
        history = body.history + [{"role": "user", "content": body.message}]
        reply = await run_conversational_turn(
            client, TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT_WITH_SUGGESTION, history, tools=[WEB_SEARCH_TOOL, WEB_FETCH_TOOL]
        )
        reply, suggested_trade = extract_trade_suggestion(reply)
        return {"reply": reply, "history": history, "suggested_trade": suggested_trade}

    if not body.symbol.strip():
        raise HTTPException(status_code=400, detail="symbol is required")
    reply, history = await ti_generate_signal(client, body.symbol)
    reply, suggested_trade = extract_trade_suggestion(reply)
    return {"reply": reply, "history": history, "suggested_trade": suggested_trade}


class TradeBreakdownRequest(BaseModel):
    history: list[dict[str, Any]] = []
    message: str | None = None


@app.post("/trade-intelligence/trades/breakdown")
async def trade_intelligence_breakdown(
    body: TradeBreakdownRequest, request: Request, _: None = Depends(verify_token)
) -> dict:
    # Deterministic stats (compute_breakdown_stats) computed first and
    # verified independently before ever being narrated -- the agent only
    # ever narrates these already-correct numbers, per its own system
    # prompt, never recomputing or eyeballing the raw trade log itself.
    # `stats` is only included on the seed response -- a follow-up
    # doesn't need it resent, the client already has it from the seed.
    client = AsyncAnthropic(api_key=_require_api_key())
    if body.history:
        if not body.message:
            raise HTTPException(status_code=400, detail="message is required for a follow-up turn")
        history = body.history + [{"role": "user", "content": body.message}]
        reply = await run_conversational_turn(client, TRADE_INTELLIGENCE_AGENT_SYSTEM_PROMPT, history)
        return {"reply": reply, "history": history}

    # Short-lived checkout, released BEFORE the Claude call below -- see
    # _SLOW_ROUTE_PATHS' own comment for why this route doesn't use the
    # normal whole-request middleware checkout.
    async with _pooled_postgres_conn() as postgres_conn:
        stats = await ti_compute_breakdown_stats(postgres_conn)
    if stats["closed_trades"] == 0:
        return {"reply": "No closed trades logged yet -- nothing to break down.", "history": [], "stats": stats}
    reply, history = await narrate_trade_breakdown(client, stats)
    return {"reply": reply, "history": history, "stats": stats}


# Backend-side ceiling on a single proposal's risk_pct, matching
# PCorpBridge_MaxRiskPct confirmed with Josh directly (2026-09-22). The
# REAL, load-bearing enforcement is in the bridge EA itself (hard-capped
# in MQL5 against real live account equity, not just an LLM's suggestion)
# -- this is defense in depth at the API boundary, same "validate before
# it reaches persistence" discipline already applied to setup_tag/
# direction/timeframe above, not the primary guard.
PROPOSAL_MAX_RISK_PCT = 2.0
# Widened from 900 to 6 hours (2026-09-22, the same night the automated
# hourly market scan below was added) -- an interactively-created
# proposal (Josh actively testing, approving within seconds) never came
# close to hitting 900s anyway, but a SCAN-generated one sits unreviewed
# until Josh happens to open the app, which could genuinely be hours.
# Safe to widen: the real protection against a stale price was never
# this TTL, it's PCorpBridge_PriceStaleTolerancePoints re-checking the
# LIVE price at the moment of approval/execution regardless of how long
# the proposal sat pending -- this TTL only ever existed to stop a
# long-forgotten proposal from cluttering the list forever, not to
# guard price freshness.
PROPOSAL_PENDING_TTL_SECONDS = 21600


async def _expire_stale_pending_proposals(postgres_conn) -> None:
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    for proposal in await list_proposals(status="pending", postgres_conn=postgres_conn):
        created_at = datetime.fromisoformat(proposal["created_at"])
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)
        if (now_utc - created_at).total_seconds() > PROPOSAL_PENDING_TTL_SECONDS:
            try:
                await resolve_proposal(proposal["id"], "expired", postgres_conn=postgres_conn)
            except Exception as exc:
                print(f"[trade_proposals] failed to expire #{proposal['id']}: {type(exc).__name__}: {exc}")


class TradeProposalCreateRequest(BaseModel):
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_pct: float
    reasoning: str
    computed_lots_estimate: float | None = None


@app.post("/trade-intelligence/proposals")
async def trade_proposal_create(
    body: TradeProposalCreateRequest, request: Request, _: None = Depends(verify_token)
) -> dict:
    # Never auto-created by the agent mid-conversation -- Josh explicitly
    # turns a Trade Setup reply he's already read into a proposal via a
    # dedicated action, same "human decides what becomes a proposal"
    # boundary the whole feature exists to enforce.
    if body.direction not in PROPOSAL_DIRECTIONS:
        raise HTTPException(status_code=400, detail=f"direction must be one of {PROPOSAL_DIRECTIONS}, got {body.direction!r}")
    if body.risk_pct <= 0 or body.risk_pct > PROPOSAL_MAX_RISK_PCT:
        raise HTTPException(
            status_code=400,
            detail=f"risk_pct must be between 0 and {PROPOSAL_MAX_RISK_PCT} (Josh's confirmed per-trade cap), got {body.risk_pct}",
        )
    if body.stop_loss == body.entry_price:
        raise HTTPException(status_code=400, detail="stop_loss cannot equal entry_price")
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    try:
        proposal_id = await create_proposal(
            body.symbol, body.direction, body.entry_price, body.stop_loss, body.take_profit,
            body.risk_pct, body.reasoning, body.computed_lots_estimate, postgres_conn,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Could not create proposal: {error}") from error
    await record_tool_call("create_trade_proposal_ui", body.model_dump(), "ok", postgres_conn)
    return {"id": proposal_id}


@app.get("/trade-intelligence/proposals")
async def trade_proposals_list(request: Request, status: str | None = None, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    await _expire_stale_pending_proposals(postgres_conn)
    return {"proposals": await list_proposals(status=status, postgres_conn=postgres_conn)}


@app.post("/trade-intelligence/proposals/{proposal_id}/approve")
async def trade_proposal_approve(proposal_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    await _expire_stale_pending_proposals(postgres_conn)
    resolved = await resolve_proposal(proposal_id, "approved", postgres_conn=postgres_conn)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"No pending proposal with id {proposal_id}")
    # Immediate, honest feedback rather than a silently-stuck approval
    # (2026-09-22 plan) -- reuses the exact same freshness check /status
    # already applies to local_node_last_seen_at.
    local_node_last_seen = await get_local_node_last_seen_at(postgres_conn)
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    local_node_online = (
        local_node_last_seen is not None
        and (now_utc - datetime.fromisoformat(local_node_last_seen)).total_seconds() < 150
    )
    await record_tool_call("approve_trade_proposal_ui", {"proposal_id": proposal_id}, "ok", postgres_conn)
    return {"approved": True, "local_node_online": local_node_online}


@app.post("/trade-intelligence/proposals/{proposal_id}/reject")
async def trade_proposal_reject(proposal_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    resolved = await resolve_proposal(proposal_id, "rejected", postgres_conn=postgres_conn)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"No pending proposal with id {proposal_id}")
    await record_tool_call("reject_trade_proposal_ui", {"proposal_id": proposal_id}, "ok", postgres_conn)
    return {"rejected": True}


@app.delete("/trade-intelligence/proposals/{proposal_id}")
async def trade_proposal_delete(proposal_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    deleted = await delete_proposal(proposal_id, postgres_conn=postgres_conn)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No proposal with id {proposal_id}")
    return {"deleted": True}


class VentureCreateRequest(BaseModel):
    name: str
    description: str | None = None
    status: str = "idea"
    type: str | None = None
    revenue_model: str | None = None
    owner_time: str | None = None
    automation_level: str | None = None
    setup_cost: float | None = None
    monthly_revenue: float = 0
    risk_level: str | None = None
    confidence: str | None = None
    notes: str | None = None


@app.get("/ventures/dashboard")
async def ventures_dashboard(request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    snapshot = await ventures_dashboard_snapshot(postgres_conn)
    ventures = await list_ventures(postgres_conn)
    return {**snapshot, "ventures": ventures}


@app.get("/ventures")
async def ventures_list(request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return {"ventures": await list_ventures(postgres_conn)}


@app.post("/ventures")
async def ventures_create(body: VentureCreateRequest, request: Request, _: None = Depends(verify_token)) -> dict:
    # Validated before it reaches the DB -- same "don't let a bad enum
    # value hit the shared Postgres connection" discipline as every
    # other CHECK-constrained table in this app (real bug found and
    # fixed live tonight for trade_intelligence_db.py's own setup_tag).
    if body.status not in VENTURE_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {VENTURE_STATUSES}, got {body.status!r}")
    for field_name, value in (
        ("owner_time", body.owner_time), ("automation_level", body.automation_level), ("risk_level", body.risk_level),
    ):
        if value is not None and value not in VENTURE_LEVELS:
            raise HTTPException(status_code=400, detail=f"{field_name} must be one of {VENTURE_LEVELS}, got {value!r}")
    if body.confidence is not None and body.confidence not in ("high", "medium", "low"):
        raise HTTPException(status_code=400, detail=f"confidence must be one of high/medium/low, got {body.confidence!r}")
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    try:
        venture_id = await create_venture(
            body.name, body.description, body.status, body.type, body.revenue_model, body.owner_time,
            body.automation_level, body.setup_cost, body.monthly_revenue, body.risk_level, body.confidence,
            None, body.notes, postgres_conn,
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Could not create venture: {error}") from error
    await record_tool_call("create_venture_ui", body.model_dump(), "ok", postgres_conn)
    return {"id": venture_id}


class VentureStatusUpdate(BaseModel):
    status: str


@app.patch("/ventures/{venture_id}/status")
async def ventures_update_status(
    venture_id: int, body: VentureStatusUpdate, request: Request, _: None = Depends(verify_token)
) -> dict:
    if body.status not in VENTURE_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {VENTURE_STATUSES}, got {body.status!r}")
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    updated = await update_venture_status(venture_id, body.status, postgres_conn)
    if not updated:
        raise HTTPException(status_code=404, detail=f"No venture with id {venture_id}")
    await record_tool_call("venture_status_update_ui", {"venture_id": venture_id, "status": body.status}, "ok", postgres_conn)
    return {"updated": True}


@app.delete("/ventures/{venture_id}")
async def ventures_delete(venture_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    deleted = await delete_venture(venture_id, postgres_conn)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No venture with id {venture_id}")
    await record_tool_call("venture_delete_ui", {"venture_id": venture_id}, "ok", postgres_conn)
    return {"deleted": True}


@app.get("/ventures/delta")
async def ventures_delta(request: Request, _: None = Depends(verify_token)) -> dict:
    # Modeled on compute_brief()'s own "WHAT CHANGED" section -- a real
    # "since you last looked" feed, not a fixed window. Ventures gets its
    # own last-viewed timestamp (last_ventures_viewed_at), separate from
    # The Brief's, since opening one screen isn't the same real action as
    # opening the other. Registered BEFORE /ventures/{venture_id} --
    # FastAPI matches routes in definition order, and a dynamic single-
    # segment path would otherwise shadow this static one (real bug
    # found live: "delta" got parsed as an attempted venture_id and
    # 422'd instead of ever reaching this handler).
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    last_viewed = await get_ventures_last_viewed_at(postgres_conn)
    recent_calls = await list_recent_calls(limit=100, postgres_conn=postgres_conn)
    venture_calls = [c for c in recent_calls if c["tool_name"].startswith("venture_")]
    changed = venture_calls if last_viewed is None else [c for c in venture_calls if c["created_at"] > last_viewed]
    await mark_ventures_viewed(postgres_conn)
    return {"events": changed}


@app.get("/ventures/opportunities")
async def ventures_opportunities_list(
    request: Request, status: str | None = None, _: None = Depends(verify_token)
) -> dict:
    # Registered BEFORE /ventures/{venture_id} for the same reason as
    # /ventures/delta above -- a real bug found live tonight: this route
    # (and delta) were both being shadowed by the dynamic route, since
    # Starlette matches a plain {venture_id} path parameter against ANY
    # non-empty segment at the routing level (the int type only gets
    # checked afterward, by FastAPI's own parameter validation, which is
    # too late to fall through to a differently-registered route).
    if status is not None and status not in OPPORTUNITY_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {OPPORTUNITY_STATUSES}, got {status!r}")
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return {"opportunities": await list_opportunities(status, postgres_conn)}


@app.post("/ventures/opportunities/scan")
async def ventures_opportunities_scan(_: None = Depends(verify_token)) -> dict:
    # This is a _SLOW_ROUTE_PATHS entry -- a real Claude call with web
    # search, the same multi-minute-capable shape as Trade
    # Intelligence's own routes. Manages its own short-lived DB
    # checkout rather than the normal whole-request middleware one --
    # see _SLOW_ROUTE_PATHS' own comment for why holding a pooled
    # connection through a slow external call is a real, already-fixed
    # bug class tonight, not a hypothetical one.
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set.")
    async with _pooled_postgres_conn() as postgres_conn:
        josh_context = await build_ventures_josh_context(postgres_conn)
    client = AsyncAnthropic(api_key=api_key)
    reply, opportunities = await scan_for_opportunities(client, josh_context)
    created_ids = []
    async with _pooled_postgres_conn() as postgres_conn:
        for opp in opportunities:
            new_id = await create_opportunity(
                opp["name"], opp["description"], opp["revenue_model"], opp["setup_cost"],
                opp["automation_potential"], opp["owner_time_required"], opp["confidence"],
                opp["risks"], opp["recommended_next_step"], source="radar", postgres_conn=postgres_conn,
            )
            created_ids.append(new_id)
        await record_tool_call("venture_opportunity_scan_ui", {"created_ids": created_ids}, "ok", postgres_conn)
    return {"reply": reply, "created_ids": created_ids}


@app.post("/ventures/opportunities/{opportunity_id}/promote")
async def ventures_opportunity_promote(
    opportunity_id: int, request: Request, _: None = Depends(verify_token)
) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    opportunity = await get_opportunity(opportunity_id, postgres_conn)
    if opportunity is None:
        raise HTTPException(status_code=404, detail=f"No opportunity with id {opportunity_id}")
    if opportunity["status"] != "new":
        raise HTTPException(status_code=400, detail=f"Opportunity is already {opportunity['status']}, not 'new'")
    venture_id = await create_venture(
        opportunity["name"], opportunity["description"], "idea", None, opportunity["revenue_model"],
        opportunity["owner_time_required"], opportunity["automation_potential"], opportunity["setup_cost"],
        0, None, opportunity["confidence"], None,
        f"Promoted from an opportunity (recommended next step: {opportunity['recommended_next_step']})",
        postgres_conn,
    )
    promoted = await promote_opportunity(opportunity_id, venture_id, postgres_conn)
    if not promoted:
        # Real race: something else resolved this opportunity between
        # our own read above and this write (e.g. promoted/dismissed
        # from another device at nearly the same moment). The venture
        # row we just created is harmless but orphaned -- soft-delete
        # it rather than leave a duplicate around.
        await delete_venture(venture_id, postgres_conn)
        raise HTTPException(status_code=409, detail="Opportunity was already resolved by another request")
    await record_tool_call("venture_opportunity_promote_ui", {"opportunity_id": opportunity_id, "venture_id": venture_id}, "ok", postgres_conn)
    return {"venture_id": venture_id}


@app.post("/ventures/opportunities/{opportunity_id}/dismiss")
async def ventures_opportunity_dismiss(
    opportunity_id: int, request: Request, _: None = Depends(verify_token)
) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    dismissed = await dismiss_opportunity(opportunity_id, postgres_conn)
    if not dismissed:
        raise HTTPException(status_code=404, detail=f"No pending opportunity with id {opportunity_id}")
    await record_tool_call("venture_opportunity_dismiss_ui", {"opportunity_id": opportunity_id}, "ok", postgres_conn)
    return {"dismissed": True}


@app.get("/ventures/{venture_id}")
async def ventures_get(venture_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    # Phase 1 never added a single-venture fetch -- the detail view needs
    # one, since the dashboard's own bulk list doesn't refresh per-venture.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    venture = await get_venture(venture_id, postgres_conn)
    if venture is None:
        raise HTTPException(status_code=404, detail=f"No venture with id {venture_id}")
    return venture


@app.post("/ventures/{venture_id}/validate")
async def ventures_validate(venture_id: int, _: None = Depends(verify_token)) -> dict:
    # Slow route (_is_slow_route's regex) -- a real Claude call with web
    # search, same reasoning as ventures_opportunities_scan above: manage
    # our own short-lived checkout rather than holding the whole-request
    # pooled connection through it.
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set.")
    async with _pooled_postgres_conn() as postgres_conn:
        venture = await get_venture(venture_id, postgres_conn)
        if venture is None:
            raise HTTPException(status_code=404, detail=f"No venture with id {venture_id}")
        josh_context = await build_ventures_josh_context(postgres_conn)
    client = AsyncAnthropic(api_key=api_key)
    reply, report = await run_validation(client, venture, josh_context)
    if report is None:
        return {"reply": reply, "report": None}
    async with _pooled_postgres_conn() as postgres_conn:
        report_id = await create_validation_report(
            venture_id, report["evidence"], report["assumptions"], report["unknowns"], report["risks"],
            report["verdict"], report["confidence"], postgres_conn=postgres_conn,
        )
        await recompute_and_store_health(venture_id, postgres_conn)
        await record_tool_call("venture_validate_ui", {"venture_id": venture_id}, "ok", postgres_conn)
    return {"reply": reply, "report": {**report, "id": report_id}}


@app.get("/ventures/{venture_id}/validation-reports")
async def ventures_validation_reports_list(
    venture_id: int, request: Request, _: None = Depends(verify_token)
) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return {"reports": await list_validation_reports(venture_id, postgres_conn)}


@app.post("/ventures/{venture_id}/build")
async def ventures_build(venture_id: int, _: None = Depends(verify_token)) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set.")
    async with _pooled_postgres_conn() as postgres_conn:
        venture = await get_venture(venture_id, postgres_conn)
        if venture is None:
            raise HTTPException(status_code=404, detail=f"No venture with id {venture_id}")
        josh_context = await build_ventures_josh_context(postgres_conn)
    client = AsyncAnthropic(api_key=api_key)
    reply, concept = await build_venture_content(client, venture, josh_context)
    if concept is None:
        return {"reply": reply, "concept": None}
    async with _pooled_postgres_conn() as postgres_conn:
        await update_venture_concept(
            venture_id, concept["concept_summary"], concept["positioning_copy"], postgres_conn=postgres_conn
        )
        # Builder's suggested steps become real checklist rows Josh can
        # edit/reorder/delete afterward -- confirmed with Josh: Builder and
        # the Launch Engine checklist work as one pipeline, not two
        # independent systems.
        for step in concept["sop_steps"]:
            await create_checklist_item(venture_id, step, source="builder", postgres_conn=postgres_conn)
        await recompute_and_store_health(venture_id, postgres_conn)
        await record_tool_call("venture_build_ui", {"venture_id": venture_id}, "ok", postgres_conn)
    return {"reply": reply, "concept": concept}


class ChecklistItemCreateRequest(BaseModel):
    title: str


@app.get("/ventures/{venture_id}/checklist")
async def ventures_checklist_list(venture_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return {"items": await list_checklist_items(venture_id, postgres_conn)}


@app.post("/ventures/{venture_id}/checklist")
async def ventures_checklist_create(
    venture_id: int, body: ChecklistItemCreateRequest, request: Request, _: None = Depends(verify_token)
) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    item_id = await create_checklist_item(venture_id, body.title, source="manual", postgres_conn=postgres_conn)
    await record_tool_call("venture_checklist_create_ui", {"venture_id": venture_id, "title": body.title}, "ok", postgres_conn)
    return {"id": item_id}


class ChecklistItemStatusUpdate(BaseModel):
    status: str


@app.patch("/ventures/{venture_id}/checklist/{item_id}")
async def ventures_checklist_update_status(
    venture_id: int, item_id: int, body: ChecklistItemStatusUpdate, request: Request,
    _: None = Depends(verify_token),
) -> dict:
    if body.status not in CHECKLIST_ITEM_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"status must be one of {CHECKLIST_ITEM_STATUSES}, got {body.status!r}"
        )
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    updated = await update_checklist_item_status(item_id, body.status, postgres_conn)
    if not updated:
        raise HTTPException(status_code=404, detail=f"No checklist item with id {item_id}")
    await recompute_and_store_health(venture_id, postgres_conn)
    await record_tool_call("venture_checklist_status_update_ui", {"item_id": item_id, "status": body.status}, "ok", postgres_conn)
    return {"updated": True}


@app.delete("/ventures/{venture_id}/checklist/{item_id}")
async def ventures_checklist_delete(
    venture_id: int, item_id: int, request: Request, _: None = Depends(verify_token)
) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    deleted = await delete_checklist_item(item_id, postgres_conn)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No checklist item with id {item_id}")
    await record_tool_call("venture_checklist_delete_ui", {"item_id": item_id}, "ok", postgres_conn)
    return {"deleted": True}


@app.post("/ventures/{venture_id}/launch")
async def ventures_launch(venture_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    # The launch gate -- no separate agent-style propose/approve pair is
    # needed here (unlike trade proposals, nothing autonomous is proposing
    # a launch; Josh moves his own venture forward himself). This satisfies
    # the original spec's "no automatic launch" boundary the same way
    # Phase 1 satisfied "no automatic spending": not a permission check
    # guarding an agent capability, but because nothing anywhere gives any
    # agent a path to call this route -- it's only reachable from a real
    # button tap in the venture detail UI.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    venture = await get_venture(venture_id, postgres_conn)
    if venture is None:
        raise HTTPException(status_code=404, detail=f"No venture with id {venture_id}")
    if venture["status"] != "build":
        raise HTTPException(
            status_code=400, detail=f"Venture must be in 'build' status to launch (currently {venture['status']!r})"
        )
    items = await list_checklist_items(venture_id, postgres_conn)
    pending = [item for item in items if item["status"] == "pending"]
    if pending:
        raise HTTPException(
            status_code=400,
            detail=f"{len(pending)} checklist item(s) still pending -- resolve or skip them before launching",
        )
    await update_venture_status(venture_id, "launch", postgres_conn)
    await log_decision(
        decision=f"Launched venture: {venture['name']}",
        reasoning=f"All {len(items)} checklist item(s) resolved.",
        venture_id=venture_id,
        postgres_conn=postgres_conn,
    )
    await recompute_and_store_health(venture_id, postgres_conn)
    await record_tool_call("venture_launch_ui", {"venture_id": venture_id}, "ok", postgres_conn)
    return {"launched": True}


@app.get("/ventures/{venture_id}/decisions")
async def ventures_decisions_list(venture_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return {"decisions": await list_decisions_for_venture(venture_id, postgres_conn)}


@app.post("/ventures/{venture_id}/financial-analysis")
async def ventures_financial_analysis(venture_id: int, _: None = Depends(verify_token)) -> dict:
    # Slow route -- a real Claude call, same short-lived-checkout reasoning
    # as every other Claude-calling Ventures route.
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set.")
    async with _pooled_postgres_conn() as postgres_conn:
        venture = await get_venture(venture_id, postgres_conn)
        if venture is None:
            raise HTTPException(status_code=404, detail=f"No venture with id {venture_id}")
        metrics = await compute_customer_metrics(venture_id, postgres_conn)
        josh_context = await build_ventures_josh_context(postgres_conn)
    client = AsyncAnthropic(api_key=api_key)
    reply = await narrate_financial_health(client, venture, metrics, josh_context)
    async with _pooled_postgres_conn() as postgres_conn:
        await record_tool_call("venture_financial_analysis_ui", {"venture_id": venture_id}, "ok", postgres_conn)
    return {"reply": reply}


class MarketingContentCreateRequest(BaseModel):
    content_type: str


@app.post("/ventures/{venture_id}/marketing-content")
async def ventures_marketing_content_create(
    venture_id: int, body: MarketingContentCreateRequest, _: None = Depends(verify_token)
) -> dict:
    if body.content_type not in MARKETING_CONTENT_TYPES:
        raise HTTPException(
            status_code=400, detail=f"content_type must be one of {MARKETING_CONTENT_TYPES}, got {body.content_type!r}"
        )
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set.")
    async with _pooled_postgres_conn() as postgres_conn:
        venture = await get_venture(venture_id, postgres_conn)
        if venture is None:
            raise HTTPException(status_code=404, detail=f"No venture with id {venture_id}")
        josh_context = await build_ventures_josh_context(postgres_conn)
    client = AsyncAnthropic(api_key=api_key)
    reply, content = await generate_marketing_content(client, venture, body.content_type, josh_context)
    if content is None:
        return {"reply": reply, "content": None}
    async with _pooled_postgres_conn() as postgres_conn:
        content_id = await create_marketing_content(
            venture_id, body.content_type, content["content"], postgres_conn=postgres_conn
        )
        await record_tool_call(
            "venture_marketing_content_create_ui", {"venture_id": venture_id, "content_type": body.content_type},
            "ok", postgres_conn,
        )
    return {"reply": reply, "content": {**content, "id": content_id, "content_type": body.content_type}}


@app.get("/ventures/{venture_id}/marketing-content")
async def ventures_marketing_content_list(venture_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return {"content": await list_marketing_content(venture_id, postgres_conn)}


@app.post("/ventures/{venture_id}/operations-sop")
async def ventures_operations_sop_generate(venture_id: int, _: None = Depends(verify_token)) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set.")
    async with _pooled_postgres_conn() as postgres_conn:
        venture = await get_venture(venture_id, postgres_conn)
        if venture is None:
            raise HTTPException(status_code=404, detail=f"No venture with id {venture_id}")
        josh_context = await build_ventures_josh_context(postgres_conn)
    client = AsyncAnthropic(api_key=api_key)
    reply, sop = await generate_operations_sop(client, venture, josh_context)
    if sop is None:
        return {"reply": reply, "sop": None}
    async with _pooled_postgres_conn() as postgres_conn:
        await update_venture_operations_sop(venture_id, sop["sop"], postgres_conn=postgres_conn)
        await record_tool_call("venture_operations_sop_generate_ui", {"venture_id": venture_id}, "ok", postgres_conn)
    return {"reply": reply, "sop": sop["sop"]}


@app.post("/ventures/{venture_id}/automation-scan")
async def ventures_automation_scan(venture_id: int, _: None = Depends(verify_token)) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set.")
    async with _pooled_postgres_conn() as postgres_conn:
        venture = await get_venture(venture_id, postgres_conn)
        if venture is None:
            raise HTTPException(status_code=404, detail=f"No venture with id {venture_id}")
        josh_context = await build_ventures_josh_context(postgres_conn)
    client = AsyncAnthropic(api_key=api_key)
    reply, suggestions = await scout_automation_opportunities(client, venture, josh_context)
    created_ids = []
    async with _pooled_postgres_conn() as postgres_conn:
        for suggestion in suggestions:
            new_id = await create_automation_suggestion(
                venture_id, suggestion["title"], suggestion["description"], suggestion["suggested_approach"],
                postgres_conn=postgres_conn,
            )
            created_ids.append(new_id)
        await record_tool_call(
            "venture_automation_scan_ui", {"venture_id": venture_id, "created_ids": created_ids}, "ok", postgres_conn
        )
    return {"reply": reply, "created_ids": created_ids}


@app.get("/ventures/{venture_id}/automation-suggestions")
async def ventures_automation_suggestions_list(
    venture_id: int, request: Request, status: str | None = None, _: None = Depends(verify_token)
) -> dict:
    if status is not None and status not in AUTOMATION_SUGGESTION_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"status must be one of {AUTOMATION_SUGGESTION_STATUSES}, got {status!r}"
        )
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return {"suggestions": await list_automation_suggestions(venture_id, status, postgres_conn)}


class AutomationSuggestionStatusUpdate(BaseModel):
    status: str


@app.patch("/ventures/{venture_id}/automation-suggestions/{suggestion_id}")
async def ventures_automation_suggestion_update_status(
    venture_id: int, suggestion_id: int, body: AutomationSuggestionStatusUpdate, request: Request,
    _: None = Depends(verify_token),
) -> dict:
    if body.status not in AUTOMATION_SUGGESTION_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"status must be one of {AUTOMATION_SUGGESTION_STATUSES}, got {body.status!r}"
        )
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    updated = await update_automation_suggestion_status(suggestion_id, body.status, postgres_conn)
    if not updated:
        raise HTTPException(status_code=404, detail=f"No automation suggestion with id {suggestion_id}")
    await record_tool_call(
        "venture_automation_suggestion_status_update_ui", {"suggestion_id": suggestion_id, "status": body.status},
        "ok", postgres_conn,
    )
    return {"updated": True}


class CustomerCreateRequest(BaseModel):
    name: str
    acquisition_source: str | None = None
    acquisition_cost: float | None = None


@app.post("/ventures/{venture_id}/customers")
async def ventures_customer_create(
    venture_id: int, body: CustomerCreateRequest, request: Request, _: None = Depends(verify_token)
) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    customer_id = await create_customer(
        venture_id, body.name, body.acquisition_source, body.acquisition_cost, postgres_conn=postgres_conn
    )
    await recompute_and_store_health(venture_id, postgres_conn)
    await record_tool_call("venture_customer_create_ui", {"venture_id": venture_id, "name": body.name}, "ok", postgres_conn)
    return {"id": customer_id}


@app.get("/ventures/{venture_id}/customers")
async def ventures_customers_list(venture_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return {"customers": await list_customers(venture_id, postgres_conn)}


class CustomerStatusUpdate(BaseModel):
    status: str


@app.patch("/ventures/{venture_id}/customers/{customer_id}")
async def ventures_customer_update_status(
    venture_id: int, customer_id: int, body: CustomerStatusUpdate, request: Request,
    _: None = Depends(verify_token),
) -> dict:
    if body.status not in CUSTOMER_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {CUSTOMER_STATUSES}, got {body.status!r}")
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    updated = await update_customer_status(customer_id, body.status, postgres_conn)
    if not updated:
        raise HTTPException(status_code=404, detail=f"No customer with id {customer_id}")
    await recompute_and_store_health(venture_id, postgres_conn)
    await record_tool_call("venture_customer_status_update_ui", {"customer_id": customer_id, "status": body.status}, "ok", postgres_conn)
    return {"updated": True}


@app.delete("/ventures/{venture_id}/customers/{customer_id}")
async def ventures_customer_delete(
    venture_id: int, customer_id: int, request: Request, _: None = Depends(verify_token)
) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    deleted = await delete_customer(customer_id, postgres_conn)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No customer with id {customer_id}")
    await recompute_and_store_health(venture_id, postgres_conn)
    await record_tool_call("venture_customer_delete_ui", {"customer_id": customer_id}, "ok", postgres_conn)
    return {"deleted": True}


class RevenueEventCreateRequest(BaseModel):
    amount: float
    event_type: str
    notes: str | None = None


@app.post("/ventures/{venture_id}/customers/{customer_id}/revenue-events")
async def ventures_revenue_event_create(
    venture_id: int, customer_id: int, body: RevenueEventCreateRequest, request: Request,
    _: None = Depends(verify_token),
) -> dict:
    if body.event_type not in REVENUE_EVENT_TYPES:
        raise HTTPException(
            status_code=400, detail=f"event_type must be one of {REVENUE_EVENT_TYPES}, got {body.event_type!r}"
        )
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    event_id = await create_revenue_event(
        customer_id, body.amount, body.event_type, body.notes, postgres_conn=postgres_conn
    )
    await recompute_and_store_health(venture_id, postgres_conn)
    await record_tool_call(
        "venture_revenue_event_create_ui",
        {"customer_id": customer_id, "amount": body.amount, "event_type": body.event_type}, "ok", postgres_conn,
    )
    return {"id": event_id}


@app.get("/ventures/{venture_id}/customers/{customer_id}/revenue-events")
async def ventures_revenue_events_list(
    venture_id: int, customer_id: int, request: Request, _: None = Depends(verify_token)
) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return {"events": await list_revenue_events(customer_id, postgres_conn)}


@app.get("/ventures/{venture_id}/customer-metrics")
async def ventures_customer_metrics(venture_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await compute_customer_metrics(venture_id, postgres_conn)


class FulfillmentItemCreateRequest(BaseModel):
    title: str


@app.get("/ventures/{venture_id}/customers/{customer_id}/fulfillment")
async def ventures_fulfillment_list(
    venture_id: int, customer_id: int, request: Request, _: None = Depends(verify_token)
) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return {"items": await list_fulfillment_items(customer_id, postgres_conn)}


@app.post("/ventures/{venture_id}/customers/{customer_id}/fulfillment")
async def ventures_fulfillment_create(
    venture_id: int, customer_id: int, body: FulfillmentItemCreateRequest, request: Request,
    _: None = Depends(verify_token),
) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    item_id = await create_fulfillment_item(customer_id, body.title, postgres_conn=postgres_conn)
    await record_tool_call("venture_fulfillment_create_ui", {"customer_id": customer_id, "title": body.title}, "ok", postgres_conn)
    return {"id": item_id}


class FulfillmentItemStatusUpdate(BaseModel):
    status: str


@app.patch("/ventures/{venture_id}/customers/{customer_id}/fulfillment/{item_id}")
async def ventures_fulfillment_update_status(
    venture_id: int, customer_id: int, item_id: int, body: FulfillmentItemStatusUpdate, request: Request,
    _: None = Depends(verify_token),
) -> dict:
    if body.status not in FULFILLMENT_ITEM_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"status must be one of {FULFILLMENT_ITEM_STATUSES}, got {body.status!r}"
        )
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    updated = await update_fulfillment_item_status(item_id, body.status, postgres_conn)
    if not updated:
        raise HTTPException(status_code=404, detail=f"No fulfillment item with id {item_id}")
    await record_tool_call("venture_fulfillment_status_update_ui", {"item_id": item_id, "status": body.status}, "ok", postgres_conn)
    return {"updated": True}


@app.delete("/ventures/{venture_id}/customers/{customer_id}/fulfillment/{item_id}")
async def ventures_fulfillment_delete(
    venture_id: int, customer_id: int, item_id: int, request: Request, _: None = Depends(verify_token)
) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    deleted = await delete_fulfillment_item(item_id, postgres_conn)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No fulfillment item with id {item_id}")
    await record_tool_call("venture_fulfillment_delete_ui", {"item_id": item_id}, "ok", postgres_conn)
    return {"deleted": True}




@app.get("/personal/dashboard")
async def personal_dashboard(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the desktop "Personal" section -- goals/habits only, see
    # app/personal_db.py's own docstring for scope. Stage 4 prep: this is
    # the one route currently wired to the dual-backend proof of concept --
    # every other route here is untouched and always reads SQLite.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await personal_dashboard_snapshot(postgres_conn)


class PersonalGoalCreate(BaseModel):
    title: str
    target_date: str | None = None
    notes: str | None = None


@app.post("/personal/goals")
async def personal_goal_create(
    body: PersonalGoalCreate, request: Request, _: None = Depends(verify_token)
) -> dict:
    # Backs Personal's new "+Add" goal form (2026-09-17, Editability Pass
    # 1) -- add_goal already existed as a Frank chat tool (personal_tools.py's
    # ADD_GOAL_TOOL); this is a direct UI path to the same function, not a
    # chat-mediated one, same shape as Joshx's own UI-driven writes below.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    title = await add_goal(body.title, body.target_date, body.notes, postgres_conn)
    await record_tool_call("add_goal_ui", body.model_dump(), "ok", postgres_conn)
    return {"title": title}


class PersonalHabitCreate(BaseModel):
    title: str
    cadence: str | None = None
    notes: str | None = None


@app.post("/personal/habits")
async def personal_habit_create(
    body: PersonalHabitCreate, request: Request, _: None = Depends(verify_token)
) -> dict:
    # Same reasoning as personal_goal_create above -- add_habit already
    # existed as a Frank tool (ADD_HABIT_TOOL), this is a direct UI path.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    title = await add_habit(body.title, body.cadence, body.notes, postgres_conn)
    await record_tool_call("add_habit_ui", body.model_dump(), "ok", postgres_conn)
    return {"title": title}


@app.get("/joshx/dashboard")
async def joshx_dashboard(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the desktop "Joshx" section -- Josh's independent freelance
    # creative business, completely separate from Alpha Mode Media. Phase
    # 1 scope only (clients/leads/projects) -- see app/joshx_db.py's own
    # docstring.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await joshx_dashboard_snapshot(postgres_conn)


@app.get("/joshx/analytics")
async def joshx_analytics(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the new performance-metrics tiles (2026-09-06, systems audit
    # §3) -- deliberately a separate endpoint from /joshx/dashboard, not
    # new keys on it, matching compute_performance_metrics()'s own
    # docstring on why that boundary matters.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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


class JoshxLeadConvert(BaseModel):
    project_name: str


@app.post("/joshx/leads/{lead_id}/convert-to-project")
async def joshx_lead_convert(
    lead_id: int, body: JoshxLeadConvert, request: Request, _: None = Depends(verify_token)
) -> dict:
    # Backs the lead detail view's "Convert to Project" action
    # (2026-09-18, direct follow-up to leads becoming clickable) --
    # id-based, same reasoning as joshx_lead_delete below. Reuses
    # convert_lead_to_project's existing lead_id kwarg (added alongside
    # this route) rather than duplicating its field-carry-forward/
    # status-flip transaction logic.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    if not body.project_name.strip():
        raise HTTPException(status_code=400, detail="project_name is required")
    result = await convert_lead_to_project(lead_id=lead_id, project_name=body.project_name, postgres_conn=postgres_conn)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No lead with id {lead_id}")
    await record_tool_call(
        "convert_joshx_lead_to_project_ui", {"lead_id": lead_id, "project_name": body.project_name}, "ok", postgres_conn
    )
    return result


@app.delete("/joshx/leads/{lead_id}")
async def joshx_lead_delete(lead_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the LEADS section's delete action (2026-08-31) -- soft
    # delete (leads.deleted_at), same reasoning as operations_db.py's
    # delete_task: a lead becoming a real project isn't tracked as a
    # link anywhere, so nothing auto-hides it once it's booked; this is
    # the explicit "get it off my list" action for a dormant one.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    deleted = await delete_lead_by_id(lead_id, postgres_conn)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No lead with id {lead_id}")
    await record_tool_call("delete_joshx_lead_ui", {"lead_id": lead_id}, "ok", postgres_conn)
    return {"lead_id": lead_id, "deleted": True}


@app.delete("/joshx/clients/{client_id}")
async def joshx_client_delete(client_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    # "Everything must be deletable if needed" (2026-08-31) -- same
    # soft-delete shape as the lead/project delete routes.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    deleted = await delete_client_by_id(client_id, postgres_conn)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No client with id {client_id}")
    await record_tool_call("delete_joshx_client_ui", {"client_id": client_id}, "ok", postgres_conn)
    return {"client_id": client_id, "deleted": True}


@app.delete("/joshx/projects/{project_id}")
async def joshx_project_delete(project_id: int, request: Request, _: None = Depends(verify_token)) -> dict:
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await people_dashboard_snapshot(postgres_conn)


class PersonCreate(BaseModel):
    name: str
    relationship_type: str | None = None
    company: str | None = None
    email: str | None = None
    phone: str | None = None


@app.post("/people")
async def person_create(body: PersonCreate, request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs People's new "+Add" form (2026-09-17, Editability Pass 1) --
    # add_person already existed as a Frank tool (people_tools.py's
    # ADD_PERSON_TOOL) and is itself an upsert keyed on name (case-
    # insensitive) -- reused as-is, not reimplemented, since typing an
    # existing name correctly updating that person rather than
    # duplicating is already its documented, desired behavior.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    fields = body.model_dump(exclude={"name"}, exclude_none=True)
    name = await add_person(body.name, postgres_conn, **fields)
    await record_tool_call("add_person_ui", body.model_dump(), "ok", postgres_conn)
    return {"name": name}


class PersonUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    relationship_type: str | None = None
    company: str | None = None
    notes: str | None = None
    next_follow_up_date: str | None = None
    follow_up_cadence_days: int | None = None


@app.patch("/people/{person_id}")
async def person_update(
    person_id: int, body: PersonUpdate, request: Request, _: None = Depends(verify_token)
) -> dict:
    # Backs People's new inline-edit fields (2026-09-17, Editability Pass
    # 1) -- id-based (update_person, not add_person's fuzzy name match)
    # since the UI already knows the exact row it's displaying, same
    # reasoning as Joshx's own id-based status/payment-status routes above.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    fields = body.model_dump(exclude_none=True)
    try:
        updated = await update_person(person_id, postgres_conn, **fields)
    except ValueError as error:
        # name is UNIQUE -- update_person already checks before writing,
        # so this means the new name collides with a different person.
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not updated:
        raise HTTPException(status_code=404, detail=f"No person with id {person_id}")
    await record_tool_call("update_person_ui", {"person_id": person_id, **fields}, "ok", postgres_conn)
    return {"person_id": person_id, **fields}


@app.get("/finance/dashboard")
async def finance_dashboard(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the desktop "Finance" section -- Josh's personal investment
    # tracking, Luno automatic + four manually-logged accounts. See
    # app/finance_db.py's own docstring for scope.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    # Real gap fixed live (2026-09-11): Luno's balances used to only ever
    # reflect the once-a-day, Mac-scheduler-only snapshot -- live_finance_dashboard
    # (app/finance.py) fetches the current real balance at request time
    # instead, same freshness compute_luno_zar_value below already gives
    # prices. See its own docstring for the full incident.
    snapshot = await live_finance_dashboard(postgres_conn)
    # Real overall Luno value, computed live against Luno's own price
    # feed (2026-08-24) -- see app/finance.py's compute_luno_zar_value()
    # docstring for why this can't just be a naive sum of raw balances.
    for account in snapshot["accounts"]:
        if account["name"] == "Luno" and account["holdings"]:
            account["luno_value"] = await compute_luno_zar_value(account["holdings"])
        elif account["name"] == "Nasdaq / Markets":
            # Real-time equity/floating P&L (2026-08-24) -- Josh wanted
            # to see this live during open trades, not just once a day.
            # Real gap found live (2026-09-12): the plain local-file read
            # only ever worked from the Mac itself -- Render (what iOS
            # talks to) always got None. get_hf_markets_live_status_for_dashboard
            # falls back to the Mac's periodically-pushed cloud copy when
            # the local file isn't there. See app/finance.py's docstring.
            account["hf_markets_live"] = await get_hf_markets_live_status_for_dashboard(postgres_conn)
    return snapshot


class FinanceBalanceUpdate(BaseModel):
    balance: float


@app.post("/finance/accounts/{account_name}/balance")
async def finance_account_balance_update(
    account_name: str, body: FinanceBalanceUpdate, request: Request, _: None = Depends(verify_token)
) -> dict:
    # Backs Finance's new inline-edit balances for the 4 manual accounts
    # (2026-09-17, Editability Pass 1) -- log_balance already existed as
    # a Frank tool (finance_tools.py's LOG_FINANCE_BALANCE_TOOL); this is
    # a direct UI path to the same function, not a chat-mediated one.
    # account_name is fuzzy-matched by log_balance itself (same as the
    # chat tool), not a strict id lookup -- the UI already has the exact
    # name string from the fetched dashboard, so this is safe in practice.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    matched_name = await log_balance(account_name, body.balance, postgres_conn=postgres_conn)
    if matched_name is None:
        raise HTTPException(status_code=404, detail=f"No account matching {account_name!r}")
    await record_tool_call(
        "log_balance_ui", {"account_name": account_name, "balance": body.balance}, "ok", postgres_conn
    )
    return {"account_name": matched_name, "balance": body.balance}


@app.get("/finance/concentration")
async def finance_concentration(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the new concentration-bars section (2026-09-06, systems audit
    # §4) -- two separate views (ZAR accounts, Luno holdings), never one
    # blended number. See app/finance.py's compute_concentration_metrics()
    # docstring for why.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await get_focus_objective(postgres_conn)


@app.post("/activity/log")
async def activity_log_endpoint(
    body: ActivityLogRequest, request: Request, _: None = Depends(verify_token)
) -> dict:
    # Shadow Mode's write path -- called by ActivityTracker.swift whenever
    # the frontmost app changes, not a Frank tool. See shadow_mode.py's
    # docstring for why capture and recall are split this way.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    await mark_local_node_seen(postgres_conn)
    return {"status": "ok"}


@app.get("/insights")
async def insights_endpoint(request: Request, _: None = Depends(verify_token)) -> list[dict]:
    # Real data behind the right rail's "Frank's Insights" card -- was
    # literal placeholder text before (see app/insights.py's docstring).
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await compute_insights(postgres_conn=postgres_conn)


@app.get("/brief")
async def brief_endpoint(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs "The Brief" (Face-Lift item 09) -- see app/brief.py's own
    # docstring. Calling this marks the brief as viewed (updates
    # app_state.last_brief_viewed_at), so this is a real state-changing
    # read, not side-effect-free -- deliberate, since "what changed"
    # always means "since you last actually looked."
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await compute_brief(postgres_conn)


@app.get("/triggers/rules")
async def trigger_rules_endpoint(request: Request, _: None = Depends(verify_token)) -> list[dict]:
    # Read-only visibility into the Proactive Triggers Layer's rule rows
    # (app/triggers_db.py) -- exists so the rule set can be inspected
    # without opening a SQLite file by hand. GET /triggers/status (below)
    # is the richer endpoint the actual Triggers UI uses; this one stays
    # as the plain rule-only view it always was.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    await set_rule_enabled(rule_type, body.enabled, postgres_conn)
    return {"rule_type": rule_type, "enabled": body.enabled}


@app.get("/triggers/status")
async def trigger_status_endpoint(request: Request, _: None = Depends(verify_token)) -> dict:
    # Backs the Triggers UI's main view -- every rule plus its currently
    # live-matching items, each flagged with whether it'd actually be in
    # *today's* digest per the decaying cadence (app/triggers.py's
    # compute_status(), entirely read-only -- viewing this can't consume
    # a cadence slot or alter what the next real digest sends).
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await compute_trigger_status(postgres_conn)


@app.post("/triggers/run-now")
async def trigger_run_now_endpoint(request: Request, _: None = Depends(verify_token)) -> dict:
    # Manual escape hatch for testing the digest without waiting for the
    # scheduler's send_hour gate (app/triggers.py's maybe_run_daily_digest)
    # -- runs the real rule checks and, if anything's due, actually sends
    # the email. Does not touch digest_schedule.last_sent_date, so it
    # won't interfere with the once-a-day scheduled run.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await compute_situation_room_alerts(postgres_conn)


@app.delete("/memory/{memory_id}")
async def forget_memory(memory_id: int, request: Request, _: None = Depends(verify_token)) -> dict[str, bool]:
    # Manual forgetting from the UI — same soft-delete Frank's own
    # forget_memory tool uses, just addressed by ID instead of title since
    # the UI already has it.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    forgotten = await forget_memory_by_id(memory_id, postgres_conn)
    return {"forgotten": forgotten}


@app.get("/history")
async def history(request: Request, _: None = Depends(verify_token)) -> list[dict]:
    # The active conversation's transcript — always the most recently
    # created one (app/db.py's get_active_conversation_id). This is what
    # backs the real chat thread built into WarRoomView.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    conversation_id = await get_active_conversation_id(postgres_conn)
    return await load_history(conversation_id, postgres_conn)


@app.post("/conversations")
async def new_conversation(request: Request, _: None = Depends(verify_token)) -> dict[str, int]:
    # "New chat" — memory (app/memory.py) still carries continuity forward;
    # this just starts a fresh transcript, and becomes the active one.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    conversation_id = await create_new_conversation(postgres_conn)
    return {"conversation_id": conversation_id}


@app.get("/conversations")
async def conversations(request: Request, q: str | None = None, _: None = Depends(verify_token)) -> list[dict]:
    # Backs the conversation history browser — reopening an older chat
    # needs a way to find it, indefinitely, as history accumulates over
    # time. `q`, when given, searches real message content across each
    # conversation, not just its preview.
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
    return await list_conversations(query=q, postgres_conn=postgres_conn)


@app.post("/conversations/{conversation_id}/activate")
async def activate_conversation(
    conversation_id: int, request: Request, _: None = Depends(verify_token)
) -> dict[str, int]:
    # Reopening an older conversation — makes it active without needing to
    # be the newest row (that's the whole reason app_state exists instead
    # of just "active = newest").
    postgres_conn = getattr(request.state, "postgres_conn", None) if DATA_BACKEND == "postgres" else None
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

    # Real bug found live (2026-09-12): Piper's voice model is a ~115MB
    # file downloaded once onto this Mac's disk (data/piper_voices/,
    # .gitignore'd -- see piper_tts.py's own docstring), never deployed to
    # Render. On Render, if ElevenLabs is also unconfigured/failing (the
    # actual trigger Josh hit -- a wrong ELEVENLABS_API_KEY/VOICE_ID from
    # the original deployment setup, same class of mistake as Supabase/
    # Anthropic/Luno's env vars before it), this fallback used to raise
    # PiperVoice.load()'s FileNotFoundError completely uncaught, surfacing
    # as a bare 500 with no server-side log line at all -- unlike
    # ElevenLabs' own failure two lines up, which at least explains
    # itself. Piper genuinely has no fallback of its own (it *is* the
    # fallback), so this can't recover -- but it can fail exactly as
    # loudly and debuggably as the ElevenLabs path above, instead of a
    # silent, unexplained crash.
    try:
        audio = await asyncio.to_thread(synthesize_wav_bytes, request.text)
        return Response(content=audio, media_type="audio/wav")
    except Exception as error:
        print(f"[speak] Piper also failed (no voice available at all): {error}")
        raise HTTPException(status_code=503, detail="Frank's voice is unavailable right now.") from error


@app.websocket("/ws")
async def websocket_chat(websocket: WebSocket) -> None:
    await websocket.accept()
    # Checked out once per websocket connection, not once per HTTP
    # request like every other route now does (2026-09-22 pool
    # migration) -- a websocket can stay open far longer than any single
    # HTTP request, so a per-message checkout would mean holding and
    # releasing a pooled connection dozens of times during one
    # conversation for no real benefit. This keeps the exact "computed
    # once per connection" design already documented below, just backed
    # by a pool checkout (validated at connect time) instead of one
    # shared, never-reverified global a background task could swap out
    # from under it -- the same race that caused a real, confirmed live
    # bug in the (now-removed) single-connection design.
    postgres_conn = None
    if DATA_BACKEND == "postgres" and hasattr(app.state, "postgres_pool"):
        postgres_conn = await app.state.postgres_pool.getconn()
    try:
        await _websocket_chat_session(websocket, postgres_conn)
    finally:
        if postgres_conn is not None:
            await app.state.postgres_pool.putconn(postgres_conn)


async def _websocket_chat_session(websocket: WebSocket, postgres_conn) -> None:
    ws_token = websocket.query_params.get("token")
    if ws_token != AUTH_TOKEN and not await verify_device_session(ws_token or "", postgres_conn):
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
    # Computed once per connection, not per turn -- see websocket_chat's
    # own comment above for why one pooled checkout for the whole
    # connection's lifetime is still the right call here. Reused below both
    # for building Frank's own system-prompt context (build_personal_block)
    # and for the personal-domain tool-dispatch branch further down --
    # a real bug found live (2026-09-10): build_personal_block() was
    # calling summarize() with no connection at all, meaning Frank's own
    # system-prompt view of his goals/habits stayed on SQLite even after
    # DATA_BACKEND=postgres went live, silently stale the moment a write
    # actually landed in Postgres instead.
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
    # Real gap found live (2026-09-24, connection-pool instability
    # investigation): psycopg3 defaults to autocommit=False, so the reads
    # above (verify_device_session/get_active_conversation_id/load_history)
    # leave this connection "idle in transaction" from Postgres's own
    # perspective. Every other route is fine because its own per-request
    # pooled connection gets reset (rolled back) automatically the moment
    # the request's `async with pool.connection()` block exits -- but this
    # websocket holds ONE checked-out connection for its ENTIRE session
    # (see websocket_chat's own comment above), so without an explicit
    # commit here, the connection sits "idle in transaction" -- not
    # returned, not usable by anything else -- for however long the socket
    # waits for Josh's first message. `save_message`'s own commit() closes
    # this out on the FIRST message either way, but a chat window just
    # left open with history loaded and nothing typed yet could hold this
    # open indefinitely, real confirmed cause of exhausting the pool's
    # max_size=10 (found live via a pg_stat_activity query: multiple
    # sessions sitting "idle in transaction" on this exact query).
    if postgres_conn is not None:
        await postgres_conn.commit()

    # Real gap found live (2026-09-11): nothing on either side sent any
    # traffic while the socket just sat waiting for Josh to type --
    # harmless on the Mac's old direct Tailscale connection (nothing in
    # between to time it out), but the real public-internet path to
    # Render almost certainly has a reverse proxy that drops an idle
    # WebSocket after some timeout, with no clean close frame the client
    # would recognize -- confirmed live as "endless connection errors"
    # the moment the app sat idle a while. A periodic keepalive keeps the
    # connection looking active to any intermediary. `[ping]` needs an
    # explicit, dedicated case on the client (BackendClient.swift) --
    # confirmed by reading it that any *unrecognized* bracketed text
    # falls into the same branch that appends to the visible reply *and*
    # clears `runningTool`, so a plain no-op text would both pollute the
    # transcript and wrongly hide the tool-running indicator mid-call.
    keepalive_task = asyncio.create_task(_websocket_keepalive(websocket))
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
                    client, system_prompt, history, websocket, conversation_id, postgres_conn, attachments=content_blocks
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
                await _safe_send(websocket, message)
                history.pop()
                continue
            except Exception as error:
                # A client-initiated stop (BackendClient.stopGenerating())
                # closes the socket mid-stream, which is exactly what
                # causes this branch to fire in the first place -- trying
                # to report the error back over an already-closed socket
                # would just raise a second, noisier exception, so that
                # attempt is best-effort only.
                await _safe_send(websocket, f"\n[backend error: {error}]")
                # Don't record a failed/interrupted turn in memory or on
                # disk — this branch means Claude/the database itself
                # genuinely failed (not just delivery to a dead socket,
                # which run_claude_turn's own sends now tolerate without
                # raising at all) -- keeps conversation state consistent
                # for the next message (or the reconnect stopGenerating()
                # makes).
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
            await _safe_send(websocket, "\n[done]")
    except WebSocketDisconnect:
        pass
    finally:
        keepalive_task.cancel()


async def _websocket_keepalive(websocket: WebSocket, interval_seconds: float = 20.0) -> None:
    """Sends a `[ping]` text frame on a fixed interval for the life of one
    /ws connection -- pure keepalive traffic, ignored by the client (see
    BackendClient.swift's dedicated `\\n[ping]` case), just here to stop an
    intermediary on the real Render network path from treating a socket
    that's idle between messages as dead. Exits cleanly on cancellation
    (the connection's own `finally` above) or once the socket is actually
    gone (`send_text` raises once the connection is closed, same as any
    other send after disconnect elsewhere in this handler)."""
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            await websocket.send_text("\n[ping]")
    except (asyncio.CancelledError, Exception):
        pass


async def _safe_send(websocket: WebSocket, text: str) -> None:
    """Best-effort delivery to a live socket (2026-09-11) -- swallows any
    failure so a client that went away (backgrounded/exited the app)
    never aborts the turn actually generating and being saved. Real gap
    found live: every send inside run_claude_turn's streaming/tool loop
    used to raise straight through to websocket_chat's outer generic
    `except Exception`, which deliberately discards the *entire* turn
    ("don't record a failed/interrupted turn") -- meaning Josh exiting
    the app mid-reply threw away Frank's real, otherwise-complete answer
    instead of just failing to deliver it live. A handful of error-
    reporting sends already did this exact try/except ad hoc; this is
    that same pattern, applied uniformly everywhere a dead socket could
    otherwise cut a turn short."""
    try:
        await websocket.send_text(text)
    except Exception:
        pass


async def run_claude_turn(
    client: AsyncAnthropic,
    system_prompt: str,
    history: list,
    websocket: WebSocket,
    conversation_id: int,
    postgres_conn: Any = None,
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
                *SCHEDULED_NOTIFICATION_TOOLS,
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
                    await _safe_send(websocket, event.text)
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
                    await _safe_send(websocket, f"\n[tool_start]{json.dumps({'label': label})}")
            final_message = await stream.get_final_message()

        if final_message.stop_reason != "tool_use":
            return assistant_text, generated_documents

        history.append({"role": "assistant", "content": final_message.content})
        tool_results = []
        for block in final_message.content:
            if block.type != "tool_use":
                continue
            await _safe_send(websocket, f"\n[tool_start]{json.dumps({'label': label_for_tool(block.name)})}")
            if block.name in FOCUS_TOOL_NAMES:
                result = await execute_focus_tool_call(block.name, block.input, postgres_conn)
            elif block.name in SCHEDULED_NOTIFICATION_TOOL_NAMES:
                result = await execute_scheduled_notification_tool_call(block.name, block.input, websocket)
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
                result = await execute_trading_division_agent_tool_call(
                    block.name, block.input, client, websocket, postgres_conn
                )
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
                result = await execute_email_tool_call(block.name, block.input, websocket, postgres_conn)
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
                await _safe_send(websocket, f"\n[notify]{notification}")
            elif block.name == "forget_memory" and result.startswith("Forgot:"):
                notification = json.dumps(
                    {"title": "Frank forgot something", "body": result.removeprefix("Forgot: ")}
                )
                await _safe_send(websocket, f"\n[notify]{notification}")
            elif block.name == "set_focus_objective":
                notification = json.dumps({"title": "Focus updated", "body": block.input.get("objective", "")})
                await _safe_send(websocket, f"\n[notify]{notification}")
            elif block.name == "log_decision":
                notification = json.dumps({"title": "Decision logged", "body": block.input.get("decision", "")})
                await _safe_send(websocket, f"\n[notify]{notification}")
            elif block.name == "link_records" and result.startswith("Linked:"):
                notification = json.dumps({"title": "Memories linked", "body": result.removeprefix("Linked: ")})
                await _safe_send(websocket, f"\n[notify]{notification}")
            elif block.name == "save_to_legacy_vault":
                notification = json.dumps({"title": "Legacy Vault updated", "body": block.input.get("title", "")})
                await _safe_send(websocket, f"\n[notify]{notification}")
            elif block.name == "delete_from_legacy_vault" and result.startswith("Deleted from Legacy Vault:"):
                notification = json.dumps(
                    {"title": "Legacy Vault entry removed", "body": result.removeprefix("Deleted from Legacy Vault: ")}
                )
                await _safe_send(websocket, f"\n[notify]{notification}")
            elif block.name in ALPHA_MODE_TOOL_NAMES:
                notification = json.dumps({"title": "Alpha Mode Media updated", "body": result})
                await _safe_send(websocket, f"\n[notify]{notification}")
            elif block.name in ("add_task", "update_task_status", "delete_task"):
                notification = json.dumps({"title": "Task updated", "body": result})
                await _safe_send(websocket, f"\n[notify]{notification}")
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
                await _safe_send(
                    websocket,
                    f"\n[document_generated]{json.dumps({'filename': document_filename, 'title': document_title})}",
                )

            automation_notification = await check_and_fire_automation(
                block.name, block.input, client, result, postgres_conn
            )
            if automation_notification:
                # Deliberately a separate notification, not folded into
                # the block above -- this is a rule firing as a real
                # side effect of the tool call, not the tool call's own
                # result, and the two shouldn't be conflated in the UI.
                await _safe_send(websocket, f"\n[notify]{json.dumps(automation_notification)}")
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
