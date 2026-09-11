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
        //
        // localHost kept set for an easy manual revert (comment out the
        // line below to fall back to the Mac over Tailscale) -- but no
        // longer what iOS actually uses day to day.
        //
        // .production is real now (2026-09-11, iPhone independence): all
        // 13 domains are live on the shared Postgres the real Render
        // deployment and the Mac both read/write, so the phone no longer
        // needs the Mac on at all for its own real backend calls -- see
        // CHANGELOG.md. The one real credential change this needs: the
        // token in Keychain must be a per-device session (POST /auth/
        // register-device), not the Mac's own plaintext AUTH_TOKEN file
        // contents -- that value was never valid against Render's
        // separate AUTH_TOKEN in the first place. Four capabilities stay
        // structurally Mac-only regardless (AppleScript Calendar writes,
        // Trading Division, HF Markets, the digest's macOS notification)
        // -- an accepted, disclosed tradeoff, not a bug.
        BackendHost.localHost = "100.93.170.24"
        BackendHost.environment = .production
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
