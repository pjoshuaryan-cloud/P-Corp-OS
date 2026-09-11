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
    @State private var isRefreshing = false

    public init(action: @escaping () async -> Void) {
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
    }
}
