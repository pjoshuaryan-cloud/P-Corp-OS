import SwiftUI

/// Root layout: sidebar, War Room center, right rail — a plain HStack for now
/// rather than NavigationSplitView, since nothing is actually navigable yet
/// (that's Phase 2 of the UI build-out: interactive chrome, still no intelligence).
struct ContentView: View {
    var body: some View {
        HStack(spacing: 0) {
            Sidebar()
            Divider()
            WarRoomView()
            Divider()
            RightRail()
        }
        .frame(minWidth: 1100, minHeight: 700)
    }
}

// No #Preview here: the Xcode Canvas preview macro needs the PreviewsMacros
// plugin that ships with full Xcode, which isn't installed on this machine
// (command-line tools only). Use `swift run` to see the actual window instead.
