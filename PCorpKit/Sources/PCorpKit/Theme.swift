import SwiftUI

/// Every surface/text/border color in the shell routes through this instead
/// of hardcoded Color.white/.black literals, so dark mode is an actual
/// designed palette rather than a color-scheme flag with nothing behind it.
/// Frank's orb and the P mark are deliberately NOT themed here — they're
/// fixed brand/identity elements, not chrome that needs to flip for contrast.
public struct AppTheme {
    public let background: Color
    public let surface: Color
    public let surfaceBorder: Color
    public let textPrimary: Color
    public let textSecondary: Color
    public let textTertiary: Color
    public let accentFill: Color
    public let accentText: Color
    public let divider: Color
    /// Card/surface drop shadow. Subtle black works against light
    /// backgrounds; against dark ones a black shadow is nearly invisible, so
    /// dark mode leans on a faint white shadow instead to read as elevation.
    public let cardShadow: Color

    public static let light = AppTheme(
        background: .white,
        surface: Color(white: 0.98),
        surfaceBorder: Color.black.opacity(0.06),
        textPrimary: .black,
        textSecondary: Color.black.opacity(0.55),
        textTertiary: Color.black.opacity(0.45),
        accentFill: .black,
        accentText: .white,
        divider: Color.black.opacity(0.08),
        cardShadow: Color.black.opacity(0.06)
    )

    public static let dark = AppTheme(
        background: Color(white: 0.07),
        // Bumped from a flat Color(white: 0.12) (2026-08-13) — too close to
        // background's 0.07 to read as a distinct elevated panel once the
        // .regularMaterial/.ultraThinMaterial blur is layered on top; cards
        // and the input bar read as plain dark grey slabs instead of
        // elevated surfaces. A touch of warmth (not pure neutral grey)
        // reads as richer than just raising the white value alone.
        surface: Color(red: 0.165, green: 0.155, blue: 0.175),
        surfaceBorder: Color.white.opacity(0.09),
        textPrimary: .white,
        textSecondary: Color.white.opacity(0.6),
        textTertiary: Color.white.opacity(0.45),
        accentFill: .white,
        accentText: .black,
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
