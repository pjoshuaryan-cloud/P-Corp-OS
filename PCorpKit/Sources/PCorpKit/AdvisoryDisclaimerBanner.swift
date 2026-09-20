import SwiftUI

/// Persistent, non-dismissable banner shown above every Trade Intelligence
/// capability (2026-09-20) -- unlike the read-only Trading Division Agent,
/// this specialist is explicitly allowed to state bias, price levels, and
/// trade recommendations, so the UI carries a structural, always-visible
/// reminder of that, not just a system-prompt caveat. Mounted exactly
/// once at the top of TradeIntelligenceView's body, above the 4-way
/// section switcher -- not per-section -- so it's physically impossible
/// to reach any capability, including Chart Analysis, without it already
/// on screen.
///
/// Visually distinct from ToastCenter's transient banners (this never
/// auto-dismisses) and from WarRoomView's SituationRoomBanner (that's a
/// real alert tied to a condition that clears; this is a fixed, permanent
/// notice, same styling language -- theme.statusHot -- but different
/// lifetime and purpose).
public struct AdvisoryDisclaimerBanner: View {
    @Environment(\.appTheme) private var theme

    public init() {}

    public var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(theme.statusHot)
            VStack(alignment: .leading, spacing: 2) {
                Text("TRADE INTELLIGENCE AGENT — ADVISORY ONLY")
                    .font(PCorpFont.label(10))
                    .trackedLabel(1.1)
                    .foregroundStyle(theme.statusHot)
                Text(
                    "Bias, price levels, and recommendations below are this agent's analysis, not financial "
                    + "advice. It has no path to place, modify, or close any real order — acting on anything "
                    + "here is your own decision and your own action."
                )
                .font(PCorpFont.body(11.5))
                .foregroundStyle(theme.textSecondary)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(theme.statusHot.opacity(0.12))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(theme.statusHot.opacity(0.3)))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }
}
