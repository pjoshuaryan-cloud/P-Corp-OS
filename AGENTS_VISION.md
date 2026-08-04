# Agents Vision

Joshua's full multi-agent vision for P Corp OS, given directly (2026-08-01) when scoping the "Automations" placeholder section. Saved as-is, as real reference material — same role `FOUNDER_BRIEF.md` plays for the project overall — not a build spec to execute all at once. See `ROADMAP.md`/`CHANGELOG.md` for what's actually been built from this so far.

**Scope note added when this was saved:** several of these agents directly collide with things already deliberately fenced off elsewhere in the project, and shouldn't be built without revisiting those decisions first — not because the vision is wrong, but because the blockers are real:
- **Life Agent** (marriage, health) — the sensitive Phase 1 interview material, deliberately kept FileVault-only, not surfaced in general UI.
- **CFO Agent** — the Finance section; `PERSONALITY_SPEC.md` already flags finance as needing extra caution regardless of how anything else scores.
- **Trading Agent** — crosses the standing rule to keep P Corp OS and the trading robot in separate chat threads/sessions.
- **Engineering Agent** (code review, git, refactoring, "helping build P Corp itself") — this is the general agentic tool-use capability (file access, shell, git) already deliberately deferred at the very start of this project specifically because `SECURITY.md`'s permission/sandboxing model for that doesn't exist yet. Building this agent would silently undo that deferral.

Operations Agent (built 2026-07-31) isn't named in Joshua's list below by that name, but fills the same role as the general, cross-business execution/workflow support agent — distinct from Alpha Mode Agent, which is specific to Alpha Mode Media's own business domain.

---

## Executive Layer

### Frank — Role: Executive Intelligence

Frank is the only AI you directly interact with. He understands:

- Your goals
- Your businesses
- Your finances
- Your marriage
- Your projects
- Your calendar
- Your trading
- Your preferences
- Your long-term vision

Every request starts with Frank. Frank decides whether to answer directly or delegate to another agent.

---

## Business Division

### Alpha Mode Agent

Dedicated entirely to Alpha Mode.

Responsibilities:
- CRM
- Clients
- Proposals
- Invoices
- Crew
- Equipment
- Suppliers
- Shoots
- Deliverables
- Marketing calendar
- Reporting

Frank speaks to this agent instead of trying to remember every project detail himself.

---

## Creative Division

### Creative Director Agent

Since filmmaking is central to your work, this should be one of the most capable agents.

Responsibilities:
- Creative concepts
- Storyboards
- Shot lists
- Scripts
- Editing ideas
- Color references
- Music references
- Campaign ideas
- Moodboards
- Client pitches

Eventually it understands your personal style, including Project Obsidian and Alpha Mode.

**Scope note (2026-08-04):** Built as its own agent, sibling to Design Agent rather than combined -- deliberately kept to a clean division of labor: this agent owns concepts/storyboards/shot lists/scripts/campaign ideas/client pitches (the "what are we making and why" layer), Design Agent owns branding/UI/design systems (the "what does it look like as a system" layer). Carries the same Brand Guardian context and Personal Taste Model as Design Agent, and the same ask-before-generating behavior. "Project Obsidian" context still deliberately skipped, same as Design Agent -- not re-asked, applying the earlier decision consistently.

### Design Agent

Responsibilities:
- Branding
- UI
- Typography
- Logos
- Design systems
- Iconography
- Motion systems

It becomes your design partner.

**Full elaboration (2026-08-03, Joshua's own words, preserved in full):** It's not a "logo generator." It's a Creative Director + Brand Strategist + Senior Product Designer + UI/UX Lead + Motion Designer that has spent years learning how you think and create. If built properly, it could eventually become one of the most valuable agents inside P Corp.

Twelve capabilities, long-term:

1. **Brand Guardian** — knows Alpha Mode's guidelines (colors, typography, tone, photography style, client type, positioning) and P Corp's (minimal, premium, executive, military precision, modern OS). Protects consistency; flags when something drifts.
2. **Creative Director** — for a campaign ask, doesn't just generate posters. Asks objective, audience, placement, duration, budget, emotion first. Then produces moodboards, campaign ideas, story concepts, visual/art direction, shot concepts, motion references, typography/color/lighting direction, production references.
3. **UI Designer** — thinks like Apple. "Design the Settings page" → "This page has 14 options, users only use 5 regularly, let's simplify" → redesigns, explains why, creates components, maintains consistency.
4. **Design System Builder** — maintains buttons, icons, spacing, animations, colors, typography, components, cards. Every new screen automatically follows the design language.
5. **Motion Designer** — motion curves, durations, states, micro-interactions, sound suggestions, transitions. E.g. the P Corp OS orb's listening/speaking/thinking/sleeping states, all with consistent motion principles.
6. **Filmmaking Partner** — since Joshua is a filmmaker: "luxury commercial" → symmetrical compositions, negative space, controlled camera movement, natural lighting, restrained palette → shot list, storyboard, moodboard, lens suggestions, lighting references, editing rhythm, music direction, color grading notes. Understands how he actually makes films, not generic ideas.
7. **Logo Designer** — not "here's 10 logos." Researches competitors, industry, history, symbolism, scalability first, then explains why something works or doesn't. A branding consultant, not a generator.
8. **Typography Expert** — compares real candidates (Inter, Söhne, Neue Haas, SF Pro, Akkurat, Helvetica Now) on readability, emotion, licensing, accessibility before recommending one.
9. **Brand Evolution** — notices drift over time ("Alpha Mode has gradually shifted toward premium corporate work, I think the visual identity should evolve") and says so unprompted.
10. **Design Critic** — upload a UI, it critiques (navigation hierarchy, typography scale, spacing, primary-action emphasis, friction points), then redesigns it.
11. **Website Designer** — thinks customer journey, conversion, information architecture, animation, SEO, interaction, loading, performance, accessibility — not just pages.
12. **Personal Taste Model** — this is what makes it different from a generic assistant. After enough time, it just knows: Josh dislikes clutter, glassmorphism, over-designed interfaces, huge gradients, bright colors. He likes minimalism, premium, military precision, symmetry, negative space, thoughtful typography, luxury, cinematic composition. Eventually he stops having to explain his preferences at all.

Target interaction shape: "Frank, I need a new dashboard" → Design Agent spends real time, returns 2-3 named directions (e.g. "Option A: Minimal Apple-inspired," "Option B: Executive military," "Option C: Cinematic editorial") with a specific recommendation and reasoning, not just raw output.

**Scope note (2026-08-03):** Built as a single "Design Agent" per Joshua's explicit choice, not combined with Creative Director Agent above — first real version (same day) covers the Brand Guardian context (Alpha Mode + P Corp identities), the Personal Taste Model (his stated preferences, verbatim above), and the ask-before-generating / present-options-with-a-recommendation behavior, all doable as system-prompt content with no new infrastructure. Explicitly NOT built yet: Design Critic (needs image upload support in the chat UI, which doesn't exist), Brand Evolution tracking (needs persistent memory across sessions -- could reuse the existing save_memory/forget_memory tools later rather than new infrastructure), and true Design System maintenance (would mean the agent actually reading/tracking P Corp OS's real UI code, not just advising on it).

---

## Technology Division

### Engineering Agent

This is the one helping build P Corp itself.

Responsibilities:
- Code reviews
- Architecture
- Refactoring
- Documentation
- Testing
- Git
- APIs
- Databases
- Security

Eventually it becomes the lead engineer of P Corp.

### Research Agent

One of the most powerful agents.

Responsibilities: research literally anything — technology, markets, AI, competitors, business, economics, science, software, legal, industry trends.

It summarizes everything. Never dumps information. Only insights.

**Scope note (2026-08-04):** Built with genuine live web search from day one, unlike most other agents' first versions -- Anthropic's Messages API has a native, server-executed web search tool, so this didn't need new infrastructure the way real Gmail access (Communications Agent) or a knowledge graph (Memory Agent) would. Confirmed working live with real, current search results.

---

## Trading Division

### Trading Agent

Dedicated entirely to your trading ecosystem.

Responsibilities:
- Strategy development
- Market analysis
- Performance reports
- Risk reports
- Drawdown analysis
- Backtesting
- VPS monitoring
- Optimization
- Trade journal
- Version history

The trading robot executes strategies; this agent helps you improve them.

---

## Finance Division

### CFO Agent

Responsibilities: personal finances, business finances, cash flow, budgets, forecasts, taxes, investments, profit analysis, savings goals, invoices, expenses.

This eventually becomes your financial dashboard.

---

## Personal Division

### Life Agent

This agent exists for Joshua. Not Alpha Mode. Not trading. Joshua.

Responsibilities: marriage, health, fitness, habits, reading, learning, goals, travel, family, calendar, reminders, journal, reflection.

This is the agent protecting your personal life.

---

## Communication Division

### Communications Agent

Responsibilities: emails, messages, meeting notes, client replies, follow-ups, scheduling, summaries, writing.

It drafts communications, but Frank decides what to send.

**Scope note (2026-08-04):** Built as draft-only, deliberately -- "Frank decides what to send" above lines up exactly with the standing rule that sending any message on Joshua's behalf needs his own explicit approval, so there's no send tool at all rather than a send tool gated behind confirmation. No real inbox/calendar integration either -- that needs real Google OAuth infrastructure (Cloud project, consent screen, token storage), a genuinely separate, bigger project. The Gmail/Calendar MCP connectors available in a Claude Code session are scoped to that session only; the P Corp OS backend has no MCP client of its own and would need its own integration built from scratch if/when that's worth doing.

---

## Intelligence Division

### Memory Agent

This may become the most important agent after Frank.

Responsibilities: long-term memory, project memory, decision history, knowledge graph, ideas, lessons learned, conversations, preferences.

This is the reason Frank gets smarter over time.

**Scope note (2026-08-04):** Built as read/synthesis-only over the existing memory_records (app/memory.py, app/db.py) -- not a new "knowledge graph" or vector store, which is real infrastructure past what a flat-list-plus-system-prompt specialist needs to be useful today. save_memory/forget_memory stay Frank's own direct tools, not duplicated here. Worth revisiting the knowledge-graph piece once the record count is large enough that handing the whole list as context stops being enough.

---

## The Workflow

Imagine your morning. You open P Corp OS. Frank says:

> Good morning Josh.

You reply:

> Frank, what requires my attention today?

Frank responds:

> I've already checked with the Operations Agent, Alpha Mode Agent, Trading Agent, and Finance Agent. Here are the five decisions only you need to make today…

Notice something important: you never talk to the other agents. Frank does.
