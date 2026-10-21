import Foundation

/// The rules behind the POST screen's greyed-out buttons (2026-10-20), kept in one pure function so the reason shown under a button is always the real reason it is
/// greyed, and so it can be tested without a window. A greyed-out control with no explanation reads as broken; this gives the first thing still missing.
public enum PostFormRules {
    /// Why "Create Job" can't be pressed yet, as a sentence saying what to do, or nil when the form is complete. The first missing thing wins, in the order the form is filled in.
    public static func createJobBlocker(shootName: String, profile: String, clientName: String, sourcePath: String?, destinationPath: String?) -> String? {
        if shootName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "Give the shoot a name." }
        if profile == "alpha_mode" && clientName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "Alpha Mode shoots need a client name." }
        if sourcePath == nil { return "Choose the source drive (where the footage is now)." }
        if destinationPath == nil { return "Choose the destination drive (where the copy goes)." }
        return nil
    }

    /// The shoot card's secondary actions that live under "More" (2026-10-21): they are rarely wanted, and proxies in particular are not attached in Premiere by default.
    public enum MoreAction: Equatable {
        case generateProxies, proxyStatus, detectHighlights
    }

    /// Which "More" actions apply to a shoot, in menu order (empty = no More menu at all). The same conditions the buttons always had, moved here so they can be tested.
    public static func moreActions(status: String, mediaAnalyzed: Bool, proxiesGenerated: Bool, recommendedProxyCount: Int?) -> [MoreAction] {
        var actions: [MoreAction] = []
        if status == "ingested" && mediaAnalyzed && (recommendedProxyCount ?? 0) > 0 { actions.append(.generateProxies) }
        if proxiesGenerated { actions.append(.proxyStatus) }
        if (status == "ingested" || status == "premiere_project_created") && mediaAnalyzed { actions.append(.detectHighlights) }
        return actions
    }
}
