import SwiftUI

/// "Updated `<time>`" label (2026-09-18, interaction polish pass) --
/// extracted from two call sites that already independently hand-rolled
/// the identical `Text("Updated \(lastFetchedAt.formatted(...))")` line
/// (RightRail's InsightsCard, WarRoomView's SituationRoomBanner). `color`
/// is optional (defaults to the neutral `theme.textTertiary`) since the
/// two existing call sites use different tones -- a neutral card vs. an
/// all-red alert banner -- not because this needed new design work.
public struct FreshnessLabel: View {
    let lastFetchedAt: Date?
    let color: Color?
    let fontSize: CGFloat

    @Environment(\.appTheme) private var theme

    public init(lastFetchedAt: Date?, color: Color? = nil, fontSize: CGFloat = 9.5) {
        self.lastFetchedAt = lastFetchedAt
        self.color = color
        self.fontSize = fontSize
    }

    public var body: some View {
        if let lastFetchedAt {
            Text("Updated \(lastFetchedAt.formatted(date: .omitted, time: .standard))")
                .font(PCorpFont.body(fontSize))
                .foregroundStyle(color ?? theme.textTertiary)
        }
    }
}
