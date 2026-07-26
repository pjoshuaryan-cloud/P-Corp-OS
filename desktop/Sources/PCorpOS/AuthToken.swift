import Foundation

/// Reads the local auth token the backend generates on first startup
/// (backend/app/auth.py, backend/data/auth_token) — a machine-generated
/// shared secret, not something Joshua configures. Read fresh on every
/// connect rather than cached, matching MemoryClient's one-shot-fetch style —
/// simplest way to always reflect whatever the backend currently has.
enum AuthToken {
    static var current: String? {
        let url = ProjectPaths.repoRoot.appendingPathComponent("backend/data/auth_token")
        return try? String(contentsOf: url, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
