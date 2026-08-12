import SwiftUI
import PCorpKit

/// First real iOS screen (2026-08-12) -- proves the whole pipeline works
/// end to end: PCorpKit's shared BackendClient talking to the same
/// backend the desktop app uses, over the Tailscale listener, from a
/// real iPhone. Deliberately minimal -- a plain chat thread, not War
/// Room's full visual design -- that's real follow-on work once this
/// proves out, not part of proving the plumbing works.
struct ContentView: View {
    @StateObject private var backend = BackendClient()
    @AppStorage("backendAuthToken") private var storedToken = ""
    @State private var tokenInput = ""
    @State private var inputText = ""

    var body: some View {
        if storedToken.isEmpty {
            tokenEntryView
        } else {
            chatView
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
                storedToken = tokenInput.trimmingCharacters(in: .whitespacesAndNewlines)
            }
            .buttonStyle(.borderedProminent)
            .disabled(tokenInput.isEmpty)
        }
        .padding()
    }

    private var chatView: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        ForEach(backend.messages) { message in
                            HStack {
                                if message.role == "user" { Spacer() }
                                Text(message.content.isEmpty ? "…" : message.content)
                                    .padding(10)
                                    .background(message.role == "user" ? Color.blue.opacity(0.15) : Color.gray.opacity(0.12))
                                    .clipShape(RoundedRectangle(cornerRadius: 12))
                                if message.role == "assistant" { Spacer() }
                            }
                        }
                    }
                    .padding()
                }
                HStack {
                    TextField("Talk to Frank...", text: $inputText)
                        .textFieldStyle(.roundedBorder)
                    Button("Send") {
                        backend.send(inputText)
                        inputText = ""
                    }
                    .disabled(inputText.isEmpty)
                }
                .padding()
            }
            .navigationTitle("Frank")
            .onAppear { backend.connect() }
        }
    }
}

#Preview {
    ContentView()
}
