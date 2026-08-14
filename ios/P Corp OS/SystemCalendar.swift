import EventKit
import Foundation

struct CalendarEvent: Identifiable {
    let id = UUID()
    let title: String
    let startDate: Date
    let endDate: Date
    let calendarName: String
}

/// iOS's own EventKit read of the phone's own Calendar app (2026-08-14) --
/// not a proxy through the Mac's backend, and not a port of desktop's own
/// SystemCalendar.swift. Desktop reads the macOS Calendar app via
/// AppleScript specifically to work around a permissions bug in its own
/// raw `swift build` executable (no real bundle for macOS to attach a
/// privacy grant to, per that file's own docstring) -- that workaround
/// has no iOS equivalent at all (no AppleScript on iOS), and isn't needed
/// here anyway: this is a properly bundled app with a real Info.plist, so
/// the normal EventKit permission flow (NSCalendarsFullAccessUsageDescription
/// below) works as designed, no workaround required.
///
/// Genuinely a different data source from desktop, not just a different
/// mechanism to reach the same one -- flagged as a real, honest limitation:
/// this reads the iPhone's own Calendar app, not the Mac's. In practice
/// these usually show the same events (Joshua's own iCloud calendar synced
/// to both devices), but if the two ever diverge, that's why.
enum SystemCalendar {
    static func upcomingEvents(days: Int = 7) async -> [CalendarEvent] {
        let store = EKEventStore()
        let granted: Bool
        do {
            granted = try await store.requestFullAccessToEvents()
        } catch {
            return []
        }
        guard granted else { return [] }

        let start = Date()
        guard let end = Calendar.current.date(byAdding: .day, value: days, to: start) else { return [] }
        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: nil)

        return store.events(matching: predicate)
            .map {
                CalendarEvent(
                    title: $0.title ?? "(untitled)",
                    startDate: $0.startDate,
                    endDate: $0.endDate,
                    calendarName: $0.calendar.title
                )
            }
            .sorted { $0.startDate < $1.startDate }
    }
}
