import SwiftUI

/// Every surface/text/border color in the shell routes through this instead
/// of hardcoded Color.white/.black literals, so dark mode is an actual
/// designed palette rather than a color-scheme flag with nothing behind it.
/// Frank's orb and the P mark are deliberately NOT themed here — they're
/// fixed brand/identity elements, not chrome that needs to flip for contrast.
///
/// Values updated 2026-08-20 for the "Futuristic UI Face-Lift" brief (Phase
/// 1: foundation + shell) -- warmer off-white light background, near-black
/// (not pure black) text, a two-tier dark surface system, and a new
/// `accent` color. `accentFill`/`accentText` deliberately keep their
/// original meaning (monochrome inverted fill for buttons/user chat
/// bubbles, on both desktop and iOS since this file is shared via
/// PCorpKit) rather than being repurposed for the new accent -- doing so
/// would have silently turned every chat bubble blue app-wide.
public struct AppTheme {
    public let background: Color
    public let surface: Color
    /// Second elevation tier, above `surface` -- most useful in dark mode
    /// (brief's #101114/#15161A two-tier system) where a single surface
    /// tone reads flat once several elevated things (a card on a card, a
    /// popover, the new system-status header) sit near each other.
    public let surfaceElevated: Color
    public let surfaceBorder: Color
    public let textPrimary: Color
    public let textSecondary: Color
    public let textTertiary: Color
    public let accentFill: Color
    public let accentText: Color
    /// Genuinely new (2026-08-20): a controlled brand/intelligence-signal
    /// color, used sparingly for active/thinking system state (the new
    /// system-status header's "FRANK THINKING" dot, sidebar group
    /// accents) -- not a general-purpose UI color, and not the same thing
    /// as accentFill/accentText above.
    public let accent: Color
    public let divider: Color
    /// Card/surface drop shadow. Subtle black works against light
    /// backgrounds; against dark ones a black shadow is nearly invisible, so
    /// dark mode leans on a faint white shadow instead to read as elevation.
    public let cardShadow: Color

    public static let light = AppTheme(
        background: Color(red: 0.961, green: 0.961, blue: 0.953),   // #F5F5F3
        surface: Color(red: 0.980, green: 0.980, blue: 0.976),      // #FAFAF9
        surfaceElevated: .white,
        // Bumped 0.06 -> 0.07: the slightly warmer/darker background needs
        // a touch more edge contrast to stay legible than pure white did.
        surfaceBorder: Color.black.opacity(0.07),
        textPrimary: Color(white: 0.031),                           // #080808, near- not pure-black
        textSecondary: Color(red: 0.435, green: 0.435, blue: 0.451),// #6F6F73
        textTertiary: Color.black.opacity(0.45),
        accentFill: .black,
        accentText: .white,
        accent: Color(red: 0.271, green: 0.322, blue: 0.898),       // #4552E5, controlled indigo-blue
        divider: Color.black.opacity(0.08),
        cardShadow: Color.black.opacity(0.06)
    )

    public static let dark = AppTheme(
        background: Color(red: 0.031, green: 0.035, blue: 0.043),  // #08090B
        // Bumped from a flat Color(white: 0.12) (2026-08-13) — too close to
        // background's 0.07 to read as a distinct elevated panel once the
        // .regularMaterial/.ultraThinMaterial blur is layered on top; cards
        // and the input bar read as plain dark grey slabs instead of
        // elevated surfaces. A touch of warmth (not pure neutral grey)
        // reads as richer than just raising the white value alone.
        surface: Color(red: 0.063, green: 0.067, blue: 0.078),     // #101114, tier 1
        surfaceElevated: Color(red: 0.082, green: 0.086, blue: 0.102), // #15161A, tier 2
        surfaceBorder: Color.white.opacity(0.10),
        textPrimary: .white,
        textSecondary: Color.white.opacity(0.6),
        textTertiary: Color.white.opacity(0.45),
        accentFill: .white,
        accentText: .black,
        accent: Color(red: 0.431, green: 0.498, blue: 1.0),        // #6E7FFF, brighter for dark-bg legibility
        divider: Color.white.opacity(0.1),
        cardShadow: Color.black.opacity(0.4)
    )
}

private struct AppThemeKey: EnvironmentKey {
    static let defaultValue: AppTheme = .light
}

extension EnvironmentValues {
    public var appTheme: AppTheme {
        get { self[AppThemeKey.self] }
        set { self[AppThemeKey.self] = newValue }
    }
}

/// Shared key so the toggle in Settings and the app's own scene stay in sync
/// automatically via @AppStorage, without a separate observable object.
public enum AppStorageKeys {
    public static let darkModeEnabled = "darkModeEnabled"
    public static let showSystemStatus = "showSystemStatus"
}
