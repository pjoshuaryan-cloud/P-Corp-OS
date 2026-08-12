import SwiftUI
import PCorpKit

/// The real War Room screen (2026-08-12) -- replaces the first pass's
/// plain chat thread. Desktop's own docs call War Room "the primary
/// interface, not a stub" (WAR_ROOM.md), so this is the one screen
/// worth making properly real before any broader mobile navigation --
/// deferred, not forgotten (see ROADMAP.md).
///
/// Reuses PCorpKit's PCorpFont directly -- the typography was already
/// cross-platform, no redesign needed there. Colors deliberately use
/// iOS's own native semantic colors (systemBackground, .secondary,
/// accentColor) instead of porting AppTheme's manual light/dark toggle
/// -- desktop has its own in-app dark-mode switch because it predates
/// following the OS setting automatically; a first-class iOS app should
/// just respect the system appearance the normal iOS way, not carry
/// that same manual toggle over. Desktop's separate right-rail cards
/// (Mission Status, Insights, Situation Room) become stacked sections
/// above the chat here, since there's no room for a second column on a
/// phone. Today's Agenda is deliberately excluded -- desktop's version
/// reads the macOS Calendar app via AppleScript, which has no iOS
/// equivalent; a real mobile agenda would need iOS's own EventKit
/// against the iPhone's own calendar, a genuinely separate feature not
/// built yet.
struct WarRoomView: View {
    @StateObject private var backend = BackendClient()
    @StateObject private var focusClient = FocusClient()
    @StateObject private var insightsClient = InsightsClient()
    @StateObject private var situationRoomClient = SituationRoomClient()
    @State private var inputText = ""

    private var greeting: String {
        switch Calendar.current.component(.hour, from: .now) {
        case 0..<12: "Good morning"
        case 12..<17: "Good afternoon"
        default: "Good evening"
        }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if !situationRoomClient.alerts.isEmpty {
                    situationRoomBanner
                }
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        header
                        missionStatusCard
                        if !insightsClient.insights.isEmpty {
                            insightsCard
                        }
                        chatThread
                    }
                    .padding()
                }
                inputBar
            }
            .background(Color(.systemBackground))
            .navigationBarHidden(true)
            .task {
                backend.connect()
                await focusClient.fetch()
                await insightsClient.fetch()
                await situationRoomClient.fetch()
            }
        }
    }

    private var header: some View {
        Text("\(greeting), Joshx.")
            .font(PCorpFont.display(22))
    }

    private var missionStatusCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                sectionLabel("MISSION STATUS")
                Spacer()
                HStack(spacing: 4) {
                    Circle().fill(Color.green).frame(width: 6, height: 6)
                    Text("Active").font(PCorpFont.body(11, weight: .semibold))
                }
            }
            Text("Create Leverage.\nFreedom Tomorrow.")
                .font(PCorpFont.display(17))
                .fixedSize(horizontal: false, vertical: true)
            Text("Focus: \(focusClient.objective ?? "Nothing set yet")")
                .font(PCorpFont.body(12))
                .foregroundStyle(.secondary)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 16).fill(Color(.secondarySystemBackground)))
    }

    private var insightsCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionLabel("FRANK'S INSIGHTS")
            VStack(alignment: .leading, spacing: 8) {
                ForEach(insightsClient.insights) { insight in
                    HStack(spacing: 8) {
                        Image(systemName: insight.systemImage)
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(insight.title)
                                .font(PCorpFont.body(12.5, weight: .semibold))
                            Text(insight.detail)
                                .font(PCorpFont.body(11.5))
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 16).fill(Color(.secondarySystemBackground)))
    }

    private var situationRoomBanner: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red)
                Text("SITUATION ROOM").font(PCorpFont.label(9.5)).foregroundStyle(.red)
            }
            ForEach(situationRoomClient.alerts) { alert in
                Text("\(alert.title) — \(alert.detail)").font(PCorpFont.body(12))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(Color.red.opacity(0.12))
    }

    private var chatThread: some View {
        VStack(alignment: .leading, spacing: 12) {
            if !backend.messages.isEmpty {
                sectionLabel("FRANK")
            }
            ForEach(backend.messages) { message in
                HStack {
                    if message.role == "user" { Spacer(minLength: 40) }
                    Text(message.content.isEmpty ? "…" : message.content)
                        .font(PCorpFont.body(14))
                        .padding(10)
                        .background(
                            RoundedRectangle(cornerRadius: 12)
                                .fill(message.role == "user" ? Color.accentColor.opacity(0.15) : Color(.secondarySystemBackground))
                        )
                    if message.role == "assistant" { Spacer(minLength: 40) }
                }
            }
        }
    }

    private var inputBar: some View {
        HStack(spacing: 10) {
            TextField("Talk to Frank...", text: $inputText)
                .textFieldStyle(.roundedBorder)
            Button {
                backend.send(inputText)
                inputText = ""
            } label: {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 28))
            }
            .disabled(inputText.isEmpty)
        }
        .padding()
        .background(.ultraThinMaterial)
    }

    private func sectionLabel(_ text: String) -> some View {
        Text(text)
            .font(PCorpFont.label(9.5))
            .tracking(1.4)
            .foregroundStyle(.secondary)
    }
}

#Preview {
    WarRoomView()
}
