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

---

## Intelligence Division

### Memory Agent

This may become the most important agent after Frank.

Responsibilities: long-term memory, project memory, decision history, knowledge graph, ideas, lessons learned, conversations, preferences.

This is the reason Frank gets smarter over time.

---

## The Workflow

Imagine your morning. You open P Corp OS. Frank says:

> Good morning Josh.

You reply:

> Frank, what requires my attention today?

Frank responds:

> I've already checked with the Operations Agent, Alpha Mode Agent, Trading Agent, and Finance Agent. Here are the five decisions only you need to make today…

Notice something important: you never talk to the other agents. Frank does.
