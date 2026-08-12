import SwiftUI
import PCorpKit

/// The "Calendar" nav section — real events from the macOS Calendar app
/// (SystemCalendar.swift), not placeholder data. Read-only: this shows what's
/// on the calendar, it doesn't create or edit events (a real, separate
/// feature if ever wanted, not implied by "show my schedule").
struct CalendarView: View {
    @Environment(\.appTheme) private var theme
    @State private var events: [CalendarEvent] = []
    @State private var isLoading = true

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(theme.divider)
            content
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        .task { await load() }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Calendar")
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text("Next 7 days")
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            Button {
                Task { await load() }
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(.icon)
        }
        .padding(24)
    }

    @ViewBuilder
    private var content: some View {
        if isLoading && events.isEmpty {
            emptyState(icon: "calendar", title: "Loading…", subtitle: "Reading events from the macOS Calendar app.")
        } else if events.isEmpty {
            emptyState(icon: "calendar", title: "Nothing on the calendar", subtitle: "No events in the next 7 days across any calendar.")
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 20) {
                    ForEach(groupedByDay, id: \.0) { day, dayEvents in
                        VStack(alignment: .leading, spacing: 10) {
                            Text(day)
                                .font(PCorpFont.label(10))
                                .trackedLabel(1.2)
                                .foregroundStyle(theme.textSecondary)
                            ForEach(dayEvents) { event in
                                EventRow(event: event)
                            }
                        }
                    }
                }
                .padding(24)
            }
        }
    }

    private var groupedByDay: [(String, [CalendarEvent])] {
        let formatter = DateFormatter()
        formatter.dateFormat = "EEEE, MMM d"
        let grouped = Dictionary(grouping: events) { formatter.string(from: $0.startDate) }
        return grouped.sorted { lhs, rhs in
            (grouped[lhs.key]?.first?.startDate ?? .distantFuture) < (grouped[rhs.key]?.first?.startDate ?? .distantFuture)
        }
    }

    private func load() async {
        isLoading = true
        events = await SystemCalendar.upcomingEvents(days: 7)
        isLoading = false
    }

    private func emptyState(icon: String, title: String, subtitle: String) -> some View {
        VStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 28))
                .foregroundStyle(theme.textSecondary)
            Text(title)
                .font(PCorpFont.body(14, weight: .semibold))
                .foregroundStyle(theme.textPrimary)
            Text(subtitle)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 340)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct EventRow: View {
    let event: CalendarEvent
    @Environment(\.appTheme) private var theme

    private var timeRange: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "h:mm a"
        return "\(formatter.string(from: event.startDate)) – \(formatter.string(from: event.endDate))"
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Text(timeRange)
                .font(PCorpFont.body(12, weight: .semibold))
                .foregroundStyle(theme.textSecondary)
                .frame(width: 130, alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                Text(event.title)
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(event.calendarName)
                    .font(PCorpFont.body(11))
                    .foregroundStyle(theme.textTertiary)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(.regularMaterial)
        )
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(theme.background.opacity(0.35))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(theme.surfaceBorder)
        )
    }
}
