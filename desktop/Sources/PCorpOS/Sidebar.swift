import SwiftUI
import PCorpKit

struct Sidebar: View {
    @Binding var selectedID: UUID?
    @Environment(\.appTheme) private var theme
    @Namespace private var selectionNamespace
    // Real (2026-08-10) -- same key Settings' "Show System Status" toggle
    // writes to, so flipping it there takes effect here without any
    // shared state object, same @AppStorage pattern as dark mode.
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
                    ForEach(PlaceholderData.navItems) { item in
                        NavRow(item: item, isSelected: item.id == selectedID, namespace: selectionNamespace)
                            .onTapGesture {
                                withAnimation(.easeOut(duration: 0.22)) {
                                    selectedID = item.id
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
        .frame(minWidth: 220, idealWidth: 240)
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
