import SwiftUI

/// A small "what does this mean" affordance (2026-09-18, interaction
/// polish pass) -- a plain `info.circle` icon that reveals a short
/// explanation. One component, no per-platform branching needed inside
/// it: `.help(_:)` gives desktop a real hover tooltip (a documented
/// no-op on touch-only iOS, same reasoning `ActionButtonStyle`'s own
/// `.onHover` already relies on), and `.popover(isPresented:)` (already
/// this app's proven cross-platform pattern for every existing detail
/// view) gives BOTH platforms a tap-to-reveal path -- so iOS, which has
/// no hover concept at all, still gets full access to the same
/// information via tap, not a desktop-only feature.
///
/// Deliberately not applied blanket-wide -- a short, named list of
/// genuinely ambiguous stats/statuses, confirmed with Josh first, not
/// every metric in the app getting a tooltip whether it needs one or not.
public struct InfoTip: View {
    let text: String
    @Environment(\.appTheme) private var theme
    @State private var isShowingPopover = false

    public init(_ text: String) {
        self.text = text
    }

    public var body: some View {
        Button {
            isShowingPopover = true
        } label: {
            Image(systemName: "info.circle")
                .font(.system(size: 11))
                .foregroundStyle(theme.textTertiary)
        }
        .buttonStyle(.plain)
        .help(text)
        .popover(isPresented: $isShowingPopover) {
            Text(text)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textPrimary)
                .padding(Spacing.sm)
                .frame(maxWidth: 240, alignment: .leading)
        }
    }
}
