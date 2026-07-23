import SwiftUI

/// The first section beyond War Room with real, interactive content instead
/// of a placeholder — toggles actually flip and hold state. Nothing here is
/// wired to a backend or persisted anywhere; this is Phase 2 (buttons work,
/// navigation works, still no intelligence), not Phase 3+.
struct SettingsView: View {
    @State private var proactiveInsights = true
    @State private var soundEffects = false
    @State private var launchAtLogin = true
    @State private var showSystemStatus = true

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("Settings")
                    .font(PCorpFont.display(28))
                    .padding(.top, 8)

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
                        detail: "Start P Corp OS automatically when you log in.",
                        isOn: $launchAtLogin
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
        .background(Color.white)
    }

    /// A hairline separator between rows in a section — deliberately not a
    /// system Divider(), which reads too heavy against this design (harsh
    /// divider lines were flagged and removed elsewhere in the shell).
    private var settingsSeparator: some View {
        Rectangle()
            .fill(Color.black.opacity(0.06))
            .frame(height: 1)
            .padding(.leading, 16)
    }
}

private struct SettingsSection<Content: View>: View {
    let title: String
    let content: Content
    init(title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(PCorpFont.label(9.5))
                .trackedLabel(1.6)
                .foregroundStyle(.secondary)

            VStack(spacing: 0) {
                content
            }
            .background(
                RoundedRectangle(cornerRadius: 16)
                    .fill(Color(white: 0.98))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .strokeBorder(Color.black.opacity(0.06))
            )
        }
    }
}

private struct SettingsToggleRow: View {
    let title: String
    let detail: String
    @Binding var isOn: Bool

    var body: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(PCorpFont.body(13, weight: .semibold))
                Text(detail)
                    .font(PCorpFont.body(11.5))
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 16)
            Toggle("", isOn: $isOn)
                .labelsHidden()
                .toggleStyle(.switch)
                .tint(.black)
        }
        .padding(16)
    }
}
