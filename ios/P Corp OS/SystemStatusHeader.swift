import PCorpKit
import SwiftUI

/// Direct port of desktop's own SystemStatusHeader.swift (2026-08-20,
/// Face-Lift iOS parity pass) -- identical logic, since everything it
/// reads (BackendClient.isConnected/isStreaming, SituationRoomClient.
/// alerts, the mono font/accent color/Spacing/AnimationTiming tokens) is
/// already shared via PCorpKit. Lives in RootView's own VStack, below
/// the hamburger/logo topBar and above the switched section content, so
/// it's visible across every section, not just War Room -- same
/// placement reasoning as desktop's own version sitting above ContentView's
/// switched content + RightRail.
///
/// Every state shown here is real, already-published app state -- nothing
/// is computed or invented for this view. Five states, in priority order:
/// offline (backend unreachable) beats thinking, which beats a real
/// situation-room alert count, which beats the honest default.
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
