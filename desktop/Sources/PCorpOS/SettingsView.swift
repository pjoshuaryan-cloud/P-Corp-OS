import SwiftUI
import PCorpKit

/// The first section beyond War Room with real, interactive content instead
/// of a placeholder — toggles actually flip and hold state. Two are real,
/// persisted via @AppStorage: dark mode (drives AppTheme app-wide) and
/// Show System Status (2026-08-10, drives Sidebar's status block). The
/// rest (Proactive Insights, Sound Effects) are still no-ops. Still
/// Phase 2 (buttons work, navigation works, still no intelligence), not
/// Phase 3+.
struct SettingsView: View {
    @State private var proactiveInsights = true
    @State private var soundEffects = false

    // Real now (2026-08-10) -- same @AppStorage pattern as darkModeEnabled
    // below, so Sidebar.swift can read the same key directly rather than
    // this view owning state Sidebar has no access to.
    @AppStorage(AppStorageKeys.showSystemStatus) private var showSystemStatus = true

    // Real now (SMAppService packaging, stage 3) — was a stubbed @State that
    // did nothing. Reads actual registration status on appear rather than a
    // separately persisted preference, since SMAppService.status is the real
    // source of truth (e.g. the user could disable it from System Settings'
    // own Login Items pane directly, outside this app entirely).
    @State private var backendAutoStart = false
    @State private var backendStatusNote: String?

    // Same key as PCorpOSApp's @AppStorage — this is the actual toggle,
    // not a placeholder; flipping it really switches the app's theme.
    @AppStorage(AppStorageKeys.darkModeEnabled) private var darkModeEnabled = false

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
                        title: "Launch at Login",
                        detail: backendStatusNote ?? "Start Frank's backend automatically in the background, even before you open the app.",
                        isOn: backendAutoStartBinding
                    )
                    settingsSeparator
                    SettingsToggleRow(
                        title: "Show System Status",
                        detail: "Display the status indicator in the sidebar.",
                        isOn: $showSystemStatus
                    )
                }

                Spacer(minLength: 0)
            }
            .padding(40)
            .frame(maxWidth: 560, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(theme.background)
        .onAppear { refreshBackendStatus() }
    }

    private var backendAutoStartBinding: Binding<Bool> {
        Binding(
            get: { backendAutoStart },
            set: { newValue in
                do {
                    if newValue {
                        try BackendService.register()
                    } else {
                        try BackendService.unregister()
                    }
                } catch {
                    backendStatusNote = "Couldn't change this: \(error.localizedDescription)"
                }
                refreshBackendStatus()
            }
        )
    }

    private func refreshBackendStatus() {
        switch BackendService.status {
        case .enabled:
            backendAutoStart = true
            backendStatusNote = nil
        case .requiresApproval:
            backendAutoStart = true
            backendStatusNote = "Needs approval in System Settings → General → Login Items to actually start."
        case .notFound:
            backendAutoStart = false
            backendStatusNote = "Not available in this build — the Login Items registration wasn't found in the app bundle."
        case .notRegistered:
            backendAutoStart = false
            backendStatusNote = nil
        @unknown default:
            backendAutoStart = false
            backendStatusNote = nil
        }
    }

    /// A hairline separator between rows in a section — deliberately not a
    /// system Divider(), which reads too heavy against this design (harsh
    /// divider lines were flagged and removed elsewhere in the shell).
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
