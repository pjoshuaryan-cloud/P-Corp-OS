import SwiftUI

@main
struct PCorpOSApp: App {
    // Same UserDefaults key as SettingsView's toggle — @AppStorage keeps
    // both in sync automatically, no separate observable object needed.
    @AppStorage(AppStorageKeys.darkModeEnabled) private var darkModeEnabled = false

    var body: some Scene {
        WindowGroup("P Corp OS") {
            ContentView()
                .environment(\.appTheme, darkModeEnabled ? .dark : .light)
                // Forcing this explicitly (not .automatic) rather than
                // reading system dark mode directly — the toggle in Settings
                // is the single source of truth for which mode is active,
                // not the OS setting. Every surface color routes through
                // AppTheme (see Theme.swift); this just keeps SwiftUI's own
                // semantic colors (rare in this codebase, but present) and
                // system controls (like the Toggle switch) consistent with it.
                .preferredColorScheme(darkModeEnabled ? .dark : .light)
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentSize)
    }
}
