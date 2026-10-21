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
print("\nFAILS: \(fails)")
exit(fails == 0 ? 0 : 1)
