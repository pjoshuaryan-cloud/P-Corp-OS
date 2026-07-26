import Foundation

/// Posts a real macOS notification via `osascript`, not `UserNotifications` —
/// confirmed directly (2026-07-25) that UNUserNotificationCenter hard-crashes
/// on this app ("bundleProxyForCurrentProcess is nil"), since it's still a
/// raw `swift build` executable, not a real .app bundle (the same root cause
/// as the earlier activation-policy/Dock-icon quirks). `osascript` doesn't
/// need the calling process to have its own bundle identity, so it works
/// today; revisit once SMAppService packaging gives this app a real bundle.
enum SystemNotification {
    static func post(title: String, body: String) {
        let script = "display notification \(appleScriptString(body)) with title \(appleScriptString(title))"
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script]
        try? process.run()
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
