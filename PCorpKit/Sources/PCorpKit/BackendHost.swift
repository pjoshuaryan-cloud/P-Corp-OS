import Foundation

/// Every *Client.swift file builds its URLs off this instead of a
/// hardcoded "127.0.0.1" (2026-08-12, split out when the iOS companion
/// app needed a real host to talk to). Desktop leaves this at its
/// default -- same Mac as the backend, unreachable over the network by
/// design. iOS sets it to this Mac's Tailscale-assigned IP (the listener
/// backend/app/main.py's run() already adds when TAILSCALE_IP is set) --
/// never a public IP, matching SECURITY.md's threat model.
public enum BackendHost {
    public static var host: String = "127.0.0.1"
}
