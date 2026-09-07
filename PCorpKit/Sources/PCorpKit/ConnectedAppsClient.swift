import Foundation

/// Plain REST fetch for GET /connected-apps — same one-shot pattern as
/// InsightsClient/SituationRoomClient. Deliberately fetched from
/// Settings' own onAppear (SettingsView.swift), not a timed poll like
/// those two War Room cards — this only needs to be fresh when Josh
/// actually opens Settings to look at it, so there's no reason to pay
/// Supabase's live-check cost (backend/app/connected_apps.py's
/// _supabase_status) on a background timer nobody's watching.
@MainActor
public final class ConnectedAppsClient: ObservableObject {
    @Published public private(set) var apps: [ConnectedAppStatus] = []
    @Published public private(set) var isLoading = false

    public init() {}

    private var url: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/connected-apps")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    public func fetch() async {
        isLoading = true
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            apps = try JSONDecoder().decode([ConnectedAppStatus].self, from: data)
        } catch {
            apps = []
        }
        isLoading = false
    }
}
