# UI Guidelines

**Status:** Active — a real visual system now exists, built and iterated against the actual desktop shell (`desktop/`), not designed in the abstract.

## Purpose

Define what P Corp OS should feel like to use, so design decisions later have a standard to check against.

## Decided (from FOUNDER_BRIEF.md)

Opening the app should feel like entering headquarters, not opening another application. The home screen concept is the **War Room** (see `WAR_ROOM.md`). The interface should communicate readiness, clarity, and focus — not clutter, not gimmicks. Target qualities: purposeful, minimal, professional, disciplined, premium.

## Decided from building the first shell (2026-07-23)

**Visual language:** white/near-white surfaces, black text and accents, no color beyond that, generous whitespace, no visible seams between layout regions (background-tone contrast instead of hard divider lines — Joshua explicitly flagged divider lines as looking wrong on first look).

**Glass/material finishes (added 2026-07-24).** Sidebar, right rail, its cards, and the War Room input bar all use native SwiftUI `Material` (`.ultraThinMaterial` for panels, `.regularMaterial` for cards — slightly more opaque so text over them stays legible) layered over a faint theme-colored tint, rather than flat solid fills. Chosen specifically because Materials are a native, well-supported system feature — not something hand-built or at risk of rendering wrong the way the custom logo/particle work was. They automatically follow whichever mode is active (light/dark), since that's driven by the same `.preferredColorScheme` the rest of the theme system uses, not the OS's own appearance setting.

**Dark mode: real, designed, and user-controlled (added 2026-07-24)** — not a system-appearance flag. `Theme.swift` defines a light and a dark `AppTheme` (background, surface, borders, three text tiers, accent fill/text) injected via a custom environment key; every view reads colors from `@Environment(\.appTheme)` instead of hardcoded `Color.white`/`.black`. Toggled from Settings ("Dark Mode" under Appearance), backed by `@AppStorage` — the toggle, not the OS's own appearance setting, is the single source of truth for which mode is active (`.preferredColorScheme` is set explicitly to `.light` or `.dark`, never `.automatic`). The P mark and Frank's presence are both themed (`theme.textPrimary`) rather than fixed black — a deliberate choice, not an oversight, since flat black would go invisible against a dark background.

**The P mark — resolved (2026-07-24).** Three hand-built vector-path attempts (rounded stem+bowl, angular folded-ribbon, and rendering the original `P_logo.pdf` via PDFKit) all fell short — the real mark is intricate enough (angled facets, a beveled bowl, diagonal notches cut into the stem) that guessing coordinates was never going to land. Resolved by processing Joshua's actual reference image directly instead of approximating it: `p_logo_black.png` was extracted from a gold/metallic textured render by thresholding luminance (the background was solid black, the letterform bright gold, giving a clean separation), recoloring to a flat black silhouette with anti-aliased edges, and cropping to content bounds. Rendered via `.template` mode + `theme.textPrimary`, same pattern as the Alpha Mode Media logo. A small amount of texture-grain survived along a few interior edges from the original artwork; noted as a known minor imperfection, not treated as broken.

**Frank's on-screen presence:** a cluster of individual particles, not a solid shape (changed 2026-07-24, was previously one continuous organic "blob" outline — direct feedback asked for "a blob of particles floating" instead). 260 small dots (bumped up from an initial 120, per direct feedback for "more particles"), positions generated from a deterministic seeded random sequence (same layout every launch, not true randomness) biased toward a denser core that thins toward the edge, each shimmering independently (opacity/size breathing, out of phase with its neighbors) via `TimelineView` + `Canvas` (see `FrankOrb` in `desktop/Sources/PCorpOS/WarRoomView.swift`). The whole cluster floats — a slow vertical bob with a contact shadow beneath that widens/lightens as it rises and tightens/darkens as it falls. Rendered in `theme.textPrimary` (not fixed black) specifically so it stays visible in dark mode. No face, no mascot features — presence comes from motion and texture only, consistent with FOUNDER_BRIEF.md's explicit direction that Frank's identity shouldn't come from a character on screen.

**Tracked requirement — audio-reactive movement, not yet buildable:** once Frank has an actual voice (Phase 4+ of the UI build-out plan), the particle cluster's shimmer/motion should be driven by real audio amplitude/frequency from that speech, not the current synthetic time-based sine wave. Can't be built now — there's no voice/audio system at all yet, so there's no signal to react to. Flagged directly in code (`FrankOrb` in `WarRoomView.swift`) so it isn't forgotten once voice exists.

**Copy tone: military-style language, kept easy to understand, despite the clean/minimal visual design.** Confirmed directly by Joshua — the clean look and the terminology are separate decisions, not in tension. Examples decided so far: tasks are called **"Missions"** ("+ Mission" button, "New Mission" quick action), the home screen is the **War Room** / **Mission Control**, current focus is **Mission Status**. Apply this consistently to new copy going forward — when adding a label, ask whether a military/command-center framing fits before defaulting to generic SaaS-dashboard language ("Tasks," "Dashboard," "Notifications").

**Naming convention:** on-screen text addresses Joshua as **"Joshx"** (his own handle) — e.g. "Good morning, Joshx." When Frank actually speaks (once voice/conversation exists), he should address Joshua as **"Josh"** instead — the natural spoken form, distinct from the stylized on-screen handle. See `PERSONALITY_SPEC.md` for the spoken-address side of this.

## Open questions

- How much of "premium and disciplined" is achievable long-term depends partly on native SwiftUI's ceiling vs. custom `Shape`/`Canvas` work — the blob shape is a first data point that custom drawing is viable here, not a final answer.
- Desktop/mobile visual consistency: same design language adapted per platform, or deliberately different (desktop = command center, mobile = quick access)? Still unresolved — no mobile work has started.
- How far the military-language principle extends — confirmed for tasks/home-screen framing; other copy (e.g. "Frank's Insights," "Today's Agenda," "Quick Actions") hasn't been explicitly reviewed against it yet.

## Next step

Keep iterating against the running shell in `desktop/` as Joshua reviews it, rather than speculating further here — this document should stay a record of what's been decided by actually looking at the thing, not get ahead of it.
