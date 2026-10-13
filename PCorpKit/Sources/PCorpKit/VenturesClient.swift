import Foundation

/// VENTURES (2026-09-23, Phase 1) -- plain REST fetch-on-appear/pull-to-
/// refresh, same as every other dashboard in this app (confirmed during
/// planning: there is no real push/live-update infrastructure anywhere
/// in P Corp OS to plug into instead -- the one WebSocket is Frank's own
/// chat transport). Structure copied directly from JoshxClient.swift's
/// own fetch()/performWrite() pattern.
@MainActor
public final class VenturesClient: ObservableObject {
    @Published public private(set) var dashboard: VenturesDashboard?
    @Published public private(set) var opportunities: [Opportunity] = []
    @Published public private(set) var isLoading = false
    @Published public private(set) var isScanning = false
    @Published public private(set) var errorMessage: String?
    @Published public private(set) var lastScanReply: String?
    /// The current/last Opportunity Radar scan (it runs in the backend; see scanNow).
    @Published public private(set) var scanRun: ScanRun?

    // Phase 2 (2026-09-24) -- venture detail state, loaded on-demand when
    // a detail view opens rather than kept for every venture at once.
    @Published public private(set) var ventureDetail: Venture?
    @Published public private(set) var validationReports: [ValidationReport] = []
    @Published public private(set) var checklistItems: [ChecklistItem] = []
    @Published public private(set) var isRunningValidation = false
    @Published public private(set) var isRunningBuilder = false
    @Published public private(set) var lastValidationReply: String?
    @Published public private(set) var lastBuilderReply: String?

    // Phase 3 (2026-09-24) -- customers, revenue, fulfillment, delta.
    @Published public private(set) var customers: [Customer] = []
    @Published public private(set) var customerMetrics: CustomerMetrics?
    @Published public private(set) var revenueEvents: [RevenueEvent] = []
    @Published public private(set) var fulfillmentItems: [FulfillmentItem] = []
    @Published public private(set) var deltaEvents: [VentureDeltaEvent] = []

    // Phase 4 (2026-09-24) -- Financial/Marketing/Operations/Automation agents,
    // minimal Decision Journal linkage.
    @Published public private(set) var financialAnalysis: String?
    @Published public private(set) var isAnalyzingFinancials = false
    @Published public private(set) var marketingContent: [MarketingContent] = []
    @Published public private(set) var isGeneratingMarketingContent = false
    @Published public private(set) var isGeneratingOperationsSop = false
    @Published public private(set) var automationSuggestions: [AutomationSuggestion] = []
    @Published public private(set) var isScanningAutomation = false
    @Published public private(set) var ventureDecisions: [DecisionRecord] = []

    public init() {}

    private func url(_ path: String, extraQueryItems: [URLQueryItem] = []) -> URL {
        BackendHost.url(path: path, extraQueryItems: extraQueryItems)
    }

    private struct ErrorDetail: Decodable { let detail: String }

    private func performWrite(_ request: URLRequest) async -> String? {
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                return (try? JSONDecoder().decode(ErrorDetail.self, from: data))?.detail
                    ?? "Request failed (\(http.statusCode))."
            }
            return nil
        } catch {
            return "Couldn't reach the backend — is it running?"
        }
    }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/ventures/dashboard"))
            dashboard = try JSONDecoder().decode(VenturesDashboard.self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        do {
            let (data, _) = try await URLSession.shared.data(
                from: url("/ventures/opportunities", extraQueryItems: [URLQueryItem(name: "status", value: "new")])
            )
            struct OpportunitiesResponse: Decodable { let opportunities: [Opportunity] }
            opportunities = try JSONDecoder().decode(OpportunitiesResponse.self, from: data).opportunities
        } catch {
            opportunities = []
        }
        isLoading = false
        if !isScanning { Task { await resumeScanIfRunning() } }
    }

    public func createVenture(_ draft: VentureDraft) async -> Bool {
        var request = URLRequest(url: url("/ventures"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(draft)
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
        return writeError == nil
    }

    public func updateVentureStatus(id: Int, status: String) async {
        var request = URLRequest(url: url("/ventures/\(id)/status"))
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(["status": status])
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    public func deleteVenture(id: Int) async {
        var request = URLRequest(url: url("/ventures/\(id)"))
        request.httpMethod = "DELETE"
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    /// A current backend answers the start request at once and runs the scan in the background; the rest is polling
    /// `/scan/run`. An OLDER backend (the cloud one, until it is redeployed) runs the whole scan inside this one request
    /// and answers when it is finished -- a minute or two -- so the wait has to stay generous. Both work.
    private static let scanStartTimeout: TimeInterval = 150

    /// What the start request's answer means: (a scan is now running in the backend, or the reply of a scan an older
    /// backend already finished).
    nonisolated public static func parseScanStartResponse(_ data: Data) -> (runningInBackground: Bool, legacyReply: String?) {
        struct Start: Decodable { let started: Bool?; let reply: String? }
        let decoded = try? JSONDecoder().decode(Start.self, from: data)
        if decoded?.started == true { return (true, nil) }
        return (false, decoded?.reply)
    }

    /// Starts a scan and follows it until it ends. Safe to call again while one is running (it does nothing).
    public func scanNow() async {
        guard !isScanning else { return }
        isScanning = true
        errorMessage = nil
        var request = URLRequest(url: url("/ventures/opportunities/scan"))
        request.httpMethod = "POST"
        request.timeoutInterval = Self.scanStartTimeout
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                if http.statusCode == 409 {  // one is already running (e.g. the daily one): just follow it
                    await followScan()
                    return
                }
                errorMessage = (try? JSONDecoder().decode(ErrorDetail.self, from: data))?.detail
                    ?? "Request failed (\(http.statusCode))."
                isScanning = false
                return
            }
            let start = Self.parseScanStartResponse(data)
            if !start.runningInBackground {
                // An older backend already ran the whole scan inside that request: show its result, nothing to follow.
                lastScanReply = start.legacyReply
                await fetch()
                isScanning = false
                return
            }
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
            isScanning = false
            return
        }
        await followScan()
    }

    private struct ScanRunResponse: Decodable { let run: ScanRun? }

    /// (reachable, run) -- the run is nil when no scan has happened since the backend started.
    private func fetchScanRun() async -> (reachable: Bool, run: ScanRun?) {
        do {
            let (data, response) = try await URLSession.shared.data(from: url("/ventures/opportunities/scan/run"))
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { return (false, nil) }
            return (true, try JSONDecoder().decode(ScanRunResponse.self, from: data).run)
        } catch {
            return (false, nil)
        }
    }

    /// Polls every 2 s until the scan ends, then loads the results. A few missed polls in a row (backend restarted?)
    /// stop the wait with a plain message instead of spinning forever.
    private func followScan() async {
        isScanning = true
        var missed = 0
        while true {
            let (reachable, run) = await fetchScanRun()
            if reachable {
                missed = 0
                if run != scanRun { scanRun = run }
                if run?.isRunning != true { break }
            } else {
                missed += 1
                if missed >= 5 {
                    errorMessage = "Lost contact with the backend while the scan was running. It may still finish — reopen this screen in a minute."
                    isScanning = false
                    return
                }
            }
            try? await Task.sleep(nanoseconds: 2_000_000_000)
        }
        let finished = scanRun
        await fetch()  // loads the new opportunities (and clears errorMessage, so a failure is set after it)
        if finished?.state == "done" { lastScanReply = finished?.reply }
        if finished?.state == "failed" { errorMessage = finished?.message }
        isScanning = false
    }

    /// Picks up a scan the backend is already running (started on another device, by the daily job, or before this
    /// screen was opened), and remembers the last one's numbers.
    private func resumeScanIfRunning() async {
        guard !isScanning else { return }
        let (reachable, run) = await fetchScanRun()
        guard reachable else { return }
        if run != scanRun { scanRun = run }
        if run?.isRunning == true { await followScan() }
    }

    public func promoteOpportunity(id: Int) async {
        var request = URLRequest(url: url("/ventures/opportunities/\(id)/promote"))
        request.httpMethod = "POST"
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    public func dismissOpportunity(id: Int) async {
        var request = URLRequest(url: url("/ventures/opportunities/\(id)/dismiss"))
        request.httpMethod = "POST"
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    // MARK: - Phase 2: venture detail (2026-09-24)

    /// Loads everything the detail view needs in one call -- the venture
    /// itself, its checklist, and its validation-report history.
    public func fetchVentureDetail(id: Int) async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/ventures/\(id)"))
            ventureDetail = try JSONDecoder().decode(Venture.self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/ventures/\(id)/checklist"))
            struct ChecklistResponse: Decodable { let items: [ChecklistItem] }
            checklistItems = try JSONDecoder().decode(ChecklistResponse.self, from: data).items
        } catch {
            checklistItems = []
        }
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/ventures/\(id)/validation-reports"))
            struct ReportsResponse: Decodable { let reports: [ValidationReport] }
            validationReports = try JSONDecoder().decode(ReportsResponse.self, from: data).reports
        } catch {
            validationReports = []
        }
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/ventures/\(id)/customers"))
            struct CustomersResponse: Decodable { let customers: [Customer] }
            customers = try JSONDecoder().decode(CustomersResponse.self, from: data).customers
        } catch {
            customers = []
        }
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/ventures/\(id)/customer-metrics"))
            customerMetrics = try JSONDecoder().decode(CustomerMetrics.self, from: data)
        } catch {
            customerMetrics = nil
        }
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/ventures/\(id)/marketing-content"))
            struct Response: Decodable { let content: [MarketingContent] }
            marketingContent = try JSONDecoder().decode(Response.self, from: data).content
        } catch {
            marketingContent = []
        }
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/ventures/\(id)/automation-suggestions"))
            struct Response: Decodable { let suggestions: [AutomationSuggestion] }
            automationSuggestions = try JSONDecoder().decode(Response.self, from: data).suggestions
        } catch {
            automationSuggestions = []
        }
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/ventures/\(id)/decisions"))
            struct Response: Decodable { let decisions: [DecisionRecord] }
            ventureDecisions = try JSONDecoder().decode(Response.self, from: data).decisions
        } catch {
            ventureDecisions = []
        }
        isLoading = false
    }

    /// A real Claude call with web search -- same generous timeout as
    /// scanNow(), which already proved this can genuinely take a minute
    /// or two.
    private static let agentCallTimeout: TimeInterval = 150

    public func runValidation(ventureId: Int) async {
        isRunningValidation = true
        errorMessage = nil
        var request = URLRequest(url: url("/ventures/\(ventureId)/validate"))
        request.httpMethod = "POST"
        request.timeoutInterval = Self.agentCallTimeout
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                errorMessage = (try? JSONDecoder().decode(ErrorDetail.self, from: data))?.detail
                    ?? "Request failed (\(http.statusCode))."
            } else {
                struct ValidateResponse: Decodable { let reply: String }
                lastValidationReply = try JSONDecoder().decode(ValidateResponse.self, from: data).reply
            }
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        await fetchVentureDetail(id: ventureId)
        isRunningValidation = false
    }

    public func runBuilder(ventureId: Int) async {
        isRunningBuilder = true
        errorMessage = nil
        var request = URLRequest(url: url("/ventures/\(ventureId)/build"))
        request.httpMethod = "POST"
        request.timeoutInterval = Self.agentCallTimeout
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                errorMessage = (try? JSONDecoder().decode(ErrorDetail.self, from: data))?.detail
                    ?? "Request failed (\(http.statusCode))."
            } else {
                struct BuildResponse: Decodable { let reply: String }
                lastBuilderReply = try JSONDecoder().decode(BuildResponse.self, from: data).reply
            }
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        await fetchVentureDetail(id: ventureId)
        isRunningBuilder = false
    }

    public func addChecklistItem(ventureId: Int, title: String) async {
        var request = URLRequest(url: url("/ventures/\(ventureId)/checklist"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(["title": title])
        let writeError = await performWrite(request)
        await fetchVentureDetail(id: ventureId)
        if let writeError { errorMessage = writeError }
    }

    public func updateChecklistItemStatus(ventureId: Int, itemId: Int, status: String) async {
        var request = URLRequest(url: url("/ventures/\(ventureId)/checklist/\(itemId)"))
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(["status": status])
        let writeError = await performWrite(request)
        await fetchVentureDetail(id: ventureId)
        if let writeError { errorMessage = writeError }
    }

    public func deleteChecklistItem(ventureId: Int, itemId: Int) async {
        var request = URLRequest(url: url("/ventures/\(ventureId)/checklist/\(itemId)"))
        request.httpMethod = "DELETE"
        let writeError = await performWrite(request)
        await fetchVentureDetail(id: ventureId)
        if let writeError { errorMessage = writeError }
    }

    /// Returns whether the launch actually succeeded -- on failure (e.g.
    /// pending checklist items), the exact reason lands in errorMessage
    /// rather than being silently swallowed, so the UI can show Josh why.
    @discardableResult
    public func launchVenture(ventureId: Int) async -> Bool {
        var request = URLRequest(url: url("/ventures/\(ventureId)/launch"))
        request.httpMethod = "POST"
        let writeError = await performWrite(request)
        await fetchVentureDetail(id: ventureId)
        await fetch()
        if let writeError { errorMessage = writeError }
        return writeError == nil
    }

    // MARK: - Phase 3: customers, revenue, fulfillment, delta (2026-09-24)

    public func createCustomer(ventureId: Int, name: String, acquisitionSource: String?, acquisitionCost: Double?) async {
        var request = URLRequest(url: url("/ventures/\(ventureId)/customers"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        struct Body: Encodable { let name: String; let acquisition_source: String?; let acquisition_cost: Double? }
        request.httpBody = try? JSONEncoder().encode(Body(name: name, acquisition_source: acquisitionSource, acquisition_cost: acquisitionCost))
        let writeError = await performWrite(request)
        await fetchVentureDetail(id: ventureId)
        if let writeError { errorMessage = writeError }
    }

    public func updateCustomerStatus(ventureId: Int, customerId: Int, status: String) async {
        var request = URLRequest(url: url("/ventures/\(ventureId)/customers/\(customerId)"))
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(["status": status])
        let writeError = await performWrite(request)
        await fetchVentureDetail(id: ventureId)
        if let writeError { errorMessage = writeError }
    }

    public func deleteCustomer(ventureId: Int, customerId: Int) async {
        var request = URLRequest(url: url("/ventures/\(ventureId)/customers/\(customerId)"))
        request.httpMethod = "DELETE"
        let writeError = await performWrite(request)
        await fetchVentureDetail(id: ventureId)
        if let writeError { errorMessage = writeError }
    }

    public func fetchRevenueEvents(ventureId: Int, customerId: Int) async {
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/ventures/\(ventureId)/customers/\(customerId)/revenue-events"))
            struct Response: Decodable { let events: [RevenueEvent] }
            revenueEvents = try JSONDecoder().decode(Response.self, from: data).events
        } catch {
            revenueEvents = []
        }
    }

    public func logRevenueEvent(ventureId: Int, customerId: Int, amount: Double, eventType: String, notes: String?) async {
        var request = URLRequest(url: url("/ventures/\(ventureId)/customers/\(customerId)/revenue-events"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        struct Body: Encodable { let amount: Double; let event_type: String; let notes: String? }
        request.httpBody = try? JSONEncoder().encode(Body(amount: amount, event_type: eventType, notes: notes))
        let writeError = await performWrite(request)
        await fetchRevenueEvents(ventureId: ventureId, customerId: customerId)
        await fetchVentureDetail(id: ventureId)
        if let writeError { errorMessage = writeError }
    }

    public func fetchFulfillmentItems(ventureId: Int, customerId: Int) async {
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/ventures/\(ventureId)/customers/\(customerId)/fulfillment"))
            struct Response: Decodable { let items: [FulfillmentItem] }
            fulfillmentItems = try JSONDecoder().decode(Response.self, from: data).items
        } catch {
            fulfillmentItems = []
        }
    }

    public func addFulfillmentItem(ventureId: Int, customerId: Int, title: String) async {
        var request = URLRequest(url: url("/ventures/\(ventureId)/customers/\(customerId)/fulfillment"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(["title": title])
        let writeError = await performWrite(request)
        await fetchFulfillmentItems(ventureId: ventureId, customerId: customerId)
        if let writeError { errorMessage = writeError }
    }

    public func updateFulfillmentItemStatus(ventureId: Int, customerId: Int, itemId: Int, status: String) async {
        var request = URLRequest(url: url("/ventures/\(ventureId)/customers/\(customerId)/fulfillment/\(itemId)"))
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(["status": status])
        let writeError = await performWrite(request)
        await fetchFulfillmentItems(ventureId: ventureId, customerId: customerId)
        if let writeError { errorMessage = writeError }
    }

    public func deleteFulfillmentItem(ventureId: Int, customerId: Int, itemId: Int) async {
        var request = URLRequest(url: url("/ventures/\(ventureId)/customers/\(customerId)/fulfillment/\(itemId)"))
        request.httpMethod = "DELETE"
        let writeError = await performWrite(request)
        await fetchFulfillmentItems(ventureId: ventureId, customerId: customerId)
        if let writeError { errorMessage = writeError }
    }

    /// Fetches "what changed since you last looked" -- calling this
    /// marks Ventures as viewed server-side, same as opening The Brief
    /// does for its own feed, so a second call right after returns empty.
    public func fetchDelta() async {
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/ventures/delta"))
            struct Response: Decodable { let events: [VentureDeltaEvent] }
            deltaEvents = try JSONDecoder().decode(Response.self, from: data).events
        } catch {
            deltaEvents = []
        }
    }

    // MARK: - Phase 4: Financial/Marketing/Operations/Automation agents (2026-09-24)

    public func analyzeFinancials(ventureId: Int) async {
        isAnalyzingFinancials = true
        errorMessage = nil
        var request = URLRequest(url: url("/ventures/\(ventureId)/financial-analysis"))
        request.httpMethod = "POST"
        request.timeoutInterval = Self.agentCallTimeout
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                errorMessage = (try? JSONDecoder().decode(ErrorDetail.self, from: data))?.detail
                    ?? "Request failed (\(http.statusCode))."
            } else {
                struct Response: Decodable { let reply: String }
                financialAnalysis = try JSONDecoder().decode(Response.self, from: data).reply
            }
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        isAnalyzingFinancials = false
    }

    public func generateMarketingContent(ventureId: Int, contentType: String) async {
        isGeneratingMarketingContent = true
        errorMessage = nil
        var request = URLRequest(url: url("/ventures/\(ventureId)/marketing-content"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(["content_type": contentType])
        request.timeoutInterval = Self.agentCallTimeout
        let writeError = await performWrite(request)
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/ventures/\(ventureId)/marketing-content"))
            struct Response: Decodable { let content: [MarketingContent] }
            marketingContent = try JSONDecoder().decode(Response.self, from: data).content
        } catch {
            // leave marketingContent as-is on a read failure
        }
        if let writeError { errorMessage = writeError }
        isGeneratingMarketingContent = false
    }

    public func generateOperationsSop(ventureId: Int) async {
        isGeneratingOperationsSop = true
        errorMessage = nil
        var request = URLRequest(url: url("/ventures/\(ventureId)/operations-sop"))
        request.httpMethod = "POST"
        request.timeoutInterval = Self.agentCallTimeout
        let writeError = await performWrite(request)
        await fetchVentureDetail(id: ventureId)
        if let writeError { errorMessage = writeError }
        isGeneratingOperationsSop = false
    }

    public func scanForAutomation(ventureId: Int) async {
        isScanningAutomation = true
        errorMessage = nil
        var request = URLRequest(url: url("/ventures/\(ventureId)/automation-scan"))
        request.httpMethod = "POST"
        request.timeoutInterval = Self.agentCallTimeout
        let writeError = await performWrite(request)
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/ventures/\(ventureId)/automation-suggestions"))
            struct Response: Decodable { let suggestions: [AutomationSuggestion] }
            automationSuggestions = try JSONDecoder().decode(Response.self, from: data).suggestions
        } catch {
            // leave automationSuggestions as-is on a read failure
        }
        if let writeError { errorMessage = writeError }
        isScanningAutomation = false
    }

    public func updateAutomationSuggestionStatus(ventureId: Int, suggestionId: Int, status: String) async {
        var request = URLRequest(url: url("/ventures/\(ventureId)/automation-suggestions/\(suggestionId)"))
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(["status": status])
        let writeError = await performWrite(request)
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/ventures/\(ventureId)/automation-suggestions"))
            struct Response: Decodable { let suggestions: [AutomationSuggestion] }
            automationSuggestions = try JSONDecoder().decode(Response.self, from: data).suggestions
        } catch {
            // leave automationSuggestions as-is on a read failure
        }
        if let writeError { errorMessage = writeError }
    }
}
