import Foundation

/// Reads the local auth token the backend generates on first startup
/// (backend/app/auth.py, backend/data/auth_token) — a machine-generated
/// shared secret, not something Joshua configures. Read fresh on every
/// connect rather than cached, matching MemoryClient's one-shot-fetch style —
/// simplest way to always reflect whatever the backend currently has.
///
/// Path is relative to cwd, matching how this whole project runs today
/// (swift run from desktop/, uv run from backend/ — nothing packaged into
/// a real .app yet). Revisit once SMAppService packaging happens.
enum AuthToken {
    static var current: String? {
        let path = FileManager.default.currentDirectoryPath + "/../backend/data/auth_token"
        return try? String(contentsOfFile: path, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
