import Foundation

/// Proactive Triggers Layer (2026-08-21) -- the first PCorpKit client
/// whose UI directly mutates backend state (toggleRule), rather than
/// Frank being the only writer (unlike Personal/Alpha Mode, this is
/// plain settings-style state with no reason to route through a
/// conversation). Same one-shot fetch pattern as TradingDivisionClient/
/// PersonalClient otherwise, and the same optimistic-update-then-fire
/// pattern MemoryClient.forget() already uses for its DELETE call.
@MainActor
public final class TriggersClient: ObservableObject {
    @Published public private(set) var status: TriggerStatus?
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?
    @Published public private(set) var lastRunResult: TriggerRunResult?

    public init() {}

    private func url(path: String) -> URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731\(path)")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url(path: "/triggers/status"))
            status = try JSONDecoder().decode(TriggerStatus.self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        isLoading = false
    }

    /// Flips a rule's enabled state optimistically (mirrors the section
    /// list immediately, same reasoning as MemoryClient.forget()'s
    /// optimistic removal) then fires the real PATCH. Refetches on
    /// failure rather than guessing what the server-side state actually
    /// ended up as.
    public func toggleRule(ruleType: String, enabled: Bool) async {
        guard let current = status else { return }
        let optimisticRules = current.rules.map { section in
            section.ruleType == ruleType
                ? TriggerRuleSection(ruleType: section.ruleType, label: section.label, enabled: enabled, thresholdDays: section.thresholdDays, items: section.items)
                : section
        }
        status = TriggerStatus(rules: optimisticRules, lastSentDate: current.lastSentDate, sendHour: current.sendHour)

        var request = URLRequest(url: url(path: "/triggers/rules/\(ruleType)"))
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(["enabled": enabled])
        do {
            _ = try await URLSession.shared.data(for: request)
        } catch {
            await fetch()
        }
    }

    /// Manual "send digest now" -- bypasses the scheduler's send_hour
    /// gate but not the real rule engine or email send, for confirming
    /// the whole path actually works without waiting for tomorrow.
    public func runNow() async {
        var request = URLRequest(url: url(path: "/triggers/run-now"))
        request.httpMethod = "POST"
        do {
            let (data, _) = try await URLSession.shared.data(for: request)
            lastRunResult = try JSONDecoder().decode(TriggerRunResult.self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        await fetch()
    }
}
