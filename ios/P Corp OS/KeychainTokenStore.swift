import Foundation
import Security

/// Stores the backend auth token in the Keychain instead of UserDefaults
/// (2026-08-12) -- UserDefaults was a deliberate, flagged scope cut for
/// the first iOS pass; this closes it. Keychain items are encrypted at
/// rest by iOS itself, unlike UserDefaults' plain plist. iOS-only for
/// now: desktop doesn't need this at all (AuthToken.provider there reads
/// a local file on the same Mac as the backend), so this stays in the
/// app target rather than PCorpKit -- not shared functionality yet.
enum KeychainTokenStore {
    private static let service = "media.alphamode.pcorpos.mobile"
    private static let account = "backendAuthToken"

    private static var query: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    static func save(_ token: String) {
        // Delete-then-add rather than trying update-vs-add branching --
        // simplest way to handle both "first save" and "replacing an
        // existing token" identically, and Keychain deletes of a
        // nonexistent item are a harmless no-op.
        SecItemDelete(query as CFDictionary)
        var newItem = query
        newItem[kSecValueData as String] = Data(token.utf8)
        SecItemAdd(newItem as CFDictionary, nil)
    }

    static func load() -> String? {
        var attributes = query
        attributes[kSecReturnData as String] = true
        attributes[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        let status = SecItemCopyMatching(attributes as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func delete() {
        SecItemDelete(query as CFDictionary)
    }
}
