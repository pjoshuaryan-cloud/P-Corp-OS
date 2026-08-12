import AppKit
import Foundation
import PCorpKit

/// Shadow Mode (2026-08-10) -- passive activity awareness, app name only.
/// Observes NSWorkspace's own frontmost-app-change notification, a public
/// API that needs no permission prompt (deliberately not AppleScript/
/// Accessibility, which would trigger a TCC automation dialog -- same
/// class of problem as the earlier mic crash). Event-driven, not polled:
/// only fires when the frontmost app actually changes, so the backend
/// ends up with a segmented history, not raw samples.
@MainActor
final class ActivityTracker {
    static let shared = ActivityTracker()
    private var lastAppName: String?
    private var started = false

    private init() {}

    func start() {
        guard !started else { return }
        started = true
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification,
            object: nil,
            queue: .main
        ) { [weak self] notification in
            guard let app = notification.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
                  app.isRealApp, let name = app.localizedName else { return }
            Task { @MainActor in
                self?.logChange(name)
            }
        }
        // Log whatever's frontmost at launch too -- otherwise it never
        // gets recorded until the user switches away from it.
        if let app = NSWorkspace.shared.frontmostApplication, app.isRealApp, let name = app.localizedName {
            logChange(name)
        }
    }

    private func logChange(_ name: String) {
        guard name != lastAppName else { return }
        lastAppName = name
        Task {
            await post(name)
        }
    }

    private struct ActivityLogPayload: Encodable {
        let appName: String
        enum CodingKeys: String, CodingKey {
            case appName = "app_name"
        }
    }

    private func post(_ name: String) async {
        var components = URLComponents(string: "http://127.0.0.1:8731/activity/log")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        var request = URLRequest(url: components.url!)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(ActivityLogPayload(appName: name))
        _ = try? await URLSession.shared.data(for: request)
    }
}

private extension NSRunningApplication {
    // Real bug found 2026-08-10: system helpers like UserNotificationCenter
    // (the notification-banner process) briefly become "frontmost" and got
    // logged as if the user switched to them. .regular is the same
    // activation policy macOS itself uses to decide what gets a Dock icon
    // -- filtering to it excludes that whole class of transient system UI
    // (Dock, SystemUIServer, notification banners, Spotlight, etc.) without
    // hardcoding a blocklist of specific process names.
    var isRealApp: Bool { activationPolicy == .regular }
}
