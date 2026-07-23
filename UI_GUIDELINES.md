# UI Guidelines

**Status:** Active — a real visual system now exists, built and iterated against the actual desktop shell (`desktop/`), not designed in the abstract.

## Purpose

Define what P Corp OS should feel like to use, so design decisions later have a standard to check against.

## Decided (from FOUNDER_BRIEF.md)

Opening the app should feel like entering headquarters, not opening another application. The home screen concept is the **War Room** (see `WAR_ROOM.md`). The interface should communicate readiness, clarity, and focus — not clutter, not gimmicks. Target qualities: purposeful, minimal, professional, disciplined, premium.

## Decided from building the first shell (2026-07-23)

**Visual language:** white/near-white surfaces, black text and accents, no color beyond that, generous whitespace, no visible seams between layout regions (background-tone contrast instead of hard divider lines — Joshua explicitly flagged divider lines as looking wrong on first look).

**Dark mode: real, designed, and user-controlled (added 2026-07-24)** — not a system-appearance flag. `Theme.swift` defines a light and a dark `AppTheme` (background, surface, borders, three text tiers, accent fill/text) injected via a custom environment key; every view reads colors from `@Environment(\.appTheme)` instead of hardcoded `Color.white`/`.black`. Toggled from Settings ("Dark Mode" under Appearance), backed by `@AppStorage` — the toggle, not the OS's own appearance setting, is the single source of truth for which mode is active (`.preferredColorScheme` is set explicitly to `.light` or `.dark`, never `.automatic`). Frank's orb and the P mark are deliberately NOT themed — they're fixed brand/identity elements regardless of mode, not chrome that flips for contrast.

**Frank's on-screen presence:** an irregular, organic "blob" shape — not a circle, not a mascot, no face. Built from a fixed set of points around a circle with gentle per-point radius variance, smoothed into one continuous outline (see `BlobShape` in `desktop/Sources/PCorpOS/WarRoomView.swift`), rendered with a radial gradient, a tight bright specular highlight, and a faint rim light for a liquid/3D feel rather than a flat disc. It floats — a slow vertical bob with a contact shadow beneath that widens/lightens as it rises and tightens/darkens as it falls, so the motion reads as floating rather than just sliding. Presence comes from shape, material, and motion only — consistent with FOUNDER_BRIEF.md's explicit direction that Frank's identity shouldn't come from a character on screen.

**Copy tone: military-style language, kept easy to understand, despite the clean/minimal visual design.** Confirmed directly by Joshua — the clean look and the terminology are separate decisions, not in tension. Examples decided so far: tasks are called **"Missions"** ("+ Mission" button, "New Mission" quick action), the home screen is the **War Room** / **Mission Control**, current focus is **Mission Status**. Apply this consistently to new copy going forward — when adding a label, ask whether a military/command-center framing fits before defaulting to generic SaaS-dashboard language ("Tasks," "Dashboard," "Notifications").

**Naming convention:** on-screen text addresses Joshua as **"Joshx"** (his own handle) — e.g. "Good morning, Joshx." When Frank actually speaks (once voice/conversation exists), he should address Joshua as **"Josh"** instead — the natural spoken form, distinct from the stylized on-screen handle. See `PERSONALITY_SPEC.md` for the spoken-address side of this.

## Open questions

- How much of "premium and disciplined" is achievable long-term depends partly on native SwiftUI's ceiling vs. custom `Shape`/`Canvas` work — the blob shape is a first data point that custom drawing is viable here, not a final answer.
- Desktop/mobile visual consistency: same design language adapted per platform, or deliberately different (desktop = command center, mobile = quick access)? Still unresolved — no mobile work has started.
- How far the military-language principle extends — confirmed for tasks/home-screen framing; other copy (e.g. "Frank's Insights," "Today's Agenda," "Quick Actions") hasn't been explicitly reviewed against it yet.
- **The actual logo mark — explicitly parked.** Three attempts (a hand-built rounded stem+bowl path, a hand-built angular folded-ribbon path, and rendering the real source file `desktop/Sources/PCorpOS/Resources/P_logo.pdf` via PDFKit) all fell short on direct look. The shell currently uses a plain placeholder "P" glyph. The real source PDF is still bundled and ready — this needs a dedicated session, not more incremental guessing inside other UI work.

## Next step

Keep iterating against the running shell in `desktop/` as Joshua reviews it, rather than speculating further here — this document should stay a record of what's been decided by actually looking at the thing, not get ahead of it.
