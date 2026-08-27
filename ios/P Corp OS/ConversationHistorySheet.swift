import PCorpKit
import SwiftUI

/// iOS port (2026-08-27) of desktop's own ConversationListPopover
/// (WarRoomView.swift there) -- same real backing (GET /conversations,
/// optionally ?q=... for real message-content search via
/// BackendClient.fetchConversationList), same day-grouped list, same
/// BackendClient.switchToConversation on selection. Presented as a
/// `.sheet` rather than desktop's `.popover`, matching this project's own
/// established iOS convention (see TheBriefSheet.swift's doc comment for
/// the same reasoning). Uses `.searchable` instead of desktop's manual
/// TextField + magnifying-glass row -- the native iOS idiom for exactly
/// this kind of list search, not a literal copy of desktop's layout.
struct ConversationHistorySheet: View {
    @ObservedObject var backend: BackendClient
    let onSelect: (Int) -> Void

    @State private var conversations: [ConversationSummary] = []
    @State private var isLoading = true
    @State private var searchText = ""
    @State private var searchTask: Task<Void, Never>?
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Conversations")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { dismiss() }
                    }
                }
                .searchable(text: $searchText, prompt: "Search all conversations…")
                .onChange(of: searchText) { _, newValue in
                    scheduleSearch(newValue)
                }
        }
        .presentationDetents([.medium, .large])
        .task { await load(query: nil) }
    }

    @ViewBuilder
    private var content: some View {
        if isLoading {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(theme.background)
        } else if conversations.isEmpty {
            Text(searchText.isEmpty ? "No conversations yet" : "No matches for \"\(searchText)\"")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(theme.background)
        } else {
            List {
                ForEach(groupedByDay, id: \.0) { day, dayConversations in
                    Section(day) {
                        ForEach(dayConversations) { conversation in
                            Button {
                                onSelect(conversation.id)
                                dismiss()
                            } label: {
                                row(conversation)
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

    /// Exact same grouping logic as desktop's ConversationListPopover --
    /// real calendar day in the user's local timezone (the DB stores UTC
    /// timestamps), groups ordered newest-first.
    private var groupedByDay: [(String, [ConversationSummary])] {
        let grouped = Dictionary(grouping: conversations) { conversation -> String in
            guard let date = Self.sqliteDateFormatter.date(from: conversation.lastMessageAt) else { return "Earlier" }
            if Calendar.current.isDateInToday(date) { return "Today" }
            if Calendar.current.isDateInYesterday(date) { return "Yesterday" }
            return Self.dayLabelFormatter.string(from: date)
        }
        return grouped.sorted { lhs, rhs in
            let lhsDate = lhs.value.first.flatMap { Self.sqliteDateFormatter.date(from: $0.lastMessageAt) } ?? .distantPast
            let rhsDate = rhs.value.first.flatMap { Self.sqliteDateFormatter.date(from: $0.lastMessageAt) } ?? .distantPast
            return lhsDate > rhsDate
        }
    }

    private static let sqliteDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return formatter
    }()

    private static let dayLabelFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "EEEE, MMM d"
        return formatter
    }()

    /// Debounced -- searching on every keystroke would mean a real
    /// request per character typed.
    private func scheduleSearch(_ text: String) {
        searchTask?.cancel()
        searchTask = Task {
            try? await Task.sleep(nanoseconds: 300_000_000)
            guard !Task.isCancelled else { return }
            await load(query: text)
        }
    }

    private func load(query: String?) async {
        isLoading = true
        conversations = await backend.fetchConversationList(query: query)
        isLoading = false
    }

    private func row(_ conversation: ConversationSummary) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(conversation.firstMessage ?? "New conversation")
                .font(PCorpFont.body(13))
                .foregroundStyle(theme.textPrimary)
                .lineLimit(1)
            Text("\(conversation.messageCount) message\(conversation.messageCount == 1 ? "" : "s")")
                .font(PCorpFont.body(11))
                .foregroundStyle(theme.textSecondary)
        }
        .padding(.vertical, 2)
    }
}
