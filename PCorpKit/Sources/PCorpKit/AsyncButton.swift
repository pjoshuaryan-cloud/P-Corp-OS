import SwiftUI

/// A button wrapping an `async` action with a real busy/disabled state
/// (2026-09-18, interaction polish pass) -- generalizes the exact
/// busy/self-disable/spinner-swap logic `RefreshIconButton` already
/// proves for icon-only refresh buttons, extended to text/label buttons
/// (Save, Convert, etc.) whose label needs to stay legible while
/// disabled rather than being replaced by a bare icon.
///
/// Real gap this closes: several Save/action buttons across the app
/// (PersonalView's goal/habit/person forms) were only ever
/// `.disabled(!canSave)` -- never disabled once tapped, so a fast
/// double-click could genuinely fire the same write twice before the
/// first one's response came back. `AsyncButton` guards re-entry itself
/// (`guard !isRunning`), so callers don't each need to invent their own
/// `@State isSaving` flag to get this right.
///
/// Deliberately does NOT touch `RefreshIconButton` -- that component
/// already works and has real call sites depending on its exact icon-
/// only shape; this is a separate, additive primitive for the
/// text-label case, not a replacement.
public struct AsyncButton<Label: View>: View {
    let role: ButtonRole?
    let action: () async -> Void
    let label: () -> Label

    @State private var isRunning = false

    public init(
        role: ButtonRole? = nil,
        action: @escaping () async -> Void,
        @ViewBuilder label: @escaping () -> Label
    ) {
        self.role = role
        self.action = action
        self.label = label
    }

    public var body: some View {
        Button(role: role) {
            guard !isRunning else { return }
            isRunning = true
            Task {
                await action()
                isRunning = false
            }
        } label: {
            if isRunning {
                ProgressView()
                    .controlSize(.small)
            } else {
                label()
            }
        }
        .disabled(isRunning)
    }
}
