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

                Spacer(minLength: 0)
            }
            .padding(24)
            .frame(maxWidth: 560, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(theme.background)
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
