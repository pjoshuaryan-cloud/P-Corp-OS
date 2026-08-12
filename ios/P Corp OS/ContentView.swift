import SwiftUI
import PCorpKit

/// Token gate for the app -- once connected, hands off to WarRoomView
/// (2026-08-12), the real screen. This file's own first pass (a plain
/// chat thread) proved the pipeline worked; that content now lives in
/// WarRoomView.swift, properly designed.
struct ContentView: View {
    // Keychain-backed (2026-08-12), not @AppStorage/UserDefaults --
    // loaded once here since Keychain reads are synchronous and cheap;
    // updated explicitly in tokenEntryView's Connect button rather than
    // relying on a property wrapper to persist it automatically.
    @State private var storedToken: String = KeychainTokenStore.load() ?? ""
    @State private var tokenInput = ""

    var body: some View {
        if storedToken.isEmpty {
            tokenEntryView
        } else {
            WarRoomView()
        }
    }

    private var tokenEntryView: some View {
        VStack(spacing: 16) {
            Text("Connect to Frank")
                .font(.title2.bold())
            Text("Paste the auth token from your Mac's backend/data/auth_token file.")
                .font(.footnote)
                .foregroundStyle(.secondary)
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
