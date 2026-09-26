import Foundation

/// POST (2026-09-25, Phase 1) -- plain REST fetch-on-appear/poll-while-
/// active, same "no push infrastructure exists in this app" reasoning
/// already established for Ventures. Structure copied directly from
/// VenturesClient.swift's own fetch()/performWrite() pattern.
///
/// Job creation/start/cancel/delete are desktop-only by design (Phase 1
/// decision): picking a source drive needs a live listing only the Mac
/// physically connected to it can produce, so PostView.swift on iOS
/// only ever calls fetch()/fetchJob() -- it never calls createJob/
/// startJob/cancelJob/deleteJob at all, even though nothing here
/// prevents it structurally (both platforms share this one client).
@MainActor
public final class PostClient: ObservableObject {
    @Published public private(set) var jobs: [PostJob] = []
    @Published public private(set) var sourceVolumes: [SourceVolume] = []
    @Published public private(set) var profiles: [String: PostProfile] = [:]
    @Published public private(set) var isLoading = false
    @Published public private(set) var isLoadingSources = false
    @Published public private(set) var errorMessage: String?

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
            let (data, _) = try await URLSession.shared.data(from: url("/post/jobs"))
            struct JobsResponse: Decodable { let jobs: [PostJob] }
            jobs = try JSONDecoder().decode(JobsResponse.self, from: data).jobs
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        isLoading = false
    }

    /// Single-job poll target, used while any job isActive -- returns
    /// the fresh row without touching the whole `jobs` list, but also
    /// updates it in place if present so a detail view and a list view
    /// never show conflicting progress.
    public func pollJob(id: Int) async -> PostJob? {
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/post/jobs/\(id)"))
            let job = try JSONDecoder().decode(PostJob.self, from: data)
            if let index = jobs.firstIndex(where: { $0.id == id }) {
                jobs[index] = job
            }
            return job
        } catch {
            return nil
        }
    }

    public func fetchSources() async {
        isLoadingSources = true
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/post/jobs/sources"))
            struct SourcesResponse: Decodable { let volumes: [SourceVolume] }
            sourceVolumes = try JSONDecoder().decode(SourcesResponse.self, from: data).volumes
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        isLoadingSources = false
    }

    public func fetchProfiles() async {
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/post/profiles"))
            struct ProfilesResponse: Decodable { let profiles: [String: PostProfile] }
            profiles = try JSONDecoder().decode(ProfilesResponse.self, from: data).profiles
        } catch {
            // Non-fatal -- the profile picker just falls back to the
            // plain postProfileNames constant with no folder preview.
        }
    }

    public func fetchJobFiles(id: Int) async -> [PostJobFile] {
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/post/jobs/\(id)/files"))
            struct FilesResponse: Decodable { let files: [PostJobFile] }
            return try JSONDecoder().decode(FilesResponse.self, from: data).files
        } catch {
            return []
        }
    }

    public func createJob(_ draft: PostJobDraft) async -> Int? {
        var request = URLRequest(url: url("/post/jobs"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(draft)
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                errorMessage = (try? JSONDecoder().decode(ErrorDetail.self, from: data))?.detail
                    ?? "Request failed (\(http.statusCode))."
                return nil
            }
            struct CreateResponse: Decodable { let id: Int }
            let created = try JSONDecoder().decode(CreateResponse.self, from: data)
            await fetch()
            return created.id
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
            return nil
        }
    }

    public func startJob(id: Int) async {
        var request = URLRequest(url: url("/post/jobs/\(id)/start"))
        request.httpMethod = "POST"
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    public func cancelJob(id: Int) async {
        var request = URLRequest(url: url("/post/jobs/\(id)/cancel"))
        request.httpMethod = "POST"
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    public func deleteJob(id: Int) async {
        var request = URLRequest(url: url("/post/jobs/\(id)"))
        request.httpMethod = "DELETE"
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    // MARK: - Phase 2: media intelligence

    public func analyzeMedia(jobId: Int) async {
        var request = URLRequest(url: url("/post/jobs/\(jobId)/analyze-media"))
        request.httpMethod = "POST"
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    public func fetchMediaReport(jobId: Int) async -> MediaReport? {
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/post/jobs/\(jobId)/media-report"))
            return try JSONDecoder().decode(MediaReport.self, from: data)
        } catch {
            return nil
        }
    }

    // MARK: - Phase 4: proxies

    public func fetchProxyRecommendations(jobId: Int) async -> [ProxyRecommendation] {
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/post/jobs/\(jobId)/proxy-recommendations"))
            struct RecommendationsResponse: Decodable { let recommendations: [ProxyRecommendation] }
            return try JSONDecoder().decode(RecommendationsResponse.self, from: data).recommendations
        } catch {
            return []
        }
    }

    public func generateProxies(jobId: Int) async {
        var request = URLRequest(url: url("/post/jobs/\(jobId)/generate-proxies"))
        request.httpMethod = "POST"
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    public func fetchProxies(jobId: Int) async -> [ProxyStatus] {
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/post/jobs/\(jobId)/proxies"))
            struct ProxiesResponse: Decodable { let proxies: [ProxyStatus] }
            return try JSONDecoder().decode(ProxiesResponse.self, from: data).proxies
        } catch {
            return []
        }
    }
}
