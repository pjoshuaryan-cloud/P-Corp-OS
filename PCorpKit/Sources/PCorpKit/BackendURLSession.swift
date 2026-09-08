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
    /// attempt" design (see BackendClient.swift's openTask()), which uses
    /// webSocketConfiguration below, not this one.
    public static let shared = URLSession(configuration: configuration)

    /// Real bug found live (2026-09-08, "connection drops mid-reply, most
    /// days"): `openTask()` was built from `configuration` above, which
    /// sets `timeoutIntervalForResource = 10`. That property isn't an idle
    /// timeout -- per Apple's own docs it's a hard ceiling on a task's
    /// *total* lifetime from creation, active traffic or not. Applied to
    /// the long-lived chat WebSocket (as it accidentally was, once
    /// `608f66a` swapped `openTask()` from `.default` to the new shared
    /// `configuration` for the "fast-fail cold launch" fix), it meant
    /// URLSession itself killed the socket exactly 10 seconds after it
    /// opened, every single connection, regardless of whether Frank was
    /// mid-reply. Short replies finished under 10s and looked fine; any
    /// reply involving tool-use/agent delegation/web_search commonly runs
    /// longer than that and got its connection torn down mid-stream --
    /// exactly what surfaced as `listen()`'s "[connection error: lost
    /// connection to Frank mid-reply]", confirmed to correlate with how
    /// often a reply takes >10s, not with any real network condition.
    ///
    /// This configuration keeps the same fast-fail 10s
    /// `timeoutIntervalForRequest` for the initial handshake (still a real
    /// win against a slow Tailscale negotiation) but deliberately leaves
    /// `timeoutIntervalForResource` at its default (Foundation's own
    /// 7-day ceiling) -- long enough that no real chat turn will ever hit
    /// it, but still a hard backstop against a task that's truly wedged
    /// forever.
    public static let webSocketConfiguration: URLSessionConfiguration = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 10
        return config
    }()
}
