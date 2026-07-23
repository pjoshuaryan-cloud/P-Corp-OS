import SwiftUI

/// Every surface/text/border color in the shell routes through this instead
/// of hardcoded Color.white/.black literals, so dark mode is an actual
/// designed palette rather than a color-scheme flag with nothing behind it.
/// Frank's orb and the P mark are deliberately NOT themed here — they're
/// fixed brand/identity elements, not chrome that needs to flip for contrast.
struct AppTheme {
    let background: Color
    let surface: Color
    let surfaceBorder: Color
    let textPrimary: Color
    let textSecondary: Color
    let textTertiary: Color
    let accentFill: Color
    let accentText: Color
    let divider: Color
    /// Card/surface drop shadow. Subtle black works against light
    /// backgrounds; against dark ones a black shadow is nearly invisible, so
    /// dark mode leans on a faint white shadow instead to read as elevation.
    let cardShadow: Color

    static let light = AppTheme(
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

    static let dark = AppTheme(
        background: Color(white: 0.07),
        surface: Color(white: 0.12),
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
    var appTheme: AppTheme {
        get { self[AppThemeKey.self] }
        set { self[AppThemeKey.self] = newValue }
    }
}

/// Shared key so the toggle in Settings and the app's own scene stay in sync
/// automatically via @AppStorage, without a separate observable object.
enum AppStorageKeys {
    static let darkModeEnabled = "darkModeEnabled"
}
