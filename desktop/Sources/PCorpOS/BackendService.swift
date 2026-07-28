import Foundation
import ServiceManagement

/// Stage 3 of SMAppService packaging (TECH_STACK.md): registers the backend
/// shim (Contents/MacOS/PCorpOSBackend, embedded Python runtime included —
/// stage 2) as a persistent LaunchAgent, so Frank's backend genuinely runs
/// as an always-available background service, not something that only
/// exists while this SwiftUI window happens to be open. This is the step
/// that actually delivers the capability stages 1-2 were prerequisites for.
///
/// `SMAppService.agent(plistName:)` requires the launchd plist to live at
/// Contents/Library/LaunchAgents/<name>.plist inside the app bundle
/// (written by build_app.sh), and its ProgramArguments[0] to reference an
/// executable co-located in Contents/MacOS/ of the same bundle — a real
/// requirement of the API, not a convention. Only works when this code
/// runs from inside the actual bundled .app (Bundle.main needs a real
/// identity) — calling this from `swift run` will fail, by design.
enum BackendService {
    private static let plistName = "media.alphamode.pcorpos.backend.plist"
    private static var service: SMAppService { .agent(plistName: plistName) }

    static var status: SMAppService.Status {
        service.status
    }

    static func register() throws {
        try service.register()
    }

    static func unregister() throws {
        try service.unregister()
    }
}
