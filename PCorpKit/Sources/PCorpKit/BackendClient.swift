import Foundation
#if canImport(UIKit)
import UIKit
public typealias PlatformImage = UIImage
#else
import AppKit
public typealias PlatformImage = NSImage
#endif

/// What kind of file an attachment is -- derived from media type/filename,
/// never sent by the client as its own field (see WireAttachment below):
/// one place this mapping can exist, not two drifting copies.
public enum AttachmentKind: String {
    case image, pdf, docx, xlsx, csv, other

    public static func from(mediaType: String, filename: String) -> AttachmentKind {
        if mediaType.hasPrefix("image/") { return .image }
        if mediaType == "application/pdf" { return .pdf }
        switch (filename as NSString).pathExtension.lowercased() {
        case "docx": return .docx
        case "xlsx": return .xlsx
        case "csv": return .csv
        default: return .other
        }
    }

    /// SF Symbol shown in place of a thumbnail for any non-image kind, in
    /// both the pre-send chip strip and the in-bubble attachment display.
    public var symbolName: String {
        switch self {
        case .image: return "photo"
        case .pdf: return "doc.richtext.fill"
        case .docx: return "doc.text.fill"
        case .xlsx: return "tablecells.fill"
        case .csv: return "tablecells"
        case .other: return "doc.fill"
        }
    }
}

/// Staged in the composer before send -- generalizes the old single
/// (Data?, mediaType?) pair (2026-08-05, image-only) to N attachments of
/// any kind (2026-09-05). `thumbnail` is non-nil only for `.image` --
/// decoded once at staging time, not re-decoded on every re-render (same
/// perf reasoning as ChatMessage's own real 2026-08-10 fix below).
public struct PendingAttachment: Identifiable {
    public let id = UUID()
    public let data: Data
    public let mediaType: String
    public let filename: String
    public let thumbnail: PlatformImage?

    public init(data: Data, mediaType: String, filename: String, thumbnail: PlatformImage? = nil) {
        self.data = data
        self.mediaType = mediaType
        self.filename = filename
        self.thumbnail = thumbnail
    }

    public var kind: AttachmentKind { .from(mediaType: mediaType, filename: filename) }
}

/// One attachment on an already-sent message, this session -- a real
/// thumbnail for an image, an SF Symbol placeholder for everything else.
public struct SentAttachment: Identifiable {
    public let id = UUID()
    public let kind: AttachmentKind
    public let filename: String
    public let thumbnail: PlatformImage?

    public init(kind: AttachmentKind, filename: String, thumbnail: PlatformImage? = nil) {
        self.kind = kind
        self.filename = filename
        self.thumbnail = thumbnail
    }
}

/// A single turn in the conversation — user or assistant. Mirrors
/// backend/app/db.py's `messages` table. Conversations can now start fresh
/// (startNewConversation below) — durable memory, not the transcript, is
/// what carries "there is only ever one Frank" forward. See app/db.py.
public struct ChatMessage: Identifiable {
    public let id = UUID()
    public let role: String
    public var content: String
    /// Real attachments for a message sent this live session -- rendered
    /// with actual thumbnails/content. Generalized 2026-09-05 from the
    /// old single `image: PlatformImage?` (real bug found and fixed
    /// 2026-08-10: decoding a raw Data image fresh in the view body re-ran
    /// on every re-render during streaming and visibly froze the chat --
    /// decoding once at send time, carried here, is what that fix
    /// depends on, still true for every attachment now, not just images).
    public var attachments: [SentAttachment] = []
    /// Placeholder names for a message loaded from a *reopened* old
    /// conversation (see GET /history) -- bytes aren't re-fetched, only
    /// the original filenames are shown, same confirmed decision
    /// 2026-08-05 (cost of re-sending an old attachment as real context on
    /// every reconnect vs. just knowing one was attached), now covering
    /// every attachment kind rather than only images.
    public var storedAttachmentNames: [String] = []

    public init(
        role: String,
        content: String,
        attachments: [SentAttachment] = [],
        storedAttachmentNames: [String] = []
    ) {
        self.role = role
        self.content = content
        self.attachments = attachments
        self.storedAttachmentNames = storedAttachmentNames
    }
}

/// Which of the three approval flows a pending ApprovalRequest belongs to
/// -- see ApprovalRequest's own doc comment for why this is now one
/// generalized type instead of three parallel ones.
public enum ApprovalKind {
    case fileEdit
    case calendarChange
    case automationRule
    case alphaModeChange
}

/// A pending approval of any kind, sent by the backend via one of four
/// sentinels: "\n[approval_request]" (Engineering Agent file edits, see
/// engineering_agent.py's propose_file_edit), "\n[calendar_approval_request]"
/// (calendar_tools.py's propose_*_calendar_event, added 2026-08-30),
/// "\n[automation_approval_request]" (automation_tools.py's
/// propose_create_automation, added 2026-09-06), or
/// "\n[alpha_mode_approval_request]" (alpha_mode_tools.py's real-Supabase
/// writes, added 2026-09-06 in the same systems-audit §19 sweep that
/// gated them). Generalized from three separate structs/pending-slots/
/// response-methods into this one type on the third occurrence -- exactly
/// the point calendar_tools.py's own comment named as when to stop
/// copy-pasting a new pair ("wait for a third occurrence, same rule of
/// three already applied on the backend"); the fourth (.alphaModeChange)
/// slots straight into the same shape, reusing the already-generic
/// title/details fields .calendarChange established rather than adding
/// two more optional properties for one more kind.
/// `kind` is set by listen() based on which sentinel matched, not decoded
/// from JSON -- the three backend payload shapes are unchanged and still
/// don't share a discriminator field, so this needed zero backend
/// changes for the two pre-existing flows. Only the fields relevant to
/// `kind` are ever non-nil; Joshua approving/rejecting always only needs
/// `id`, round-tripped verbatim in respondToApproval so the backend can
/// match the answer to the right pending request regardless of kind.
public struct ApprovalRequest: Identifiable {
    public let id: String
    public let tool: String
    public let kind: ApprovalKind
    // .fileEdit
    public let path: String?
    public let summary: String?
    public let diff: String?
    // .calendarChange (start/end are nil for a proposed cancellation)
    public let title: String?
    public let details: String?
    public let start: String?
    public let end: String?
    // .automationRule
    public let name: String?
    public let description: String?
    public let triggerTool: String?
    public let agent: String?
    public let instruction: String?
}

/// The connection from the shell to the Python backend, and the owner of
/// the live conversation state — real Claude reasoning streamed back
/// token-by-token (see backend/app/main.py), using native
/// `URLSessionWebSocketTask` (no third-party WebSocket library needed).
/// Loads prior history once on connect (GET /history) so relaunching the
/// app continues the same conversation instead of starting blank, matching
/// the backend's own "one continuous conversation" persistence.
@MainActor
public final class BackendClient: ObservableObject {
    @Published public private(set) var messages: [ChatMessage] = []
    @Published public private(set) var isConnected: Bool = false
    @Published public private(set) var isStreaming: Bool = false
    /// Non-nil while ANY of the three approval flows (file edit, calendar
    /// change, automation-rule creation) is blocked waiting on Josh's
    /// decision -- one shared slot since 2026-09-06 (see ApprovalRequest's
    /// own doc comment), never more than one at a time in practice (a
    /// turn calls one tool at a time). The UI shows an approval card and
    /// disables normal chat input while this is set. Cleared by
    /// respondToApproval() or on disconnect.
    @Published public private(set) var pendingApproval: ApprovalRequest? = nil
    /// The friendly label from the backend's most recent "\n[tool_start]"
    /// sentinel (see backend/app/tool_labels.py) -- non-nil for as long as
    /// Frank is mid-tool-call and no new text has arrived yet. Cleared the
    /// instant real text (or an error string, which arrives through the
    /// same plain-text branch -- see listen()'s final `else`) lands, or on
    /// "\n[done]"/disconnect/a manual stop/a fresh send(). No "[tool_end]"
    /// sentinel exists or is needed -- a thrown backend exception sends
    /// "\n[backend error: ...]" instead, which has no recognized prefix
    /// and falls into that same plain-text branch, so this still resolves
    /// correctly with no dedicated error path.
    @Published public private(set) var runningTool: String? = nil

    public init() {}

    private var session: URLSession?
    private var task: URLSessionWebSocketTask?
    /// Set right before a *deliberate* disconnect (disconnect() itself,
    /// called by switchToConversation/startNewConversation before their own
    /// explicit connect()) so listen()'s .failure handler can tell that
    /// apart from a connection that just died on its own -- see the
    /// self-healing reconnect added there 2026-09-04. Without this, an
    /// intentional disconnect's own cancellation would race the auto-heal
    /// logic into reopening a socket for the OLD conversation right as the
    /// caller was about to activate a new one, leaving connect()'s
    /// `guard task == nil` silently no-op and the app stuck talking to the
    /// wrong conversation.
    private var isIntentionalDisconnect = false
    /// Real bug found live (2026-09-04, "Frank always gives connection
    /// errors with every message" on iOS): a connection could go silently
    /// dead during a long background/lock period -- confirmed by Joshua's
    /// own report that only a full force-quit-and-relaunch fixed it, not
    /// backgrounding/foregrounding the still-running app, which pointed at
    /// something process-level (a stale pooled connection on the shared
    /// URLSession, or Tailscale's own network extension not yet having
    /// finished re-establishing its tunnel by the moment RootView's
    /// scenePhase-triggered connect() fired) rather than a one-off network
    /// blip. Counts consecutive unintentional reconnect attempts so the
    /// auto-heal below (which retries with a short backoff, giving
    /// Tailscale time to catch up) can't turn into a tight infinite loop if
    /// the phone is genuinely offline -- reset to 0 by any real success.
    private var consecutiveAutoReconnectFailures = 0
    private static let maxAutoReconnectAttempts = 4
    /// Bumped every time connect()/reopenSocket() stands up a new task.
    /// listen() closes over the value current at the moment it starts
    /// listening, and every branch inside its callback checks it's still
    /// current before touching `self.task`/`self.isConnected` -- guards
    /// against a real race in the fix above: URLSessionWebSocketTask's
    /// `.receive()` completion for an OLD, already-cancelled task can still
    /// fire *after* reopenSocket() has already installed and started
    /// listening on a brand-new one (cancellation delivers its failure
    /// asynchronously, not synchronously with cancel()). Without this, that
    /// stale callback's unconditional `self.task = nil` would silently undo
    /// the very reconnect this file exists to make reliable.
    private var connectionGeneration = 0

    /// A brand-new URLSession per connection attempt, not URLSession.shared
    /// -- part of the 2026-09-04 fix above. URLSession pools/reuses
    /// underlying connections across tasks by design; after this process
    /// sat backgrounded for hours, there's no way from here to prove the
    /// shared session's pooled state for this host was still healthy, and
    /// a fresh session costs nothing to create. The old session is
    /// explicitly invalidated (not just dropped) since an ad-hoc
    /// URLSession retains itself until told otherwise.
    private func openTask() -> URLSessionWebSocketTask {
        session?.invalidateAndCancel()
        let newSession = URLSession(configuration: .default)
        session = newSession
        let task = newSession.webSocketTask(with: wsURL)
        // Real bug found live (2026-09-05, multi-attach): Apple's own docs
        // for maximumMessageSize don't clearly state its default in a way
        // that was verifiable from here, and this app's own multi-
        // attachment messages can legitimately approach ~55MB once base64-
        // encoded (see main.py's WS_MAX_SIZE comment for the exact math) --
        // rather than trust an unverified implicit default, set this
        // explicitly to match the server's own configured ceiling, so
        // neither side is the unexpected bottleneck.
        task.maximumMessageSize = 64 * 1024 * 1024
        return task
    }

    /// True once this process has already started its one fresh
    /// conversation for this launch (see connect()). A `static var`, not
    /// an instance property, deliberately — WarRoomView (and this class
    /// with it) gets torn down and recreated every time you navigate to a
    /// different sidebar section and back (ContentView forces this via
    /// `.id(selectedItem.id)`), so an instance property would re-trigger
    /// "start fresh" on every nav click, not just app launch. Confirmed
    /// decision (2026-07-28): a brand-new conversation starts once per
    /// app launch; clicking to Settings/Calendar/etc. and back to War
    /// Room within the same running session keeps whatever's active, it
    /// doesn't get wiped. Old conversations don't need to "just sit
    /// there" anymore either way — the conversation history browser
    /// (search + date grouping) already makes any of them reachable.
    private static var hasStartedFreshThisLaunch = false

    /// Host comes from BackendHost.host (2026-08-12) -- "127.0.0.1" by
    /// default (desktop: same Mac as the backend, unreachable over the
    /// network by design), settable by the iOS app to this Mac's
    /// Tailscale IP. Token appended fresh at connect time (see
    /// AuthToken.swift) — the backend rejects any connection without it
    /// (SECURITY.md's local-auth fix).
    private var wsURL: URL {
        var components = URLComponents(string: "ws://\(BackendHost.host):8731/ws")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    private var historyURL: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/history")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    private var newConversationURL: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/conversations")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    private func conversationListURL(query: String?) -> URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/conversations")!
        var items = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        if let query, !query.isEmpty {
            items.append(URLQueryItem(name: "q", value: query))
        }
        components.queryItems = items
        return components.url!
    }

    private func activateURL(_ conversationID: Int) -> URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/conversations/\(conversationID)/activate")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    /// Starts a fresh conversation on the backend, then reconnects so the
    /// live WebSocket picks it up (a connection is bound to whichever
    /// conversation was active at connect time — see backend/app/main.py).
    /// Memory (SECURITY.md-classified "regular" tool, app/memory.py) is
    /// untouched by this; only the transcript resets.
    public func startNewConversation() async {
        messages = []
        var request = URLRequest(url: newConversationURL)
        request.httpMethod = "POST"
        _ = try? await URLSession.shared.data(for: request)
        disconnect()
        connect()
    }

    /// Every past conversation, most-recently-active first, for the
    /// history browser. `query`, when non-nil/non-empty, searches real
    /// message content (backend/app/db.py's list_conversations), not just
    /// each conversation's preview — indefinite history only stays useful
    /// if you can actually find something in it later.
    /// Throws on a real fetch/decode failure rather than returning `[]` --
    /// real gap found live (2026-09-06, systems audit §18 sweep): a
    /// failed request and a genuinely empty history both read as
    /// "No conversations yet" to the caller with no way to tell them
    /// apart. Callers should catch and show a real "couldn't load"
    /// state instead of trusting an empty array as a true empty history.
    public func fetchConversationList(query: String? = nil) async throws -> [ConversationSummary] {
        let (data, _) = try await URLSession.shared.data(from: conversationListURL(query: query))
        return try JSONDecoder().decode([ConversationSummary].self, from: data)
    }

    /// Reopens an older conversation — makes it active, then reconnects
    /// (same reasoning as startNewConversation: the live WebSocket needs a
    /// fresh connection to pick up whichever conversation is now active).
    public func switchToConversation(_ conversationID: Int) async {
        messages = []
        var request = URLRequest(url: activateURL(conversationID))
        request.httpMethod = "POST"
        _ = try? await URLSession.shared.data(for: request)
        disconnect()
        connect()
    }

    public func connect() {
        guard task == nil else { return }
        consecutiveAutoReconnectFailures = 0
        // Real bug found live (2026-09-05): isIntentionalDisconnect used to
        // only ever get reset back to false inside listen()'s own failure
        // handler -- but that handler bails out immediately, via the
        // connectionGeneration guard, whenever it's handling a *stale*
        // callback for an already-superseded task. Every normal reconnect
        // cycle (the phone locking, switching conversations, anything that
        // calls disconnect() then connect()/reopenSocket() right after) has
        // a real chance of the OLD task's failure notification arriving
        // after the new generation is already active, meaning that reset
        // line never runs. Once that race hits even once, this flag gets
        // stuck at true permanently -- and every future *genuine* failure,
        // for a task with no relation to that old disconnect() call at
        // all, gets misread as "this one was intentional," silently
        // skipping the self-healing reconnect below for the rest of the
        // process's life. Confirmed live: reproduced as "Frank fails on
        // every single message, fixed only by a full force-quit-and-
        // relaunch" -- exactly what a permanently-disabled self-heal would
        // look like. Resetting here, at the start of every new connection
        // attempt, is safe regardless of whether the old task's failure
        // ever actually fires: if it does, connectionGeneration has
        // already changed by the time it does, so that callback's own
        // guard bails before ever reading this flag anyway -- it never
        // depends on what value this holds at that point.
        isIntentionalDisconnect = false
        connectionGeneration += 1
        let task = openTask()
        self.task = task
        task.resume()
        isConnected = true
        listen()

        if Self.hasStartedFreshThisLaunch {
            Task { await loadHistory() }
        } else {
            Self.hasStartedFreshThisLaunch = true
            Task { await startFreshConversationForLaunch() }
        }
    }

    /// Creates a new conversation and makes it active — the same backend
    /// call startNewConversation() makes, but skipped-down for use during
    /// connect() itself: no need to clear `messages` (already empty on a
    /// fresh instance) or disconnect/reconnect (there's no live
    /// connection yet to restart), and no loadHistory() call since the
    /// new conversation is guaranteed to have none.
    private func startFreshConversationForLaunch() async {
        var request = URLRequest(url: newConversationURL)
        request.httpMethod = "POST"
        _ = try? await URLSession.shared.data(for: request)
    }

    public func disconnect() {
        isIntentionalDisconnect = true
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        isConnected = false
    }

    /// Interrupts the current reply, similar to Claude's own stop button.
    /// Closes the live socket (the backend's in-flight `send_text` calls
    /// start failing the instant it does, which unwinds `run_claude_turn`
    /// on the server side) and opens a fresh one for the next message --
    /// deliberately NOT calling loadHistory() as part of that reconnect,
    /// since the interrupted turn was never persisted server-side and a
    /// reload would silently erase the partial reply still visible in
    /// `messages`, which is exactly what should stay on screen.
    public func stopGenerating() {
        isStreaming = false
        runningTool = nil
        reopenSocket()
    }

    /// Shared by stopGenerating() and send()'s reconnect-on-send fallback
    /// below -- deliberately NOT loadHistory()/startFreshConversationForLaunch(),
    /// same reasoning as stopGenerating()'s own original comment: this fires
    /// mid-session, not at app launch, so reloading would either erase an
    /// in-flight partial reply (stopGenerating's case) or race the optimistic
    /// user-message append send() is about to do (its case) against an async
    /// history fetch that doesn't know about it yet.
    private func reopenSocket() {
        task?.cancel(with: .goingAway, reason: nil)
        // See connect()'s own comment on this same reset -- the identical
        // stuck-flag race applies here too, since this is the other place
        // a new connection generation begins.
        isIntentionalDisconnect = false
        connectionGeneration += 1
        let newTask = openTask()
        task = newTask
        newTask.resume()
        isConnected = true
        listen()
    }

    /// `attachments` generalizes the old single (imageData, mediaType) pair
    /// (2026-08-05, image-only) to N attachments of any kind (2026-09-05) --
    /// see PendingAttachment. Always an array, never optional, so both this
    /// function and the Python decode side (backend/app/main.py) index the
    /// same shape whether zero, one, or several files are attached.
    public func send(_ text: String, attachments: [PendingAttachment] = []) {
        // Real bug found live (2026-08-14): if the connection had silently
        // died since the last message -- backend restarted, network drop,
        // anything -- `task` was nil here and this whole function was a
        // total no-op: no message appended, no error, nothing. Exactly
        // matched a real report ("sent a message no response") with zero
        // visible symptom to debug from. `listen()`'s own `.failure` case
        // already nils `task` correctly; the actual gap was never trying
        // to reconnect before giving up, on any platform -- this isn't
        // iOS-specific the way the scenePhase fix was, a Mac with a stale
        // connection open when its backend restarts hits the exact same
        // silent no-op.
        if task == nil {
            reopenSocket()
        }
        guard let task else { return }
        // Thumbnails already decoded once, at staging time (see
        // PendingAttachment.thumbnail's doc comment for the real bug this
        // avoids repeating) -- not re-decoded here or in the view body.
        let sentAttachments = attachments.map { attachment in
            SentAttachment(kind: attachment.kind, filename: attachment.filename, thumbnail: attachment.thumbnail)
        }
        messages.append(ChatMessage(role: "user", content: text, attachments: sentAttachments))
        messages.append(ChatMessage(role: "assistant", content: ""))
        isStreaming = true
        runningTool = nil

        let wireAttachments = attachments.map { attachment in
            WireAttachment(media_type: attachment.mediaType, filename: attachment.filename, data: attachment.data.base64EncodedString())
        }
        let payload = WirePayload(text: text, attachments: wireAttachments)
        guard let json = try? JSONEncoder().encode(payload), let jsonString = String(data: json, encoding: .utf8) else {
            appendToLastAssistantMessage("[connection error: couldn't encode message]")
            isStreaming = false
            return
        }

        // Captured now, checked inside the completion handler below -- see
        // that guard's own comment for the real, confirmed race this closes
        // (2026-09-05).
        let generation = connectionGeneration
        task.send(.string(jsonString)) { [weak self] error in
            if let error {
                Task { @MainActor in
                    guard let self else { return }
                    // Real bug found live (2026-09-05), a direct
                    // continuation of the previous night's connection-
                    // reliability fix: this completion handler had no
                    // staleness check at all, unlike listen()'s own
                    // .failure case (see connectionGeneration's doc
                    // comment). Confirmed live from Joshua's own screenshot
                    // -- two stacked error strings in one reply bubble,
                    // "...mid-reply" immediately followed by "...request
                    // timed out": the original task.send() call's
                    // completion was still pending on an old, already-dead
                    // task when listen()'s .receive() failed first, reset
                    // state, and self-healed into a brand-new task/
                    // generation -- then THIS handler finally fired late
                    // (a `send()` timeout can take far longer to surface
                    // than a `.receive()` failure does) and, with no
                    // staleness check, unconditionally nilled the fresh
                    // task right back out from under the very reconnect
                    // that was supposed to fix things, every single time.
                    guard generation == self.connectionGeneration else { return }
                    // Real bug found live (2026-08-30): a send() failure
                    // here left `task` and `isConnected` untouched, so a
                    // connection that's silently dead (common after a
                    // phone backgrounds/sleeps or switches networks --
                    // URLSessionWebSocketTask doesn't always notice this
                    // promptly via its own .receive() callback, which is
                    // what normally nils `task` on failure, see listen()'s
                    // .failure case) kept being reused on every subsequent
                    // send() -- the exact same broken task, failing the
                    // exact same way, forever, until the app was force-
                    // quit and relaunched. Tearing the task down here too
                    // means the next send() call's own `if task == nil`
                    // check (see above) correctly triggers a fresh
                    // reopenSocket() instead of retrying a dead one.
                    self.task = nil
                    self.isConnected = false
                    // Only report/self-heal if this is genuinely new news --
                    // if listen()'s .failure already fired for this same
                    // still-current generation (both directions of one
                    // connection dying around the same moment), it already
                    // appended its own error text and reset isStreaming;
                    // piling a second, redundant error string on top of
                    // that same reply bubble would be exactly the stacked-
                    // errors symptom this fix exists to remove.
                    guard self.isStreaming else { return }
                    self.isStreaming = false
                    self.runningTool = nil
                    self.appendToLastAssistantMessage(
                        "[connection error: \(error.localizedDescription) — retry your message, it should reconnect automatically]"
                    )
                    if self.consecutiveAutoReconnectFailures < Self.maxAutoReconnectAttempts {
                        self.consecutiveAutoReconnectFailures += 1
                        let delaySeconds = min(pow(2.0, Double(self.consecutiveAutoReconnectFailures - 1)), 8.0)
                        Task {
                            try? await Task.sleep(nanoseconds: UInt64(delaySeconds * 1_000_000_000))
                            await MainActor.run {
                                guard self.task == nil, !self.isIntentionalDisconnect else { return }
                                self.reopenSocket()
                            }
                        }
                    }
                }
            }
        }
    }

    /// Sends Joshua's decision on a pending approval (any of the three
    /// kinds -- see ApprovalRequest's own doc comment) back over this
    /// same live socket -- the backend's propose_* executor is blocked in
    /// a single `await websocket.receive_text()` call waiting for exactly
    /// this shape, regardless of which flow it came from (the backend
    /// matches purely by `id`, never by kind). Deliberately doesn't reuse
    /// send(_:attachments:) above, since that's coupled to starting a new
    /// chat turn (appends ChatMessages, sets isStreaming). Clears
    /// pendingApproval immediately so the UI can't double-send for the
    /// same request; a no-op if the socket already died while the card
    /// was showing. One method for all three kinds since 2026-09-06 --
    /// see ApprovalRequest's own doc comment for why.
    public func respondToApproval(approved: Bool) {
        guard let request = pendingApproval, let task else { return }
        pendingApproval = nil
        let response = ApprovalResponseWire(
            approval_response: ApprovalResponseInner(id: request.id, approved: approved)
        )
        guard let json = try? JSONEncoder().encode(response),
              let jsonString = String(data: json, encoding: .utf8) else { return }
        task.send(.string(jsonString)) { _ in }
    }

    private struct ApprovalResponseInner: Encodable { let id: String; let approved: Bool }
    private struct ApprovalResponseWire: Encodable { let approval_response: ApprovalResponseInner }

    /// Wire format for a sent chat turn (2026-08-05, image upload support;
    /// generalized 2026-09-05 to N attachments of any kind) -- was a bare
    /// string before; now a small JSON envelope so attachments can ride
    /// alongside the text. `attachments` is always present (empty array,
    /// not omitted/optional) so both this side and the Python decode side
    /// (backend/app/main.py) always index the same shape. `kind` is
    /// deliberately not sent -- see AttachmentKind.from's own doc comment,
    /// derived server-side only.
    private struct WireAttachment: Encodable { let media_type: String; let filename: String; let data: String }
    private struct WirePayload: Encodable { let text: String; let attachments: [WireAttachment] }

    private struct HistoryAttachmentEntry: Decodable {
        let filename: String
        let original_name: String
        let media_type: String
    }

    private struct HistoryEntry: Decodable {
        let role: String
        let content: String
        let image_path: String?
        let attachments: [HistoryAttachmentEntry]?
    }

    private func loadHistory() async {
        do {
            let (data, _) = try await URLSession.shared.data(from: historyURL)
            let entries = try JSONDecoder().decode([HistoryEntry].self, from: data)
            messages = entries.map { entry in
                // A row written after the 2026-09-05 migration carries real
                // attachments (each with its own original filename); an
                // older row only has image_path -- still shown, just with
                // no real filename to recover, same "placeholder, not a
                // re-fetch" reasoning as before.
                let storedNames: [String]
                if let attachments = entry.attachments, !attachments.isEmpty {
                    storedNames = attachments.map(\.original_name)
                } else if entry.image_path != nil {
                    storedNames = ["Image"]
                } else {
                    storedNames = []
                }
                return ChatMessage(role: entry.role, content: entry.content, storedAttachmentNames: storedNames)
            }
        } catch {
            // Not critical enough to surface a hard error on first load —
            // the thread just starts empty, same as before this existed.
        }
    }

    private func appendToLastAssistantMessage(_ text: String) {
        guard let lastIndex = messages.indices.last, messages[lastIndex].role == "assistant" else { return }
        messages[lastIndex].content += text
    }

    private struct NotificationPayload: Decodable { let title: String; let body: String }
    private struct ToolStartPayload: Decodable { let label: String }
    // One private wire-decode struct per sentinel, matching each backend
    // payload's exact shape unchanged -- ApprovalRequest itself is no
    // longer directly Decodable (it's a union of all three kinds' fields,
    // built by listen() below rather than decoded straight off the wire).
    private struct FileEditApprovalWire: Decodable { let id, tool, path, summary, diff: String }
    private struct CalendarApprovalWire: Decodable {
        let id, tool, title, details: String
        let start, end: String?
    }
    private struct AutomationApprovalWire: Decodable {
        let id, tool, name, description, trigger_tool, agent, instruction: String
    }
    private struct AlphaModeApprovalWire: Decodable { let id, tool, title, details: String }
    private static let notifyPrefix = "\n[notify]"
    private static let approvalRequestPrefix = "\n[approval_request]"
    private static let calendarApprovalRequestPrefix = "\n[calendar_approval_request]"
    private static let automationApprovalRequestPrefix = "\n[automation_approval_request]"
    private static let alphaModeApprovalRequestPrefix = "\n[alpha_mode_approval_request]"
    private static let toolStartPrefix = "\n[tool_start]"

    private func listen() {
        guard let task else { return }
        let generation = connectionGeneration
        task.receive { [weak self] result in
            guard let self else { return }
            Task { @MainActor in
                // Bail out silently if a newer connect()/reopenSocket() has
                // already superseded this one -- see connectionGeneration's
                // doc comment for the exact race this closes.
                guard generation == self.connectionGeneration else { return }
                switch result {
                case .success(let message):
                    if case .string(let text) = message {
                        // Two sentinels from the backend (backend/app/main.py),
                        // neither part of the visible reply: "\n[done]" marks
                        // end of turn, "\n[notify]{json}" is Frank pushing a
                        // real notification (currently: whenever save_memory
                        // fires) rather than chat text.
                        if text == "\n[done]" {
                            self.isStreaming = false
                            self.runningTool = nil
                        } else if text.hasPrefix(Self.notifyPrefix) {
                            let payloadText = String(text.dropFirst(Self.notifyPrefix.count))
                            if let data = payloadText.data(using: .utf8),
                               let payload = try? JSONDecoder().decode(NotificationPayload.self, from: data) {
                                SystemNotification.post(title: payload.title, body: payload.body)
                            }
                        } else if text.hasPrefix(Self.approvalRequestPrefix) {
                            let payloadText = String(text.dropFirst(Self.approvalRequestPrefix.count))
                            if let data = payloadText.data(using: .utf8),
                               let w = try? JSONDecoder().decode(FileEditApprovalWire.self, from: data) {
                                self.pendingApproval = ApprovalRequest(
                                    id: w.id, tool: w.tool, kind: .fileEdit,
                                    path: w.path, summary: w.summary, diff: w.diff,
                                    title: nil, details: nil, start: nil, end: nil,
                                    name: nil, description: nil, triggerTool: nil, agent: nil, instruction: nil
                                )
                            }
                        } else if text.hasPrefix(Self.calendarApprovalRequestPrefix) {
                            let payloadText = String(text.dropFirst(Self.calendarApprovalRequestPrefix.count))
                            if let data = payloadText.data(using: .utf8),
                               let w = try? JSONDecoder().decode(CalendarApprovalWire.self, from: data) {
                                self.pendingApproval = ApprovalRequest(
                                    id: w.id, tool: w.tool, kind: .calendarChange,
                                    path: nil, summary: nil, diff: nil,
                                    title: w.title, details: w.details, start: w.start, end: w.end,
                                    name: nil, description: nil, triggerTool: nil, agent: nil, instruction: nil
                                )
                            }
                        } else if text.hasPrefix(Self.automationApprovalRequestPrefix) {
                            let payloadText = String(text.dropFirst(Self.automationApprovalRequestPrefix.count))
                            if let data = payloadText.data(using: .utf8),
                               let w = try? JSONDecoder().decode(AutomationApprovalWire.self, from: data) {
                                self.pendingApproval = ApprovalRequest(
                                    id: w.id, tool: w.tool, kind: .automationRule,
                                    path: nil, summary: nil, diff: nil,
                                    title: nil, details: nil, start: nil, end: nil,
                                    name: w.name, description: w.description, triggerTool: w.trigger_tool,
                                    agent: w.agent, instruction: w.instruction
                                )
                            }
                        } else if text.hasPrefix(Self.alphaModeApprovalRequestPrefix) {
                            let payloadText = String(text.dropFirst(Self.alphaModeApprovalRequestPrefix.count))
                            if let data = payloadText.data(using: .utf8),
                               let w = try? JSONDecoder().decode(AlphaModeApprovalWire.self, from: data) {
                                self.pendingApproval = ApprovalRequest(
                                    id: w.id, tool: w.tool, kind: .alphaModeChange,
                                    path: nil, summary: nil, diff: nil,
                                    title: w.title, details: w.details, start: nil, end: nil,
                                    name: nil, description: nil, triggerTool: nil, agent: nil, instruction: nil
                                )
                            }
                        } else if text.hasPrefix(Self.toolStartPrefix) {
                            let payloadText = String(text.dropFirst(Self.toolStartPrefix.count))
                            if let data = payloadText.data(using: .utf8),
                               let payload = try? JSONDecoder().decode(ToolStartPayload.self, from: data) {
                                self.runningTool = payload.label
                            }
                        } else {
                            // Real text (or a "\n[backend error: ...]" string,
                            // which has no recognized prefix and lands here
                            // too) always means whatever tool was running has
                            // resolved -- clearing here needs no dedicated
                            // "[tool_end]" sentinel at all.
                            self.runningTool = nil
                            self.appendToLastAssistantMessage(text)
                        }
                    }
                    self.consecutiveAutoReconnectFailures = 0
                    self.listen() // keep listening for the next chunk
                case .failure:
                    // Real bug found live (2026-09-01): this path (the
                    // connection dying while waiting on .receive(), e.g. a
                    // backend restart mid-reply) left the in-progress
                    // assistant message exactly as empty as send()'s optimistic
                    // append (line ~288) had left it -- unlike send()'s own
                    // completion-handler failure branch above, which already
                    // appends a visible "[connection error...]" string, this
                    // one appended nothing. Two real, confirmed symptoms:
                    // silently blank reply bubble in the transcript, and for
                    // a voice-triggered turn specifically, WarRoomView's
                    // pendingVoiceReply handoff would call
                    // VoiceOutput.speak("") -- which correctly no-ops on
                    // empty text -- so voice input would visibly transcribe
                    // but Frank would never audibly reply, with no error
                    // surfaced anywhere. Only append when a turn was actually
                    // in flight -- this same .failure case also fires for an
                    // idle disconnect with no pending reply, and appending
                    // there would corrupt an unrelated, already-complete past
                    // message instead.
                    let wasStreaming = self.isStreaming
                    let wasIntentional = self.isIntentionalDisconnect
                    self.isIntentionalDisconnect = false
                    self.isConnected = false
                    self.isStreaming = false
                    self.pendingApproval = nil
                    self.runningTool = nil
                    self.task = nil
                    if wasStreaming {
                        self.appendToLastAssistantMessage(
                            "[connection error: lost connection to Frank mid-reply — retry your message, it should reconnect automatically]"
                        )
                    }
                    // Self-healing reconnect (2026-09-04): deliberately does
                    // NOT resend the in-flight message itself -- confirmed
                    // unsafe, since main.py's websocket_chat persists the
                    // user's text to the messages table and can already have
                    // executed a side-effecting tool call (send an email, log
                    // an invoice) before a mid-reply disconnect, and has no
                    // idempotency/dedup of any kind, so a blind auto-resend
                    // risks a duplicate transcript entry or a duplicated real
                    // action. What IS safe, and what actually fixes "Frank
                    // always errors on iOS" (root-caused to a connection that
                    // silently went bad during a long background/lock period,
                    // confirmed by the fact only a full force-quit-and-
                    // relaunch cleared it, not just foregrounding the still-
                    // running app): get a fresh socket standing by *before*
                    // Joshua ever retypes anything, so his own manual retry
                    // lands on an already-healthy connection on the first try
                    // instead of racing a dead one. Backs off and caps at
                    // maxAutoReconnectAttempts so a genuinely offline phone
                    // can't spin this into a tight battery-draining loop --
                    // an intentional disconnect() (switchToConversation/
                    // startNewConversation, which call connect() themselves
                    // right after) skips this entirely so it can't steal
                    // their `task == nil` check out from under them.
                    if !wasIntentional, self.consecutiveAutoReconnectFailures < Self.maxAutoReconnectAttempts {
                        self.consecutiveAutoReconnectFailures += 1
                        let delaySeconds = min(pow(2.0, Double(self.consecutiveAutoReconnectFailures - 1)), 8.0)
                        Task {
                            try? await Task.sleep(nanoseconds: UInt64(delaySeconds * 1_000_000_000))
                            await MainActor.run {
                                guard self.task == nil, !self.isIntentionalDisconnect else { return }
                                self.reopenSocket()
                            }
                        }
                    }
                }
            }
        }
    }
}
