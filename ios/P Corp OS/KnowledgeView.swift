import PCorpKit
import SwiftUI

/// Mobile translation of desktop's own KnowledgeView.swift (2026-08-13) --
/// fifth of the deferred sidebar sections, and the first to need a real
/// layout redesign rather than a direct port. Desktop is a fixed master-
/// detail HStack (a permanent 260pt doc list beside the content pane),
/// which has no room on a phone; this is a push-based list-then-detail
/// flow instead, using SwiftUI's own NavigationStack. Reuses PCorpKit's
/// SimpleMarkdownView unmodified (moved there from desktop for exactly
/// this reuse) and RootView's own topBar still owns the hamburger/back-
/// to-sidebar navigation -- this screen's NavigationStack is scoped to
/// list<->detail within Knowledge itself, a second, independent level of
/// navigation, not a replacement for it.
///
/// Bigger difference than layout: desktop reads these docs straight off
/// local disk, which only works because it runs on the same Mac as the
/// repo. A phone has no filesystem access to that Mac, so this is backed
/// by a real new backend surface (GET /knowledge, GET /knowledge/
/// {filename} — see KnowledgeClient.swift and backend/app/knowledge.py)
/// rather than being a pure client-side port like Frank/Settings/
/// Automations/Agents were.
struct KnowledgeView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var client = KnowledgeClient()

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Knowledge")
                .navigationBarTitleDisplayMode(.inline)
                .navigationDestination(for: KnowledgeDocSummary.self) { doc in
                    KnowledgeDocDetailView(doc: doc, client: client)
                }
        }
        .task { await client.fetch() }
    }

    @ViewBuilder
    private var content: some View {
        if client.isLoading && client.docs.isEmpty {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(theme.background)
        } else if let error = client.errorMessage {
            Text(error)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
                .padding(24)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(theme.background)
        } else {
            List(client.docs) { doc in
                NavigationLink(value: doc) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(doc.title)
                            .font(PCorpFont.body(15, weight: .semibold))
                            .foregroundStyle(theme.textPrimary)
                        Text(doc.subtitle)
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                    }
                    .padding(.vertical, 4)
                }
                .listRowBackground(theme.background)
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(theme.background)
        }
    }
}

private struct KnowledgeDocDetailView: View {
    let doc: KnowledgeDocSummary
    @ObservedObject var client: KnowledgeClient
    @Environment(\.appTheme) private var theme
    @State private var content: String?

    var body: some View {
        ScrollView {
            if let content {
                SimpleMarkdownView(text: content)
                    .padding(20)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                ProgressView()
                    .padding(.top, 60)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        .navigationTitle(doc.title)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            content = await client.fetchContent(filename: doc.filename)
        }
    }
}
