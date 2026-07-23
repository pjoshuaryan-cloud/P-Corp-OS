import SwiftUI

@main
struct PCorpOSApp: App {
    var body: some Scene {
        WindowGroup("P Corp OS") {
            ContentView()
                // The design is a fixed light aesthetic (white/near-white
                // surfaces, black text and accents), not a light/dark pair
                // yet. Without this, semantic colors like .secondary adapt
                // to system dark mode and render near-invisible on these
                // light backgrounds. Revisit if/when a real dark mode gets
                // designed on purpose, per UI_GUIDELINES.md.
                .preferredColorScheme(.light)
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentSize)
    }
}
