import Foundation
import SwiftUI

/// A real event from the macOS Calendar app.
struct CalendarEvent: Identifiable {
    let id = UUID()
    let title: String
    let startDate: Date
    let endDate: Date
    let calendarName: String
    /// The real color Joshua already assigned this calendar in the
    /// macOS Calendar app (2026-09-18, "I want work/home/family
    /// colour coordinated") -- read directly from Calendar.app itself
    /// via AppleScript's `color of cal`, not a scheme invented here, so
    /// this always matches whatever he sees there.
    let calendarColor: Color
}

/// Reads real events from the macOS Calendar app via AppleScript, not
/// EventKit — confirmed directly (2026-07-26) that EventKit silently denies
/// access on this app with no permission dialog ever appearing, same root
/// cause as UNUserNotificationCenter's earlier hard crash: this is still a
/// raw `swift build` executable, no real bundle/Info.plist for macOS to
/// attach a privacy-permission grant to. AppleScript doesn't need that.
///
/// Dates come back as small numeric components (year/month/day/hour/minute),
/// not a single epoch number — AppleScript's default number-to-string
/// coercion for large numbers (Unix epoch seconds, ~1.7 billion) uses the
/// system locale's decimal separator and scientific notation (confirmed:
/// produced "1,7851464E+9" on this machine), which silently fails to parse
/// as a Double in Swift. Small components sidestep that entirely.
enum SystemCalendar {
    private static let recordSeparator: Character = "\u{2}"
    private static let fieldSeparator: Character = "\u{1}"

    static func upcomingEvents(days: Int = 7) async -> [CalendarEvent] {
        let script = """
        tell application "Calendar"
            launch
            delay 1
            set startDate to current date
            set endDate to startDate + (\(days) * days)
            set output to ""
            repeat with cal in calendars
                try
                    set calColor to color of cal
                    set calR to item 1 of calColor
                    set calG to item 2 of calColor
                    set calB to item 3 of calColor
                    set calEvents to (every event of cal whose start date is greater than or equal to startDate and start date is less than or equal to endDate)
                    repeat with e in calEvents
                        set sd to start date of e
                        set ed to end date of e
                        set output to output & (summary of e as string) & (ASCII character 1) & (year of sd) & "-" & (month of sd as integer) & "-" & (day of sd) & "-" & (hours of sd) & "-" & (minutes of sd) & (ASCII character 1) & (year of ed) & "-" & (month of ed as integer) & "-" & (day of ed) & "-" & (hours of ed) & "-" & (minutes of ed) & (ASCII character 1) & (name of cal as string) & (ASCII character 1) & calR & "-" & calG & "-" & calB & (ASCII character 2)
                    end repeat
                end try
            end repeat
            return output
        end tell
        """
        let output = await runAppleScript(script)
        return parse(output).sorted { $0.startDate < $1.startDate }
    }

    private static func runAppleScript(_ script: String) async -> String {
        await withCheckedContinuation { continuation in
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
            process.arguments = ["-e", script]
            let pipe = Pipe()
            process.standardOutput = pipe
            process.terminationHandler = { _ in
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                continuation.resume(returning: String(data: data, encoding: .utf8) ?? "")
            }
            do {
                try process.run()
            } catch {
                continuation.resume(returning: "")
            }
        }
    }

    private static func parse(_ output: String) -> [CalendarEvent] {
        output.split(separator: recordSeparator).compactMap { record in
            let fields = record.split(separator: fieldSeparator, omittingEmptySubsequences: false)
            guard fields.count == 5,
                  let start = parseDateComponents(fields[1]),
                  let end = parseDateComponents(fields[2])
            else { return nil }
            return CalendarEvent(
                title: String(fields[0]),
                startDate: start,
                endDate: end,
                calendarName: String(fields[3]),
                calendarColor: parseColor(fields[4])
            )
        }
    }

    /// AppleScript's Calendar.app color is a 3-item {r, g, b} list, each
    /// 0-65535 (the same range Finder label colors and other older macOS
    /// scripting dictionaries use) -- confirmed live against Joshua's real
    /// calendars (2026-09-18): Work 59361,0,63948, Home 11396,39314,54351,
    /// Family 65535,52676,0.
    private static func parseColor(_ text: Substring) -> Color {
        let parts = text.split(separator: "-").compactMap { Double($0) }
        guard parts.count == 3 else { return .gray }
        return Color(red: parts[0] / 65535, green: parts[1] / 65535, blue: parts[2] / 65535)
    }

    /// Parses "year-month-day-hour-minute" (all plain integers, no padding).
    private static func parseDateComponents(_ text: Substring) -> Date? {
        let parts = text.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 5 else { return nil }
        var components = DateComponents()
        components.year = parts[0]
        components.month = parts[1]
        components.day = parts[2]
        components.hour = parts[3]
        components.minute = parts[4]
        return Calendar.current.date(from: components)
    }
}
