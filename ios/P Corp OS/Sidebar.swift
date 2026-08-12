import PCorpKit
import SwiftUI

/// Slide-in drawer version of desktop's Sidebar.swift -- same header,
/// same nav rows (icon colors, selection highlight), same System Status
/// footer, ported as closely as the mobile drawer pattern allows. Desktop
/// is a permanent fixed column; here it's an overlay toggled by RootView's
/// hamburger button, so selecting a row also closes the drawer (there's no
/// room for both the drawer and content on a phone at once).
struct Sidebar: View {
    @Binding var selectedID: UUID?
    @Binding var isOpen: Bool
    @Environment(\.appTheme) private var theme
    @Namespace private var selectionNamespace
    @AppStorage(AppStorageKeys.showSystemStatus) private var showSystemStatus = true

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
                    ForEach(NavItem.items) { item in
                        NavRow(item: item, isSelected: item.id == selectedID, namespace: selectionNamespace)
                            .contentShape(Rectangle())
                            .onTapGesture {
                                withAnimation(.easeOut(duration: 0.22)) {
                                    selectedID = item.id
                                    isOpen = false
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
                    .foregroundStyle((IconColors.forNavItem(item.title) ?? theme.textPrimary).opacity(isSelected ? 1.0 : 0.55))
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
