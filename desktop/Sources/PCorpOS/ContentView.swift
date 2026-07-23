import SwiftUI

/// Root layout: sidebar, center content, right rail — a plain HStack rather
/// than NavigationSplitView, since the layout is a fixed three-column design,
/// not a collapsible/adaptive one. Selection now lives here (not inside
/// Sidebar) so it can drive what the center pane shows — real navigation,
/// still no backend, no data, no wired-up actions beyond switching views.
struct ContentView: View {
    @State private var selectedID: UUID? = PlaceholderData.navItems.first?.id

    private var selectedItem: NavItem {
        PlaceholderData.navItems.first { $0.id == selectedID } ?? PlaceholderData.navItems[0]
    }

    var body: some View {
        HStack(spacing: 0) {
            Sidebar(selectedID: $selectedID)

            Group {
                switch selectedItem.title {
                case "War Room":
                    WarRoomView()
                case "Settings":
                    SettingsView()
                default:
                    SectionPlaceholderView(item: selectedItem)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            RightRail()
        }
        .frame(minWidth: 1100, minHeight: 700)
    }
}

/// What every non-War-Room nav item shows right now: an honest "not built
/// yet" placeholder, not invented content. Keeps the shell truthful about
/// what actually exists rather than faking depth that isn't there.
private struct SectionPlaceholderView: View {
    let item: NavItem

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: item.systemImage)
                .font(.system(size: 34, weight: .regular))
                .foregroundStyle(Color.black.opacity(0.25))
            Text(item.title)
                .font(PCorpFont.display(22))
            Text("Not built yet.")
                .font(PCorpFont.body(13))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.white)
    }
}

// No #Preview here: the Xcode Canvas preview macro needs the PreviewsMacros
// plugin that ships with full Xcode, which isn't installed on this machine
// (command-line tools only). Use `swift run` to see the actual window instead.
