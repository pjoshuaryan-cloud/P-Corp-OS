import Foundation

/// How to actually post a system notification differs per platform --
/// desktop shells out to `osascript` (desktop/Sources/PCorpOS/
/// SystemNotification.swift, unmoved: real `Process`/shell execution
/// isn't available in an iOS sandbox at all); iOS will use
/// UNUserNotificationCenter instead, which ironically crashes on today's
/// desktop build specifically because it isn't a real bundled .app yet
/// (see the desktop file's own docstring) -- a real iOS app has proper
/// bundle identity from the start, so that blocker doesn't apply there.
/// Split out (2026-08-12) so BackendClient.swift (now shared) can post a
/// notification without depending on either platform's real mechanism.
public enum SystemNotification {
    public static var poster: ((String, String) -> Void)?

    public static func post(title: String, body: String) {
        poster?(title, body)
    }
}
