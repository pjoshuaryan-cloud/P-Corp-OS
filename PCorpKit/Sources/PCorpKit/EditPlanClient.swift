import Foundation

/// Talks to the edit-planning routes of one POST job (2026-10-09): what can be chosen (style, song, opening clip),
/// planning the edit, adding/removing accents, rendering the preview. Desktop-only by convention, like every other
/// POST action -- the Premiere plugin builds the actual sequence from the plan this saves.
///
/// Planning REPLACES the job's saved plan (the backend keeps the old one as edit_plan_prev_*.json first), so the
/// view warns when a reviewed plan exists.
@MainActor
public final class EditPlanClient: ObservableObject {
    @Published public private(set) var options: EditOptions?
    @Published public private(set) var momentsStatus: MomentsStatus?
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?
    /// Something worked but not everything (e.g. the plan was saved but the accents step failed).
    @Published public private(set) var warningMessage: String?
    /// Every saved plan of this job in plain words, current one first (2026-10-20).
    @Published public private(set) var planHistory: [PlanHistoryEntry] = []

    public let jobId: Int

    public init(jobId: Int) { self.jobId = jobId }

    private struct ErrorDetail: Decodable { let detail: String }

    /// A thumbnail of one of the job's clips (the token rides in the query like every other call).
    public func thumbURL(fileId: Int) -> URL {
        BackendHost.url(path: "/post/jobs/\(jobId)/clips/\(fileId)/thumb")
    }

    /// The moment-review page. The token goes after a "#" so it is never sent to a server or logged; the page keeps it
    /// and clears it from the address bar.
    public func reviewPageURL() -> URL {
        var components = URLComponents(
            url: BackendHost.url(path: "/static/edit_review.html", extraQueryItems: [URLQueryItem(name: "job", value: String(jobId))]),
            resolvingAgainstBaseURL: false
        )!
        let token = components.queryItems?.first(where: { $0.name == "token" })?.value ?? ""
        components.queryItems = components.queryItems?.filter { $0.name != "token" }
        if !token.isEmpty {
            // percentEncodedFragment, not fragment: the plain setter would encode the "%" signs a second time.
            let unreserved = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))
            components.percentEncodedFragment = "token=" + (token.addingPercentEncoding(withAllowedCharacters: unreserved) ?? token)
        }
        return components.url!
    }

    public func load() async {
        isLoading = true
        errorMessage = nil
        await reloadOptions()
        await loadPlanHistory()
        isLoading = false
    }

    // MARK: Plan history

    /// Re-reads the saved plans. A failure keeps the last list: the history is a convenience, never a reason to block planning.
    public func loadPlanHistory() async {
        do {
            let (data, response) = try await URLSession.shared.data(from: BackendHost.url(path: "/post/jobs/\(jobId)/edit-plans"))
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { return }
            struct Listed: Decodable { let plans: [PlanHistoryEntry] }
            let fetched = try JSONDecoder().decode(Listed.self, from: data).plans
            if fetched != planHistory { planHistory = fetched }
        } catch {
            // keep what we have
        }
    }

    /// Makes an earlier saved plan the current one (nothing is deleted: the plan it replaces is kept). Returns the backend's plain message, or nil if it failed.
    public func restorePlan(file: String) async -> String? {
        errorMessage = nil
        warningMessage = nil
        struct Body: Encodable { let file: String }
        guard let encoded = try? JSONEncoder().encode(Body(file: file)) else { errorMessage = "Couldn't build the request."; return nil }
        let result = await send("/post/jobs/\(jobId)/edit-plans/restore", body: encoded, timeout: 60)
        if let error = result.error {
            errorMessage = error
            return nil
        }
        struct Restored: Decodable { let message: String }
        let message = result.data.flatMap { try? JSONDecoder().decode(Restored.self, from: $0) }?.message ?? "Restored."
        await reloadOptions()
        await loadPlanHistory()
        return message
    }

    /// Gives a saved plan a name of your own (an empty name clears it).
    public func renamePlan(file: String, label: String) async {
        errorMessage = nil
        struct Body: Encodable { let file: String; let label: String }
        guard let encoded = try? JSONEncoder().encode(Body(file: file, label: label)) else { errorMessage = "Couldn't build the request."; return }
        if let error = await send("/post/jobs/\(jobId)/edit-plans/rename", body: encoded, timeout: 60).error { errorMessage = error }
        await loadPlanHistory()
    }

    /// Re-reads what can be chosen (e.g. after clips were described and now have labels).
    public func refreshOptions() async { await reloadOptions() }

    // MARK: Describing clips (costs real Claude credits -- always confirmed first by the caller)

    /// Re-reads just the state of the describe run (a cheap call, safe to poll every couple of seconds). The counts of
    /// described/missing clips are refreshed by `refreshOptions()` once a run ends.
    public func loadMomentsRun() async {
        do {
            let (data, response) = try await URLSession.shared.data(from: BackendHost.url(path: "/post/jobs/\(jobId)/find-moments/run"))
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode), let current = momentsStatus else { return }
            struct RunResponse: Decodable { let run: MomentsRun? }
            let run = try JSONDecoder().decode(RunResponse.self, from: data).run
            if run != current.run {
                momentsStatus = MomentsStatus(total: current.total, described: current.described, missing: current.missing, estimate: current.estimate, run: run, apiKeySet: current.apiKeySet)
            }
        } catch {
            // Keep the last known state; the next poll tries again.
        }
    }

    /// Starts describing the job's undescribed clips in the backend (it keeps going if this screen closes). `maxClips`
    /// is the spend cap: the number the confirmation showed. Returns true if a run started.
    public func startDescribingClips(maxClips: Int) async -> Bool {
        errorMessage = nil
        warningMessage = nil
        struct Body: Encodable { let maxClips: Int; enum CodingKeys: String, CodingKey { case maxClips = "max_clips" } }
        guard let encoded = try? JSONEncoder().encode(Body(maxClips: maxClips)) else { errorMessage = "Couldn't build the request."; return false }
        let result = await send("/post/jobs/\(jobId)/find-moments", body: encoded, timeout: 90)
        if let error = result.error {
            errorMessage = error
            return false
        }
        struct Started: Decodable { let started: Bool; let message: String? }
        let started = result.data.flatMap { try? JSONDecoder().decode(Started.self, from: $0) }
        if started?.started == false, let message = started?.message { warningMessage = message }
        await loadMomentsRun()
        return started?.started ?? false
    }

    /// Stops sending new clips; clips already described are kept.
    public func stopDescribingClips() async {
        _ = await send("/post/jobs/\(jobId)/find-moments/cancel", timeout: 30)
        await loadMomentsRun()
    }

    private func reloadOptions() async {
        do {
            let (data, response) = try await URLSession.shared.data(from: BackendHost.url(path: "/post/jobs/\(jobId)/edit-options"))
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                errorMessage = (try? JSONDecoder().decode(ErrorDetail.self, from: data))?.detail ?? "Request failed (\(http.statusCode))."
                return
            }
            let fetched = try JSONDecoder().decode(EditOptions.self, from: data)
            if fetched != options { options = fetched }
            if let describe = fetched.describe, describe != momentsStatus { momentsStatus = describe }
        } catch {
            errorMessage = "Couldn't load the planning options — is the backend running?"
        }
    }

    /// Returns the error text, or nil on success.
    private func send(_ path: String, body: Data? = nil, timeout: TimeInterval = 120) async -> (data: Data?, error: String?) {
        var request = URLRequest(url: BackendHost.url(path: path))
        request.httpMethod = "POST"
        request.timeoutInterval = timeout
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = body
        }
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                return (nil, (try? JSONDecoder().decode(ErrorDetail.self, from: data))?.detail ?? "Request failed (\(http.statusCode)).")
            }
            return (data, nil)
        } catch let error as URLError where error.code == .timedOut {
            return (nil, "That took too long. It may still be running — reopen this screen in a minute.")
        } catch {
            return (nil, "Couldn't reach the backend — is it running?")
        }
    }

    /// Plans the edit, then (if asked) adds the accents to the new plan. Returns true if the plan itself was saved.
    public func plan(_ body: EditPlanRequestBody, withAccents: Bool, withSoundEffects: Bool) async -> Bool {
        errorMessage = nil
        warningMessage = nil
        guard let encoded = try? JSONEncoder().encode(body) else { errorMessage = "Couldn't build the request."; return false }
        let planned = await send("/post/jobs/\(jobId)/edit-plan", body: encoded, timeout: 300)
        if let error = planned.error {
            errorMessage = error
            return false
        }
        if withAccents {
            let accentError = await setAccentsRequest(enabled: true, soundEffects: withSoundEffects)
            if let accentError { warningMessage = "The plan is saved, but the accents weren't added: \(accentError)" }
        }
        await reloadOptions()
        await loadPlanHistory()
        return true
    }

    private func setAccentsRequest(enabled: Bool, soundEffects: Bool) async -> String? {
        struct Body: Encodable { let enabled: Bool; let sfx: Bool }
        guard let encoded = try? JSONEncoder().encode(Body(enabled: enabled, sfx: soundEffects)) else { return "Couldn't build the request." }
        return await send("/post/jobs/\(jobId)/edit-accents", body: encoded, timeout: 300).error
    }

    public func setAccents(enabled: Bool, soundEffects: Bool) async {
        errorMessage = nil
        warningMessage = nil
        if let error = await setAccentsRequest(enabled: enabled, soundEffects: soundEffects) { errorMessage = error }
        await reloadOptions()
    }

    /// Renders the preview video; returns its file path on success.
    public func renderPreview() async -> String? {
        errorMessage = nil
        warningMessage = nil
        let result = await send("/post/jobs/\(jobId)/edit-preview", timeout: 600)
        if let error = result.error {
            errorMessage = error
            return nil
        }
        struct Rendered: Decodable { let previewPath: String; enum CodingKeys: String, CodingKey { case previewPath = "preview_path" } }
        let path = result.data.flatMap { try? JSONDecoder().decode(Rendered.self, from: $0) }?.previewPath
        await reloadOptions()
        return path
    }
}
