import AppKit
import PCorpKit
import SwiftUI

@main
struct PCorpOSApp: App {
    // Same UserDefaults key as SettingsView's toggle — @AppStorage keeps
    // both in sync automatically, no separate observable object needed.
    @AppStorage(AppStorageKeys.darkModeEnabled) private var darkModeEnabled = false

    init() {
        // Desktop's half of AuthToken's pluggable provider (PCorpKit) --
        // reads fresh from the local backend data file on every access
        // (not cached), so a regenerated token is picked up without
        // restarting. Set once, here, before any *Client.swift network
        // call can happen.
        AuthToken.provider = {
            let url = ProjectPaths.repoRoot.appendingPathComponent("backend/data/auth_token")
            return try? String(contentsOf: url, encoding: .utf8)
                .trimmingCharacters(in: .whitespacesAndNewlines)
        }

        // Desktop's half of SystemNotification's pluggable poster
        // (PCorpKit) -- real macOS notification via `osascript`, not
        // `UserNotifications`: confirmed directly (2026-07-25) that
        // UNUserNotificationCenter hard-crashes on this app
        // ("bundleProxyForCurrentProcess is nil"), since it's still a raw
        // `swift build` executable, not a real .app bundle. `osascript`
        // doesn't need the calling process to have its own bundle
        // identity, so it works today; revisit once SMAppService
        // packaging gives this app a real bundle.
        SystemNotification.poster = { title, body in
            let script = "display notification \(Self.appleScriptString(body)) with title \(Self.appleScriptString(title))"
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
            process.arguments = ["-e", script]
            try? process.run()
        }

        // This is a plain SPM executable, not a proper .app bundle built by
        // Xcode — there's no Info.plist/asset-catalog icon pipeline to hook
        // into. Setting the Dock icon at runtime is the correct way to get a
        // real icon without that infrastructure.
        //
        // Uses AppIcon.icns (built via `iconutil` from a full 10-image
        // .iconset — 16/32/64/128/256/512/1024px, matching Apple's standard
        // size set) rather than the single flat app_icon.png: NSImage loads
        // every representation embedded in a .icns automatically and picks
        // the pixel-exact match for each context (Dock, Cmd-Tab, Finder),
        // instead of relying on live scaling of one image, which can look
        // soft at small sizes. Same source artwork either way (the white P
        // mark on a black rounded-square, derived from p_logo_black.png);
        // this is a quality upgrade to how it's delivered, not a redesign.
        // AppIcon.icns is also ready to drop straight into a real Xcode
        // asset catalog later, if this ever becomes a proper .app bundle.
        if let url = AppResources.url(forResource: "AppIcon", withExtension: "icns"),
           let icon = NSImage(contentsOf: url) {
            NSApplication.shared.applicationIconImage = icon
        }

        // Shadow Mode (2026-08-10) -- see ActivityTracker.swift's own
        // docstring for what this does and doesn't capture.
        ActivityTracker.shared.start()
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

    /// Escapes a string for embedding in an AppleScript string literal —
    /// backslash first, then double-quote, in that order (matters: escaping
    /// quotes first would double-escape the backslashes just added for them).
    private static func appleScriptString(_ text: String) -> String {
        let escaped = text
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        return "\"\(escaped)\""
    }
}
