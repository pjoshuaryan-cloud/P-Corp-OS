import Foundation

/// A shared, short-timeout URLSessionConfiguration for the app-launch path
/// (2026-09-07) -- real bug found live: every launch-time network call
/// (the WebSocket handshake and every REST fetch it races with) previously
/// inherited Foundation's default 60-second timeout, confirmed via grep
/// across this package and both platforms' iOS/desktop targets (zero uses
/// of `timeoutInterval`/`URLSessionConfiguration` anywhere). If Tailscale's
/// own route negotiation is even briefly slow right after a cold app
/// launch, nothing failed fast and retried -- it just sat, silently, for
/// up to a full minute, which is exactly what "very slow to start, then a
/// connection error" looks like from the outside. 10s is a ~6x
/// improvement over the default: generous enough for a genuinely slow but
/// working cellular/Tailscale path, short enough to fail fast and let the
/// existing exponential-backoff reconnect logic (BackendClient.swift) take
/// over quickly.
public enum BackendURLSession {
    public static let configuration: URLSessionConfiguration = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 10
        config.timeoutIntervalForResource = 10
        return config
    }()

    /// Safe to share across plain, short-lived REST calls -- unlike the
    /// WebSocket's own deliberate "brand-new URLSession per connection
    /// attempt" design (see BackendClient.swift's openTask(), which still
    /// creates a fresh instance from this same configuration rather than
    /// reusing this singleton, for reasons specific to a long-lived
    /// connection surviving background suspension).
    public static let shared = URLSession(configuration: configuration)
}
