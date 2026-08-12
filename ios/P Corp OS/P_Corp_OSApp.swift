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
        // read back from UserDefaults here, not Keychain -- a genuine
        // scope cut for this first pass, flagged so it isn't forgotten,
        // not an oversight.
        BackendHost.host = "100.93.170.24"
        AuthToken.provider = {
            UserDefaults.standard.string(forKey: "backendAuthToken")
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
