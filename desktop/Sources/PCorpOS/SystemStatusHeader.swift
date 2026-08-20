import PCorpKit
import SwiftUI

/// A persistent, always-visible system-state strip (2026-08-20, Face-Lift
/// brief section 06) — lives at ContentView's root, above the switched
/// center content and RightRail, visible across all 11 sidebar sections,
/// not just War Room. RightRail is already a persistent sibling of the
/// switched content today, so this follows that same existing pattern
/// rather than introducing a new one.
///
/// Every state shown here is real, already-published app state -- nothing
/// is computed or invented for this view. Five states, in priority order:
/// offline (backend unreachable) beats thinking, which beats a real
/// situation-room alert count, which beats the honest default. Showing
/// "SYSTEM NOMINAL" while actually disconnected would itself be a
/// fabrication, so an honest offline state was added beyond the brief's
/// own 4 named examples.
struct SystemStatusHeader: View {
    @ObservedObject var backend: BackendClient
    @ObservedObject var situationRoom: SituationRoomClient
    @Environment(\.appTheme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var statusText: String {
        if !backend.isConnected {
            return "FRANK OFFLINE"
        }
        if backend.isStreaming {
            return "FRANK THINKING"
        }
        if !situationRoom.alerts.isEmpty {
            let count = situationRoom.alerts.count
            return "\(count) ACTION\(count == 1 ? "" : "S") REQUIRED"
        }
        return "SYSTEM NOMINAL"
    }

    private var dotColor: Color {
        if !backend.isConnected { return theme.textTertiary }
        if backend.isStreaming { return theme.accent }
        if !situationRoom.alerts.isEmpty { return .orange }
        return .green
    }

    var body: some View {
        HStack(spacing: 7) {
            Circle()
                .fill(dotColor)
                .frame(width: 6, height: 6)
                // Subtle pulse only for the one genuinely "active" state --
                // a static dot for offline/nominal/alert would be honest
                // but a pulsing one for those would overstate them.
                .scaleEffect(backend.isStreaming && !reduceMotion ? 1.3 : 1.0)
                .animation(
                    backend.isStreaming && !reduceMotion
                        ? .easeInOut(duration: 0.7).repeatForever(autoreverses: true)
                        : .easeOut(duration: AnimationTiming.instant),
                    value: backend.isStreaming
                )
            Text(statusText)
                .font(PCorpFont.mono(10.5))
                .tracking(0.6)
                .foregroundStyle(theme.textSecondary)
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.xs)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(theme.surfaceElevated.opacity(0.5))
        .overlay(Rectangle().fill(theme.divider).frame(height: 1), alignment: .bottom)
        .animation(.easeOut(duration: AnimationTiming.quick), value: statusText)
    }
}
