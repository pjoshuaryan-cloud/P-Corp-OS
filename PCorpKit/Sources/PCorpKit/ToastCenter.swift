import SwiftUI

/// Minimal in-app transient banner system (2026-09-18, interaction
/// polish pass) -- explicitly distinct from two things that already
/// exist and look superficially similar: `SystemNotification` (a real
/// OS-level push notification, `UNUserNotificationCenter`/`osascript`,
/// not an in-app UI element at all) and `SituationRoomBanner` (a
/// persistent alert that stays until the underlying condition clears,
/// not a transient "this just happened" confirmation).
///
/// Single-slot by design, not a queue -- this app is single-user,
/// single-window-of-attention; a real second event while one toast is
/// showing simply replaces it rather than stacking, matching "don't
/// spam the user, only show meaningful events" over building real queue
/// machinery for a case that won't come up in practice.
public enum ToastStyle {
    case success, info, warning, error
}

public struct ToastMessage: Identifiable, Equatable {
    public let id = UUID()
    public let text: String
    public let style: ToastStyle
}

@MainActor
public final class ToastCenter: ObservableObject {
    @Published public private(set) var current: ToastMessage?
    private var dismissTask: Task<Void, Never>?

    public init() {}

    public func show(_ text: String, style: ToastStyle = .info) {
        dismissTask?.cancel()
        current = ToastMessage(text: text, style: style)
        dismissTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(2.5))
            guard !Task.isCancelled else { return }
            self?.current = nil
        }
    }

    public func dismiss() {
        dismissTask?.cancel()
        current = nil
    }
}

private struct ToastBanner: View {
    let toast: ToastMessage
    @Environment(\.appTheme) private var theme

    private var iconAndColor: (String, Color) {
        switch toast.style {
        case .success: ("checkmark.circle.fill", theme.statusGood)
        case .info: ("arrow.triangle.2.circlepath", theme.accent)
        case .warning: ("exclamationmark.triangle.fill", theme.statusHot)
        case .error: ("xmark.circle.fill", theme.statusRisk)
        }
    }

    var body: some View {
        let (icon, color) = iconAndColor
        HStack(spacing: 8) {
            Image(systemName: icon)
                .foregroundStyle(color)
            Text(toast.text)
                .font(PCorpFont.body(12.5, weight: .medium))
                .foregroundStyle(theme.textPrimary)
        }
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, 10)
        .cardSurface(radius: Radius.md)
        .shadow(color: theme.cardShadow, radius: 12, y: 4)
    }
}

private struct ToastHostModifier: ViewModifier {
    @StateObject private var center = ToastCenter()

    func body(content: Content) -> some View {
        content
            .environmentObject(center)
            .overlay(alignment: .bottom) {
                if let toast = center.current {
                    ToastBanner(toast: toast)
                        .padding(.bottom, Spacing.xl)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                        .onTapGesture { center.dismiss() }
                }
            }
            .animation(.easeOut(duration: AnimationTiming.standard), value: center.current)
    }
}

extension View {
    /// Mounts one `ToastCenter` and its presentation overlay -- call once
    /// at each platform's true root (desktop's `ContentView`, iOS's
    /// `RootView`), never per-screen. Any descendant reads
    /// `@EnvironmentObject private var toastCenter: ToastCenter` to call
    /// `.show(_:style:)`.
    public func toastHost() -> some View {
        modifier(ToastHostModifier())
    }
}
