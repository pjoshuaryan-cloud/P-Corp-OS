import SwiftUI
import PCorpKit

/// One named group in the sidebar's nav list -- pure display grouping,
/// resolved back against PlaceholderData.navItems by title. Deliberately
/// NOT a change to NavItem/PlaceholderData.navItems itself: ContentView's
/// Cmd+1-9 shortcuts index into that array by position and its switch
/// routes by title, so the underlying array stays exactly as it was,
/// same order, same 11 elements -- only how it's visually chunked here
/// changes.
private struct NavGroup {
    let label: String
    let itemTitles: [String]
}

private let navGroups: [NavGroup] = [
    NavGroup(label: "CORE", itemTitles: ["War Room", "Frank"]),
    NavGroup(label: "DIVISIONS", itemTitles: ["Alpha Mode Media", "Joshx", "Trading Division", "Finance"]),
    NavGroup(label: "LIFE", itemTitles: ["Personal", "Calendar"]),
    NavGroup(label: "INTELLIGENCE", itemTitles: ["Knowledge", "Agents", "Automations", "Triggers"]),
    NavGroup(label: "SYSTEM", itemTitles: ["Settings"]),
]

struct Sidebar: View {
    @Binding var selectedID: UUID?
    @Environment(\.appTheme) private var theme
    @Namespace private var selectionNamespace
    // Real (2026-08-10) -- same key Settings' "Show System Status" toggle
    // writes to, so flipping it there takes effect here without any
    // shared state object, same @AppStorage pattern as dark mode.
    @AppStorage(AppStorageKeys.showSystemStatus) private var showSystemStatus = true

    init(selectedID: Binding<UUID?>) {
        self._selectedID = selectedID
        #if DEBUG
        let grouped = Set(navGroups.flatMap(\.itemTitles))
        let actual = Set(PlaceholderData.navItems.map(\.title))
        assert(grouped == actual, "Sidebar navGroups is out of sync with PlaceholderData.navItems: missing \(actual.subtracting(grouped)), extra \(grouped.subtracting(actual))")
        #endif
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 3) {
                Text("P CORP OS")
                    .font(PCorpFont.display(15))
                    .trackedLabel(1.8)
                    .foregroundStyle(theme.textPrimary)
                Text("EXECUTIVE INTELLIGENCE")
                    .font(PCorpFont.label(9.5))
                    .trackedLabel(1.8)
                    .foregroundStyle(theme.textSecondary)
            }
            .padding(.horizontal, 22)
            // Extra top clearance (not just visual breathing room): with
            // .hiddenTitleBar, macOS still reserves the top-left ~78x28pt for
            // the traffic-light window controls. 28pt of top padding put this
            // header's first line right where those buttons sit. Pushing
            // content down clear of that zone entirely avoids the collision
            // without needing to fuss over horizontal position too.
            .padding(.top, 40)
            .padding(.bottom, 28)

            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(navGroups.enumerated()), id: \.offset) { index, group in
                        Text(group.label)
                            .font(PCorpFont.label(9.5))
                            .trackedLabel(1.6)
                            .foregroundStyle(theme.textTertiary)
                            .padding(.horizontal, Spacing.sm)
                            .padding(.top, index == 0 ? 0 : Spacing.lg)
                            .padding(.bottom, Spacing.xs)

                        ForEach(group.itemTitles.compactMap { title in
                            PlaceholderData.navItems.first { $0.title == title }
                        }) { item in
                            NavRow(item: item, isSelected: item.id == selectedID, namespace: selectionNamespace)
                                .onTapGesture {
                                    withAnimation(.easeOut(duration: AnimationTiming.standard)) {
                                        selectedID = item.id
                                    }
                                }
                        }
                    }
                }
                .padding(.horizontal, 14)
            }

            Spacer(minLength: 24)

            if showSystemStatus {
                Divider()
                VStack(alignment: .leading, spacing: 6) {
                    Text("SYSTEM STATUS")
                        .font(PCorpFont.label(9.5))
                        .trackedLabel(1.8)
                        .foregroundStyle(theme.textSecondary)
                    HStack(spacing: 7) {
                        Circle().fill(Color.green).frame(width: 7, height: 7)
                        Text("All Systems Operational")
                            .font(PCorpFont.body(12.5))
                            .foregroundStyle(theme.textPrimary)
                    }
                }
                .padding(.horizontal, 22)
                .padding(.vertical, 24)
            }
        }
        // Explicit maxWidth added (2026-08-20): without one, this had no
        // hard cap, and restructuring ContentView's HStack to add the new
        // SystemStatusHeader (nesting the center content in a VStack
        // rather than a flat 3-child HStack) changed how SwiftUI
        // distributed extra window space -- the sidebar started growing
        // with the window instead of staying a fixed narrow column.
        .frame(minWidth: 220, idealWidth: 240, maxWidth: 260)
        .background(.ultraThinMaterial)
        .background(theme.surface.opacity(0.3)) // faint theme tint under the glass so it doesn't go fully neutral
    }
}

private struct NavRow: View {
    let item: NavItem
    let isSelected: Bool
    let namespace: Namespace.ID
    @Environment(\.appTheme) private var theme
    @State private var isHovering = false

    /// Alpha Mode Media's real brand mark, bundled from its actual brand
    /// assets (`Resources/alpha_mode_logo.png`) rather than a generic system
    /// icon. `.template` rendering mode treats it as an alpha mask, so it
    /// tints the same way the SF Symbol icons do (theme-colored, not a fixed
    /// color) — including flipping black/white correctly between light and
    /// dark mode along with everything else.
    private static let alphaModeLogo: Image? = {
        guard let url = AppResources.url(forResource: "alpha_mode_logo", withExtension: "png"),
              let nsImage = NSImage(contentsOf: url)
        else { return nil }
        return Image(nsImage: nsImage)
    }()

    var body: some View {
        HStack(spacing: 12) {
            if item.title == "Alpha Mode Media", let logo = Self.alphaModeLogo {
                logo
                    .resizable()
                    .renderingMode(.template)
                    .scaledToFit()
                    .frame(width: 15, height: 15)
                    .frame(width: 20)
                    .foregroundStyle(IconColors.alphaModeBrandBlue.opacity(isSelected ? 1.0 : 0.55))
            } else {
                Image(systemName: item.systemImage)
                    .font(.system(size: 15))
                    .frame(width: 20)
                    // Joshx (2026-08-21) gets theme.accent, not a fixed
                    // IconColors entry -- the one deliberate visual
                    // identity marker distinguishing it from Alpha Mode
                    // Media without building the full bespoke "cinematic"
                    // redesign the original brief asked for (deferred,
                    // confirmed with Joshua).
                    .foregroundStyle(
                        (item.title == "Joshx" ? theme.accent : IconColors.forNavItem(item.title)) ?? theme.textPrimary
                    )
                    .opacity(isSelected ? 1.0 : 0.55)
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(item.title)
                    .font(PCorpFont.body(13, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(item.subtitle)
                    .font(PCorpFont.body(11))
                    .foregroundStyle(theme.textTertiary)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 11)
        .background {
            // Only the selected row carries this ID at any given moment, so
            // matchedGeometryEffect animates it sliding from the old row's
            // position to the new one instead of just appearing/disappearing.
            if isSelected {
                RoundedRectangle(cornerRadius: 12)
                    .fill(theme.textPrimary.opacity(0.06))
                    .matchedGeometryEffect(id: "navSelection", in: namespace)
            } else if isHovering {
                RoundedRectangle(cornerRadius: 12)
                    .fill(theme.textPrimary.opacity(0.035))
            }
        }
        .contentShape(Rectangle())
        .onHover { hovering in
            withAnimation(.easeOut(duration: 0.12)) { isHovering = hovering }
        }
    }
}
