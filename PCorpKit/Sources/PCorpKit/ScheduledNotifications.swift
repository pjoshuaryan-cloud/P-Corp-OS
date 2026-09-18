import Foundation
import UserNotifications

/// Real future-dated device notifications (e.g. "wake me up at 6am") --
/// distinct from SystemNotification.swift's immediate, in-session pushes
/// (used for things like a save_memory confirmation). Talks to
/// UNUserNotificationCenter directly on both platforms rather than
/// through a pluggable per-platform poster: unlike immediate pushes,
/// which historically needed osascript on desktop because a raw `swift
/// build` executable has no bundle identity and UNUserNotificationCenter
/// hard-crashed on it ("bundleProxyForCurrentProcess is nil"),
/// UserNotifications is genuinely cross-platform and confirmed live
/// (2026-09-18) to work fine now that build_app.sh assembles a real,
/// signed .app bundle.
///
/// The property that actually makes this useful: once scheduled, this is
/// registered with the OS's own notification scheduler, so it fires even
/// if the app isn't open or connected to the backend at the target time --
/// unlike the websocket-relayed `[notify]` sentinel, which only fires
/// while a live connection happens to be open. Real Apple platform
/// restriction, not a P Corp scoping choice: no third-party app can
/// create an actual system Alarm (Clock app) on either iOS or macOS, so
/// this is the closest working substitute -- a real banner + sound, but
/// one that Silent Mode/a blocking Focus can still suppress the way a
/// true Alarm wouldn't be.
public enum ScheduledNotifications {
    /// Call once at app launch on both platforms. Safe to call every
    /// launch -- UNUserNotificationCenter itself is idempotent about
    /// repeated authorization requests once the user has answered once.
    public static func requestAuthorizationIfNeeded() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    /// `fireAt` is a naive local wall-clock date-time string from the
    /// backend (e.g. "2026-09-19T06:00:00"), computed there against the
    /// real `datetime.now()` in the backend Mac's own local timezone --
    /// which matches Joshua's own local time in the single-user,
    /// single-timezone case this app is built for. Silently does nothing
    /// if the string fails to parse or the time has already passed --
    /// the backend itself already validates this before ever sending the
    /// sentinel, so either case here means the message was corrupted in
    /// transit, not a normal user-facing error to surface.
    public static func schedule(title: String, body: String, fireAt: String) {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        formatter.timeZone = .current
        guard let date = formatter.date(from: fireAt) else { return }
        let interval = date.timeIntervalSinceNow
        guard interval > 0 else { return }

        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default

        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: interval, repeats: false)
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: trigger)
        UNUserNotificationCenter.current().add(request)
    }
}
