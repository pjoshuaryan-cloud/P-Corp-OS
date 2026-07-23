import SwiftUI

/// Shared type and button styling so the whole shell reads as one designed
/// system rather than per-view font tweaks. Rounded system-font design reads
/// noticeably less "default SwiftUI" than the plain SF Pro used in the first
/// pass, and generous tracking on labels matches the wide-letter-spacing look
/// Joshua pointed to in his reference mockups.
enum PCorpFont {
    static func display(_ size: CGFloat, weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight, design: .rounded)
    }

    static func body(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .rounded)
    }

    /// Small all-caps section labels ("MISSION STATUS", "TODAY'S AGENDA", …) —
    /// always paired with wide tracking via `.trackedLabel()`.
    static func label(_ size: CGFloat = 10.5) -> Font {
        .system(size: size, weight: .semibold, design: .rounded)
    }
}

extension View {
    /// Wide letter-spacing for all-caps labels, matching the reference look.
    func trackedLabel(_ amount: CGFloat = 1.4) -> some View {
        self.tracking(amount)
    }
}

/// A fully rounded (capsule) button — filled for primary actions, tinted for
/// secondary chips like the Quick Actions grid. Replaces the default
/// `.borderedProminent` style, which only rounds corners slightly on macOS.
struct PillButtonStyle: ButtonStyle {
    var filled: Bool = true
    @Environment(\.appTheme) private var theme

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(PCorpFont.body(12.5, weight: .semibold))
            .padding(.horizontal, 16)
            .padding(.vertical, 9)
            .background(
                Capsule().fill(filled ? theme.accentFill : theme.textPrimary.opacity(0.06))
            )
            .foregroundStyle(filled ? theme.accentText : theme.textPrimary)
            .opacity(configuration.isPressed ? 0.85 : 1)
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
    }
}

extension ButtonStyle where Self == PillButtonStyle {
    static var pillFilled: PillButtonStyle { PillButtonStyle(filled: true) }
    static var pillTinted: PillButtonStyle { PillButtonStyle(filled: false) }
}
