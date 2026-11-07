import CryptoKit
import Foundation
import LocalAuthentication
import Security

/// Where the journal's key lives on each device: the Keychain, and nowhere else but his written-down recovery code. On iPhone the item itself
/// demands Face ID or the passcode before it can be read, and never leaves the phone or its backups. The Mac app has no Keychain entitlement
/// for that, so there the key sits in his login Keychain and the app asks for Touch ID or his password before it reads it.
public enum JournalKeychain {
    private static let service = "media.alphamode.pcorpos.journal"
    private static let account = "journalKey"

    /// The Simulator has no Face ID or passcode to ask for. Only a Simulator build, started with this set, skips the prompt; it can't exist on a phone.
    static var testUnlock: Bool {
        #if targetEnvironment(simulator)
        return ProcessInfo.processInfo.environment["PCORP_JOURNAL_TEST_UNLOCK"] == "1"
        #else
        return false
        #endif
    }

    private static var base: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
    }

    public enum Failure: Error, Equatable {
        case couldNotSave(OSStatus)
        case missing
    }

    /// Whether this device has the key, without asking for Face ID.
    public static func hasKey() -> Bool {
        var query = base
        let quiet = LAContext()
        quiet.interactionNotAllowed = true
        query[kSecUseAuthenticationContext as String] = quiet
        query[kSecReturnAttributes as String] = true
        let status = SecItemCopyMatching(query as CFDictionary, nil)
        return status == errSecSuccess || status == errSecInteractionNotAllowed || status == errSecAuthFailed
    }

    public static func store(_ key: SymmetricKey) throws {
        SecItemDelete(base as CFDictionary)
        var item = base
        item[kSecValueData as String] = JournalCrypto.keyData(key)
        #if os(iOS)
        if !testUnlock, let access = SecAccessControlCreateWithFlags(nil, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, .userPresence, nil) {
            item[kSecAttrAccessControl as String] = access
        } else {
            item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        }
        #endif
        let status = SecItemAdd(item as CFDictionary, nil)
        guard status == errSecSuccess else { throw Failure.couldNotSave(status) }
    }

    /// The key, using a Face ID or Touch ID check that's already been passed, so he's only asked once.
    public static func load(using context: LAContext?) throws -> SymmetricKey {
        var query = base
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        if let context { query[kSecUseAuthenticationContext as String] = context }
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess, let data = result as? Data, data.count == 32 else { throw Failure.missing }
        return SymmetricKey(data: data)
    }

    public static func remove() {
        SecItemDelete(base as CFDictionary)
    }
}

public enum JournalAuth {
    /// Face ID, Touch ID, or the device's passcode or password if those aren't set up. Nil if he cancels or it fails.
    public static func check(reason: String) async -> LAContext? {
        if JournalKeychain.testUnlock { return nil }
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else { return nil }
        do {
            return try await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason) ? context : nil
        } catch {
            return nil
        }
    }

    /// Whether the check passed. In the Simulator's test mode there is none to pass.
    public static func passed(_ context: LAContext?) -> Bool {
        context != nil || JournalKeychain.testUnlock
    }
}

/// The journal's routes on the backend. They only ever carry sealed bytes. An ephemeral session, so nothing is cached on disk along the way.
public struct JournalHTTP: JournalTransport {
    public enum Failure: Error, Equatable {
        case server(Int, String)
    }

    private static let session = URLSession(configuration: .ephemeral)

    public init() {}

    private struct StateReply: Decodable {
        let set_up: Bool
        let key_check: String?
    }

    private struct VersionReply: Decodable {
        let version: Int
    }

    private struct IndexReply: Decodable {
        let items: [JournalIndexItem]
    }

    private struct DetailReply: Decodable {
        let detail: String
    }

    private func send(_ request: URLRequest) async throws -> (Data, Int) {
        let (data, response) = try await Self.session.data(for: request)
        return (data, (response as? HTTPURLResponse)?.statusCode ?? 0)
    }

    private func failure(_ data: Data, _ status: Int) -> Failure {
        .server(status, (try? JSONDecoder().decode(DetailReply.self, from: data))?.detail ?? "The server said no (\(status)).")
    }

    public func state() async throws -> String? {
        let (data, status) = try await send(URLRequest(url: BackendHost.url(path: "/journal/state")))
        guard status == 200 else { throw failure(data, status) }
        return try JSONDecoder().decode(StateReply.self, from: data).key_check
    }

    public func setUp(keyCheck: String) async throws -> JournalSetupResult {
        var request = URLRequest(url: BackendHost.url(path: "/journal/setup"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(["key_check": keyCheck])
        let (data, status) = try await send(request)
        if status == 409 { return .otherKey }
        guard status == 200 else { throw failure(data, status) }
        return .ok
    }

    public func index() async throws -> [JournalIndexItem] {
        let (data, status) = try await send(URLRequest(url: BackendHost.url(path: "/journal/index")))
        guard status == 200 else { throw failure(data, status) }
        return try JSONDecoder().decode(IndexReply.self, from: data).items
    }

    public func get(_ id: String) async throws -> Data? {
        let (data, status) = try await send(URLRequest(url: BackendHost.url(path: "/journal/items/\(id)")))
        if status == 404 { return nil }
        guard status == 200 else { throw failure(data, status) }
        return data
    }

    public func put(_ id: String, data body: Data, version: Int) async throws -> JournalWriteResult {
        var request = URLRequest(url: BackendHost.url(path: "/journal/items/\(id)", extraQueryItems: [URLQueryItem(name: "version", value: String(version))]))
        request.httpMethod = "PUT"
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        return try await write(request)
    }

    public func delete(_ id: String, version: Int) async throws -> JournalWriteResult {
        var request = URLRequest(url: BackendHost.url(path: "/journal/items/\(id)", extraQueryItems: [URLQueryItem(name: "version", value: String(version))]))
        request.httpMethod = "DELETE"
        return try await write(request)
    }

    private func write(_ request: URLRequest) async throws -> JournalWriteResult {
        let (data, status) = try await send(request)
        if status == 409, let reply = try? JSONDecoder().decode(VersionReply.self, from: data) { return .conflict(reply.version) }
        guard status == 200 else { throw failure(data, status) }
        return .saved(try JSONDecoder().decode(VersionReply.self, from: data).version)
    }
}
