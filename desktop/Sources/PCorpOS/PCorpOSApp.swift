import SwiftUI

@main
struct PCorpOSApp: App {
    var body: some Scene {
        WindowGroup("P Corp OS") {
            ContentView()
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentSize)
    }
}
