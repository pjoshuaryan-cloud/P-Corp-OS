import SwiftUI

/// Shared refresh-icon button (2026-09-11) -- every section's own header
/// had the identical bare `Button { Task { await client.fetch() } } label: {
/// Image(systemName: "arrow.clockwise") }` pattern, duplicated across 11
/// views, with no visual feedback at all once tapped: a real complaint
/// (Josh, live) -- tapping refresh looked exactly the same whether it was
/// working or not. Swaps to a small spinner for the duration of `action`
/// and disables itself against a double-tap mid-refresh; same `.icon`
/// button style everything else already uses, so this is a drop-in
/// replacement, not a new visual language.
public struct RefreshIconButton: View {
    let action: () async -> Void
    /// Optional override (2026-09-18, interaction polish pass) -- every
    /// existing call site keeps its exact original `.icon`-styled
    /// neutral appearance by leaving this `nil`. Added specifically for
    /// `SituationRoomBanner`'s own already-intentional all-red alert
    /// styling, which would otherwise silently regress to a generic
    /// black/white icon if it adopted this component unmodified --
    /// rather than duplicate this button's busy/disable logic a second
    /// time locally just to preserve one color.
    var tint: Color?
    @State private var isRefreshing = false

    public init(tint: Color? = nil, action: @escaping () async -> Void) {
        self.tint = tint
        self.action = action
    }

    public var body: some View {
        Button {
            guard !isRefreshing else { return }
            isRefreshing = true
            Task {
                await action()
                isRefreshing = false
            }
        } label: {
            if isRefreshing {
                ProgressView()
                    .controlSize(.small)
                    .frame(width: 15, height: 15)
            } else {
                Image(systemName: "arrow.clockwise")
            }
        }
        .buttonStyle(.icon)
        .disabled(isRefreshing)
        .modifier(OptionalTint(tint: tint))
    }
}

private struct OptionalTint: ViewModifier {
    let tint: Color?
    func body(content: Content) -> some View {
        if let tint {
            content.foregroundStyle(tint)
        } else {
            content
        }
    }
}
