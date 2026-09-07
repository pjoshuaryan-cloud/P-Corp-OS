import PCorpKit
import SwiftUI

/// Port of desktop's own SettingsView.swift (2026-08-13) — real, persisted
/// toggles where desktop has real ones, honest no-ops where desktop's are
/// still stubs. This is also what finally resolves a flagged deviation
/// from the earlier visual-matching pass: the approved scope back then
/// was "desktop's manual dark-mode toggle instead of following the system
/// setting," but there was no Settings screen yet to put one in, so
/// ContentView.swift fell back to following the phone's system appearance
/// instead. Now that this screen exists, ContentView.swift switched over
/// to the same `@AppStorage(AppStorageKeys.darkModeEnabled)` key desktop
/// uses — manual, not system-linked, matching the original ask exactly.
///
/// One row deliberately dropped, not ported: desktop's "Launch at Login"
/// controls `SMAppService` registration for the *backend* process, which
/// only ever runs on the Mac — there's no iOS equivalent of "launch the
/// backend at login" on a phone that doesn't run the backend at all.
/// Including a toggle for it here would just be decoration with nothing
/// real behind it.
struct SettingsView: View {
    @State private var proactiveInsights = true
    @State private var soundEffects = false

    @AppStorage(AppStorageKeys.showSystemStatus) private var showSystemStatus = true
    @AppStorage(AppStorageKeys.darkModeEnabled) private var darkModeEnabled = false

    @StateObject private var connectedAppsClient = ConnectedAppsClient()

    @Environment(\.appTheme) private var theme

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("Settings")
                    .font(PCorpFont.display(28))
                    .foregroundStyle(theme.textPrimary)
                    .padding(.top, 8)

                SettingsSection(title: "APPEARANCE") {
                    SettingsToggleRow(
                        title: "Dark Mode",
                        detail: "Switch P Corp OS to a dark theme.",
                        isOn: $darkModeEnabled
                    )
                }

                SettingsSection(title: "FRANK") {
                    SettingsToggleRow(
                        title: "Proactive Insights",
                        detail: "Let Frank surface things unprompted, not just when asked.",
                        isOn: $proactiveInsights
                    )
                    settingsSeparator
                    SettingsToggleRow(
                        title: "Sound Effects",
                        detail: "Play a sound when Frank responds.",
                        isOn: $soundEffects
                    )
                }

                SettingsSection(title: "GENERAL") {
                    SettingsToggleRow(
                        title: "Show System Status",
                        detail: "Display the status indicator in the sidebar.",
                        isOn: $showSystemStatus
                    )
                }

                // Gmail/Calendar/Supabase already work in the backend but
                // had zero UI showing it (2026-09-04) -- fetched on
                // appear rather than a timed poll like Insights/Situation
                // Room, since Supabase's own check is a live network
                // round-trip (see backend/app/connected_apps.py) that's
                // only worth paying when Josh actually looks at this
                // screen.
                SettingsSection(title: "CONNECTED APPS") {
                    if connectedAppsClient.apps.isEmpty {
                        Text(connectedAppsClient.isLoading ? "Checking…" : "Couldn't reach the backend.")
                            .font(PCorpFont.body(11.5))
                            .foregroundStyle(theme.textSecondary)
                            .padding(16)
                    } else {
                        ForEach(Array(connectedAppsClient.apps.enumerated()), id: \.element.id) { index, app in
                            if index > 0 { settingsSeparator }
                            ConnectedAppStatusRow(app: app)
                        }
                    }
                }

                Spacer(minLength: 0)
            }
            .padding(24)
            .frame(maxWidth: 560, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(theme.background)
        .onAppear {
            Task { await connectedAppsClient.fetch() }
        }
    }

    private var settingsSeparator: some View {
        Rectangle()
            .fill(theme.textPrimary.opacity(0.06))
            .frame(height: 1)
            .padding(.leading, 16)
    }
}

private struct SettingsSection<Content: View>: View {
    let title: String
    let content: Content
    @Environment(\.appTheme) private var theme

    init(title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(PCorpFont.label(9.5))
                .trackedLabel(1.6)
                .foregroundStyle(theme.textSecondary)

            VStack(spacing: 0) {
                content
            }
            .background(
                RoundedRectangle(cornerRadius: 16)
                    .fill(theme.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .strokeBorder(theme.surfaceBorder)
            )
        }
    }
}

private struct SettingsToggleRow: View {
    let title: String
    let detail: String
    @Binding var isOn: Bool
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(PCorpFont.body(13, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(detail)
                    .font(PCorpFont.body(11.5))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer(minLength: 16)
            Toggle("", isOn: $isOn)
                .labelsHidden()
                .toggleStyle(.switch)
                .tint(theme.textPrimary)
        }
        .padding(16)
    }
}

private struct ConnectedAppStatusRow: View {
    let app: ConnectedAppStatus
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 3) {
                Text(app.name)
                    .font(PCorpFont.body(13, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(detailText)
                    .font(PCorpFont.body(11.5))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer(minLength: 16)
            // Not statusRisk -- Theme.swift reserves that for a real
            // escalated alert (SituationRoomBanner). "Not connected yet"
            // is a neutral state here, same reasoning AgentsView.swift
            // already uses for an inactive (not failed) agent's dot.
            Circle()
                .fill(app.connected ? theme.statusGood : theme.textSecondary)
                .frame(width: 7, height: 7)
                .padding(.top, 5)
        }
        .padding(16)
    }

    private var detailText: String {
        guard app.connected else { return "Not connected." }
        guard let lastSyncedAt = app.lastSyncedAt else {
            return "Connected — no sync recorded yet."
        }
        return "Last synced \(lastSyncedAt)"
    }
}
