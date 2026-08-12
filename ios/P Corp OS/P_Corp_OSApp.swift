import SwiftUI
import PCorpKit

@main
struct P_Corp_OSApp: App {
    init() {
        // iOS's half of the Tailscale/auth-token setup PCorpKit's
        // pluggable providers need (2026-08-12, first iOS proof screen).
        // Hardcoded to this Mac's known Tailscale IP for now -- a real
        // settings screen to change it is a follow-up, not built yet.
        // The token itself is entered once by hand (ContentView) and
        // read back from the Keychain here (KeychainTokenStore.swift,
        // 2026-08-12 -- replaced the first pass's UserDefaults storage,
        // a flagged scope cut, not an oversight).
        BackendHost.host = "100.93.170.24"
        AuthToken.provider = {
            KeychainTokenStore.load()
        }

        // One-time cleanup: the first pass stored the token in
        // UserDefaults (plaintext plist) before this migration. Leaving
        // that copy behind would defeat the point of moving to Keychain,
        // even though nothing reads it anymore.
        UserDefaults.standard.removeObject(forKey: "backendAuthToken")
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
