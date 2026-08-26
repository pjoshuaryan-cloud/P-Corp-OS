import PCorpKit
import SwiftUI

/// Slide-in drawer version of desktop's Sidebar.swift -- same header,
/// same nav rows (icon colors, selection highlight), same System Status
/// footer, ported as closely as the mobile drawer pattern allows. Desktop
/// is a permanent fixed column; here it's an overlay toggled by RootView's
/// hamburger button, so selecting a row also closes the drawer (there's no
/// room for both the drawer and content on a phone at once).
///
/// Grouped into CORE/DIVISIONS/LIFE/INTELLIGENCE/SYSTEM (2026-08-20,
/// Face-Lift item 05 iOS parity pass) -- same grouping desktop's own
/// Sidebar.swift uses, same reasoning: a pure display-layer wrapper,
/// `NavItem.items` itself untouched (RootView's Cmd... well, iOS has no
/// keyboard shortcuts to break, but keeping this consistent with
/// desktop's own "don't reorder the underlying list" discipline anyway).
/// Scoped deliberately to just this one piece of desktop's multi-round
/// Face-Lift work -- the system-status header, FrankOrb's per-state
/// motion, the War Room stats row, and The Brief are all real, separate,
/// still-undone parity items, not silently dropped.
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
    @Binding var isOpen: Bool
    @Environment(\.appTheme) private var theme
    @Namespace private var selectionNamespace
    @AppStorage(AppStorageKeys.showSystemStatus) private var showSystemStatus = true

    init(selectedID: Binding<UUID?>, isOpen: Binding<Bool>) {
        self._selectedID = selectedID
        self._isOpen = isOpen
        #if DEBUG
        let grouped = Set(navGroups.flatMap(\.itemTitles))
        let actual = Set(NavItem.items.map(\.title))
        assert(grouped == actual, "Sidebar navGroups is out of sync with NavItem.items: missing \(actual.subtracting(grouped)), extra \(grouped.subtracting(actual))")
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
            .padding(.top, 24) // drawer sits under the phone's own status bar/notch via safeAreaInset, no traffic lights to clear here
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
                            NavItem.items.first { $0.title == title }
                        }) { item in
                            NavRow(item: item, isSelected: item.id == selectedID, namespace: selectionNamespace)
                                .contentShape(Rectangle())
                                .onTapGesture {
                                    withAnimation(.easeOut(duration: AnimationTiming.standard)) {
                                        selectedID = item.id
                                        isOpen = false
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
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .background(.ultraThinMaterial)
        .background(theme.surface.opacity(0.3))
        .ignoresSafeArea(edges: .bottom)
    }
}

private struct NavRow: View {
    let item: NavItem
    let isSelected: Bool
    let namespace: Namespace.ID
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 12) {
            if item.title == "Alpha Mode Media" {
                Image("alpha_mode_logo")
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
                    // Joshx gets theme.accent, matching desktop's own
                    // Sidebar.swift special-case -- its one deliberate
                    // visual identity marker (2026-08-25 iOS parity).
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
            if isSelected {
                RoundedRectangle(cornerRadius: 12)
                    .fill(theme.textPrimary.opacity(0.06))
                    .matchedGeometryEffect(id: "navSelection", in: namespace)
            }
        }
    }
}
