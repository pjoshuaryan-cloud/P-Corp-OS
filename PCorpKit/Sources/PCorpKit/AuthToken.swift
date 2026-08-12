import Foundation

/// How to actually obtain the current token differs per platform -- desktop
/// reads a local file on the same Mac the backend runs on (impossible on
/// iOS, which has no access to that filesystem); iOS will resolve it from
/// wherever the user enters/stores it instead. PCorpKit only defines the
/// shared interface every *Client.swift file calls; each platform's app
/// shell sets `provider` once at startup (2026-08-12, split out when
/// AuthToken moved into this shared package for the iOS companion app).
public enum AuthToken {
    public static var provider: (() -> String?)?

    public static var current: String? {
        provider?()
    }
}
