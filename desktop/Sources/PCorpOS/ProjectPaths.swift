import Foundation

/// The P-Corp repo root, derived from where this source file was compiled
/// (`#filePath`), not the process's runtime working directory. Confirmed
/// directly (2026-07-26): cwd is `desktop/` under `swift run` (invoked from
/// there), but a properly launched real `.app` bundle has cwd `/` — every
/// path built on "cwd + relative path" (the auth token, the Knowledge docs)
/// silently breaks once the app is actually bundled and launched normally,
/// not run via the dev command. `#filePath` is fixed at compile time on the
/// build machine, so it's correct regardless of how the resulting binary
/// gets launched — the actual fix, not a workaround for one launch method.
enum ProjectPaths {
    static let repoRoot: URL = {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // PCorpOS/
            .deletingLastPathComponent() // Sources/
            .deletingLastPathComponent() // desktop/
            .deletingLastPathComponent() // P-Corp/
    }()
}
