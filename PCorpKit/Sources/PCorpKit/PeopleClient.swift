import Foundation

/// Plain REST fetch for GET /people/dashboard -- same one-shot pattern as
/// JoshxClient/PersonalClient, backing the "PEOPLE" section inside
/// Personal (Josh's real personal/professional relationship network,
/// deliberately separate from Joshx/Alpha Mode Media clients -- see
/// backend/app/people_db.py's docstring). A sibling client alongside
/// PersonalClient in the view, not a merged endpoint -- keeps the two
/// data sources independently fetchable/failable, same as WarRoomView
/// already keeps focusClient/insightsClient separate.
@MainActor
public final class PeopleClient: ObservableObject {
    @Published public private(set) var dashboard: PeopleDashboard?
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?

    public init() {}

    private var url: URL { BackendHost.url(path: "/people/dashboard") }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            dashboard = try JSONDecoder().decode(PeopleDashboard.self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        isLoading = false
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

    private struct PersonUpdatePayload: Encodable {
        let email: String?
        let phone: String?
    }

    /// Backs People's inline-edit contact fields (2026-09-17, Editability
    /// Pass 1) -- id-based PATCH, not add_person's name-matched upsert,
    /// since the UI already has the exact row from a prior fetch. Refetches
    /// on success rather than reconstructing `dashboard` locally, same
    /// fire-and-refetch shape as every other write client in this app.
    public func updatePerson(id: Int, email: String? = nil, phone: String? = nil) async {
        var request = URLRequest(url: BackendHost.url(path: "/people/\(id)"))
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(PersonUpdatePayload(email: email, phone: phone))
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    private struct PersonCreatePayload: Encodable {
        let name: String
        let relationshipType: String?
        let company: String?
        let email: String?
        let phone: String?

        enum CodingKeys: String, CodingKey {
            case name
            case relationshipType = "relationship_type"
            case company, email, phone
        }
    }

    /// Backs People's new "+Add" form (2026-09-17, Editability Pass 1) --
    /// POST /people wraps the same add_person upsert Frank's own
    /// add_person tool already uses, so adding a person with an existing
    /// name here correctly updates that person rather than duplicating.
    public func addPerson(
        name: String, relationshipType: String? = nil, company: String? = nil,
        email: String? = nil, phone: String? = nil
    ) async {
        var request = URLRequest(url: BackendHost.url(path: "/people"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(
            PersonCreatePayload(name: name, relationshipType: relationshipType, company: company, email: email, phone: phone)
        )
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }
}
