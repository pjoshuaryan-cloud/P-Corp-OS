import PCorpKit
import SwiftUI

/// The magnifying-glass button's real destination (2026-08-27) -- was a
/// documented no-op "reserved for future search" since first built.
/// Genuinely cross-domain ("Spotlight for P Corp OS"), backed by
/// GET /search -- distinct from ConversationHistorySheet
/// (GET /conversations?q=...), which searches real message CONTENT within
/// chat history only. Same structural pattern as that just-shipped sheet:
/// NavigationStack, .searchable, grouped List -- grouped by domain here
/// instead of by day.
struct UniversalSearchSheet: View {
    let onSelect: (SearchResult) -> Void

    @StateObject private var searchClient = SearchClient()
    @State private var searchText = ""
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Search")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { dismiss() }
                    }
                }
                .searchable(text: $searchText, prompt: "Search everything…")
                .onChange(of: searchText) { _, newValue in
                    searchClient.scheduleSearch(newValue)
                }
        }
        .presentationDetents([.medium, .large])
    }

    @ViewBuilder
    private var content: some View {
        if searchText.isEmpty {
            Text("Search projects, clients, goals, docs, and more")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(theme.background)
        } else if searchClient.isLoading && searchClient.results.isEmpty {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(theme.background)
        } else if searchClient.results.isEmpty {
            Text("No matches for \"\(searchText)\"")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(theme.background)
        } else {
            List {
                ForEach(groupedByDomain, id: \.0) { domain, domainResults in
                    Section(domain) {
                        ForEach(domainResults) { result in
                            Button {
                                onSelect(result)
                                dismiss()
                            } label: {
                                row(result)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .listStyle(.plain)
            .background(theme.background)
        }
    }

    /// Preserves search_all()'s own domain order (Knowledge, Alpha Mode
    /// Media, Joshx, Finance, Personal, Automations, Conversations) rather
    /// than alphabetizing it away -- Dictionary(grouping:) loses order, so
    /// groups are rebuilt in first-seen order from the already-ordered
    /// results instead.
    private var groupedByDomain: [(String, [SearchResult])] {
        var order: [String] = []
        var buckets: [String: [SearchResult]] = [:]
        for result in searchClient.results {
            if buckets[result.domain] == nil {
                order.append(result.domain)
                buckets[result.domain] = []
            }
            buckets[result.domain]?.append(result)
        }
        return order.map { ($0, buckets[$0] ?? []) }
    }

    private func row(_ result: SearchResult) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(result.title)
                .font(PCorpFont.body(13))
                .foregroundStyle(theme.textPrimary)
                .lineLimit(1)
            Text(result.subtitle)
                .font(PCorpFont.body(11))
                .foregroundStyle(theme.textSecondary)
                .lineLimit(1)
        }
        .padding(.vertical, 2)
    }
}
