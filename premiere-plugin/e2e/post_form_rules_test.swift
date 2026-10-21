// Tests for PostFormRules (PCorpKit/Sources/PCorpKit/PostFormRules.swift). No test target exists in this package, so this compiles the rules file with a tiny runner
// (swiftc only allows top-level code in a file called main.swift, hence the copy):
//   cd premiere-plugin/e2e && mkdir -p /tmp/swiftrules && cp post_form_rules_test.swift /tmp/swiftrules/main.swift \
//     && swiftc ../../PCorpKit/Sources/PCorpKit/PostFormRules.swift /tmp/swiftrules/main.swift -o /tmp/swiftrules/run && /tmp/swiftrules/run
import Foundation

var fails = 0
func check(_ name: String, _ ok: Bool, _ detail: String = "") {
    print((ok ? "PASS " : "FAIL ") + name + (detail.isEmpty ? "" : "   [\(detail)]"))
    if !ok { fails += 1 }
}
let blocker = PostFormRules.createJobBlocker

check("a complete form has nothing blocking it", blocker("GWM", "joshx", "", "/Volumes/A", "/Volumes/B") == nil)
check("a complete Alpha Mode form (with a client) has nothing blocking it", blocker("GWM", "alpha_mode", "Two Tone", "/Volumes/A", "/Volumes/B") == nil)
check("no shoot name says to name it", blocker("", "joshx", "", nil, nil) == "Give the shoot a name.")
check("a name of only spaces counts as no name", blocker("   \n", "joshx", "", "/Volumes/A", "/Volumes/B") == "Give the shoot a name.")
check("an Alpha Mode shoot with no client says so", blocker("GWM", "alpha_mode", "  ", "/Volumes/A", "/Volumes/B") == "Alpha Mode shoots need a client name.")
check("a Joshx shoot doesn't need a client", blocker("GWM", "joshx", "", "/Volumes/A", "/Volumes/B") == nil)
check("no source drive says to choose it", blocker("GWM", "joshx", "", nil, "/Volumes/B")?.contains("source drive") == true)
check("no destination drive says to choose it", blocker("GWM", "joshx", "", "/Volumes/A", nil)?.contains("destination drive") == true)
check("the first missing thing wins, in the order the form is filled in", blocker("", "alpha_mode", "", nil, nil) == "Give the shoot a name." && blocker("GWM", "alpha_mode", "", nil, nil) == "Alpha Mode shoots need a client name." && blocker("GWM", "alpha_mode", "X", nil, nil)?.contains("source") == true)
check("it agrees with the old yes/no rule for every combination", {
    for name in ["", "x"] { for profile in ["joshx", "alpha_mode"] { for client in ["", "c"] { for src in [nil, "/s"] as [String?] { for dst in [nil, "/d"] as [String?] {
        let old = !name.isEmpty && src != nil && dst != nil && (profile != "alpha_mode" || !client.isEmpty)
        if (blocker(name, profile, client, src, dst) == nil) != old { return false }
    } } } } }
    return true
}())
// ---- the "More" menu on the shoot card -----------------------------------------------------------------------------------------------------
let more = PostFormRules.moreActions
check("a copied, analysed shoot that would benefit from proxies offers proxies and highlights", more("ingested", true, false, 3) == [.generateProxies, .detectHighlights])
check("once proxies exist their status is offered too, in menu order", more("ingested", true, true, 3) == [.generateProxies, .proxyStatus, .detectHighlights])
check("no recommended proxies means no proxy action (but highlights still)", more("ingested", true, false, 0) == [.detectHighlights] && more("ingested", true, false, nil) == [.detectHighlights])
check("a shoot that already has its Premiere project can still detect highlights, but not make proxies", more("premiere_project_created", true, false, 5) == [.detectHighlights])
check("an unanalysed shoot has nothing under More", more("ingested", false, false, 5).isEmpty)
check("a shoot that hasn't finished has no More menu at all", more("created", false, false, nil).isEmpty && more("ingesting", false, false, nil).isEmpty && more("verifying", false, false, nil).isEmpty)
check("Proxy Status shows whenever proxies were made, as before", more("ingest_failed", false, true, nil) == [.proxyStatus])
check("it agrees with the three old button conditions for every combination", {
    for status in ["created", "scanning", "ingesting", "verifying", "analyzing_media", "ingested", "ingest_failed", "cancelled", "premiere_project_created", "generating_proxies"] {
        for analysed in [false, true] { for proxies in [false, true] { for count in [nil, 0, 4] as [Int?] {
            let oldProxies = status == "ingested" && analysed && (count ?? 0) > 0
            let oldStatus = proxies
            let oldHighlights = (status == "ingested" || status == "premiere_project_created") && analysed
            let expected = (oldProxies ? [PostFormRules.MoreAction.generateProxies] : []) + (oldStatus ? [.proxyStatus] : []) + (oldHighlights ? [.detectHighlights] : [])
            if more(status, analysed, proxies, count) != expected { return false }
        } } }
    }
    return true
}())
print("\nFAILS: \(fails)")
exit(fails == 0 ? 0 : 1)
