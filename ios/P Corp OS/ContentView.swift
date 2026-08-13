import SwiftUI
import PCorpKit

/// Token gate for the app -- once connected, hands off to RootView
/// (2026-08-12), which owns the hamburger/sidebar navigation and picks
/// between WarRoomView and the other sections. This file's own first pass
/// (a plain chat thread) proved the pipeline worked; that content now
/// lives in WarRoomView.swift, properly designed.
struct ContentView: View {
    // Keychain-backed (2026-08-12), not @AppStorage/UserDefaults --
    // loaded once here since Keychain reads are synchronous and cheap;
    // updated explicitly in tokenEntryView's Connect button rather than
    // relying on a property wrapper to persist it automatically.
    @State private var storedToken: String = KeychainTokenStore.load() ?? ""
    @State private var tokenInput = ""
    // Real now (2026-08-13), resolving a flagged deviation from the
    // earlier visual-matching pass: desktop picks AppTheme from a manual
    // Settings toggle, not the system appearance, but there was no
    // Settings screen on iOS yet to host one, so this fell back to
    // following colorScheme instead. SettingsView.swift now exists, so
    // this reads the same @AppStorage key desktop does.
    @AppStorage(AppStorageKeys.darkModeEnabled) private var darkModeEnabled = false

    var body: some View {
        Group {
            if storedToken.isEmpty {
                tokenEntryView
            } else {
                RootView()
            }
        }
        .environment(\.appTheme, darkModeEnabled ? .dark : .light)
    }

    // No exact desktop equivalent -- desktop reads its token from a
    // local file automatically, no entry screen exists there at all.
    // Same fonts/theme colors as everything else regardless, for visual
    // consistency across the app.
    private var tokenEntryView: some View {
        VStack(spacing: 16) {
            Text("Connect to Frank")
                .font(PCorpFont.display(20))
                .foregroundStyle(darkModeEnabled ? AppTheme.dark.textPrimary : AppTheme.light.textPrimary)
            Text("Paste the auth token from your Mac's backend/data/auth_token file.")
                .font(PCorpFont.body(13))
                .foregroundStyle(darkModeEnabled ? AppTheme.dark.textSecondary : AppTheme.light.textSecondary)
                .multilineTextAlignment(.center)
            TextField("Auth token", text: $tokenInput)
                .textFieldStyle(.roundedBorder)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            Button("Connect") {
                let trimmed = tokenInput.trimmingCharacters(in: .whitespacesAndNewlines)
                KeychainTokenStore.save(trimmed)
                storedToken = trimmed
            }
            .buttonStyle(.borderedProminent)
            .disabled(tokenInput.isEmpty)
        }
        .padding()
    }
}

#Preview {
    ContentView()
}
