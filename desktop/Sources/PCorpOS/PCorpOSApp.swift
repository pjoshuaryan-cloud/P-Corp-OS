import AppKit
import SwiftUI

@main
struct PCorpOSApp: App {
    // Same UserDefaults key as SettingsView's toggle — @AppStorage keeps
    // both in sync automatically, no separate observable object needed.
    @AppStorage(AppStorageKeys.darkModeEnabled) private var darkModeEnabled = false

    init() {
        // This is a plain SPM executable, not a proper .app bundle built by
        // Xcode — there's no Info.plist/asset-catalog icon pipeline to hook
        // into. Setting the Dock icon at runtime is the correct way to get a
        // real icon without that infrastructure: NSImage(contentsOf:) reads
        // the bundled PNG (white P mark on black rounded-square, derived
        // from the same p_logo_black.png used elsewhere), the same reliable
        // pixel-loading approach used for the other logo assets.
        if let url = Bundle.module.url(forResource: "app_icon", withExtension: "png"),
           let icon = NSImage(contentsOf: url) {
            NSApplication.shared.applicationIconImage = icon
        }
    }

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
