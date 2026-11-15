import Foundation
import ImageIO
import SwiftUI
import UniformTypeIdentifiers
#if canImport(PhotosUI) && os(iOS)
import PhotosUI
#endif
#if os(macOS)
import AppKit
#else
import UIKit
#endif

// The simplified Trading tab (2026-11-15). Josh: "drop in screenshots of whatever I'm trading, and AI must be able to
// analyze the chart, tell me where good buy and sell areas are ... simplify it as much as possible. I don't want too many
// tabs and options." One screen, shared by the Mac and the iPhone: drop/paste/choose up to 4 screenshots, an optional note,
// Analyze, then a short fixed-layout answer (lean, buy area, sell area, wrong-if, targets, confidence) and follow-up
// questions. Broker context (Black Crown Markets, MT5, rand) is added on the backend (trade_intelligence_agent.BROKER_CONTEXT).
// Recent analyses are kept on this device only (ChartAnalysisStore). Everything the tab used to show is behind "More tools".

// MARK: - Screenshots

public struct ChartScreenshot: Identifiable, Equatable {
    public let id = UUID()
    public let data: Data
    public let mediaType: String

    /// Screenshots are scaled down to at most `maxPixels` on the long side and sent as JPEG: retina PNGs are often 3-8 MB,
    /// slow to upload from a phone and near the API's image limit, and the price scale stays readable at this size.
    public static let maxPixels = 2000

    public init?(imageData: Data) {
        guard let source = CGImageSourceCreateWithData(imageData as CFData, nil),
              CGImageSourceGetCount(source) > 0 else { return nil }
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceThumbnailMaxPixelSize: Self.maxPixels,
            kCGImageSourceCreateThumbnailWithTransform: true,
        ]
        guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary),
              let jpeg = Self.jpeg(image, quality: 0.88) else { return nil }
        self.data = jpeg
        self.mediaType = "image/jpeg"
    }

    static func jpeg(_ image: CGImage, quality: Double) -> Data? {
        let out = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(out, UTType.jpeg.identifier as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
        return CGImageDestinationFinalize(destination) ? out as Data : nil
    }

    /// A small JPEG for the recent-analyses list.
    static func thumbnail(of data: Data, maxPixels: Int = 240) -> Data? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        let options: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceThumbnailMaxPixelSize: maxPixels]
        guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { return nil }
        return jpeg(image, quality: 0.7)
    }
}

// MARK: - Recent analyses, kept on this device

public struct ChartAnalysisRecord: Codable, Identifiable, Equatable {
    public struct Line: Codable, Equatable { public let role: String; public let text: String }
    public let id: UUID
    public let date: Date
    public var note: String
    public var thumbnail: Data?
    public var lines: [Line]
    /// The conversation as the backend needs it for follow-ups (it includes the screenshots). Kept for the newest few only.
    public var serverHistory: Data?

    /// The "Lean:" line of the first answer, for the list.
    public var headline: String {
        let first = lines.first(where: { $0.role == "assistant" })?.text ?? ""
        if let lean = first.split(separator: "\n").first(where: { $0.lowercased().contains("lean:") }) {
            return lean.replacingOccurrences(of: "**", with: "").replacingOccurrences(of: "Lean:", with: "").trimmingCharacters(in: .whitespaces)
        }
        return String(first.prefix(80))
    }
}

/// The last `keep` analyses as one JSON file in Application Support. Only the newest `keepConversation` keep their full
/// conversation (screenshots included) for follow-ups; older ones can be read but not continued. Never throws: a store that
/// can't be read starts empty.
public final class ChartAnalysisStore {
    public static let keep = 20
    public static let keepConversation = 5
    let url: URL

    public init(url: URL? = nil) {
        if let url {
            self.url = url
        } else {
            let base = (try? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true))
                ?? FileManager.default.temporaryDirectory
            self.url = base.appendingPathComponent("PCorpOS", isDirectory: true).appendingPathComponent("chart_analyses.json")
        }
    }

    public func load() -> [ChartAnalysisRecord] {
        guard let data = try? Data(contentsOf: url),
              let records = try? JSONDecoder().decode([ChartAnalysisRecord].self, from: data) else { return [] }
        return records
    }

    public func save(_ records: [ChartAnalysisRecord]) {
        var trimmed = Array(records.sorted { $0.date > $1.date }.prefix(Self.keep))
        for i in trimmed.indices where i >= Self.keepConversation { trimmed[i].serverHistory = nil }
        guard let data = try? JSONEncoder().encode(trimmed) else { return }
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: url, options: .atomic)
    }
}

// MARK: - Talking to the backend

@MainActor
public final class ChartDeskClient: ObservableObject {
    @Published public private(set) var messages: [TradeIntelligenceMessage] = []
    @Published public private(set) var isWorking = false
    @Published public private(set) var errorMessage: String?
    @Published public private(set) var recent: [ChartAnalysisRecord] = []
    /// False when an older analysis was reopened without its conversation: it can be read, not continued.
    @Published public private(set) var canFollowUp = false

    private var serverHistory: [Any] = []
    private var currentID: UUID?
    private let store: ChartAnalysisStore
    private let post: (String, [String: Any]) async -> Result<[String: Any], ChartDeskError>

    public struct ChartDeskError: Error { public let message: String }

    public init(store: ChartAnalysisStore = ChartAnalysisStore(),
                post: ((String, [String: Any]) async -> Result<[String: Any], ChartDeskError>)? = nil) {
        self.store = store
        self.post = post ?? Self.postToBackend
        recent = store.load()
    }

    /// Analyses take real seconds (a vision model reading up to 4 charts), so the timeout is generous.
    static let timeout: TimeInterval = 120

    static func postToBackend(path: String, body: [String: Any]) async -> Result<[String: Any], ChartDeskError> {
        var request = URLRequest(url: BackendHost.url(path: path))
        request.httpMethod = "POST"
        request.timeoutInterval = timeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                return .failure(ChartDeskError(message: (json?["detail"] as? String) ?? "The analysis failed (\(http.statusCode))."))
            }
            guard let json else { return .failure(ChartDeskError(message: "Unexpected reply from the backend.")) }
            return .success(json)
        } catch {
            return .failure(ChartDeskError(message: "Couldn't reach the backend — check the connection and try again."))
        }
    }

    public func analyze(_ screenshots: [ChartScreenshot], note: String) async {
        guard !screenshots.isEmpty, !isWorking else { return }
        isWorking = true
        errorMessage = nil
        let trimmedNote = note.trimmingCharacters(in: .whitespacesAndNewlines)
        let body: [String: Any] = [
            "images": screenshots.enumerated().map { i, shot in
                ["media_type": shot.mediaType, "filename": "chart-\(i + 1).jpg", "data": shot.data.base64EncodedString()]
            },
            "note": trimmedNote,
        ]
        switch await post("/trade-intelligence/chart-zones", body) {
        case .success(let json):
            guard let reply = json["reply"] as? String, let history = json["history"] as? [Any] else {
                errorMessage = "Unexpected reply from the backend."
                break
            }
            serverHistory = history
            canFollowUp = true
            messages = [
                TradeIntelligenceMessage(role: "user", text: trimmedNote, imageDataList: screenshots.map(\.data)),
                TradeIntelligenceMessage(role: "assistant", text: reply),
            ]
            let record = ChartAnalysisRecord(
                id: UUID(), date: Date(), note: trimmedNote,
                thumbnail: screenshots.first.flatMap { ChartScreenshot.thumbnail(of: $0.data) },
                lines: [.init(role: "user", text: trimmedNote), .init(role: "assistant", text: reply)],
                serverHistory: try? JSONSerialization.data(withJSONObject: history))
            currentID = record.id
            recent.insert(record, at: 0)
            persist()
        case .failure(let error):
            errorMessage = error.message
        }
        isWorking = false
    }

    public func followUp(_ text: String) async {
        let question = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty, canFollowUp, !isWorking else { return }
        isWorking = true
        errorMessage = nil
        messages.append(TradeIntelligenceMessage(role: "user", text: question))
        switch await post("/trade-intelligence/chart-zones", ["history": serverHistory, "message": question]) {
        case .success(let json):
            guard let reply = json["reply"] as? String, let history = json["history"] as? [Any] else {
                errorMessage = "Unexpected reply from the backend."
                break
            }
            serverHistory = history
            messages.append(TradeIntelligenceMessage(role: "assistant", text: reply))
            if let id = currentID, let i = recent.firstIndex(where: { $0.id == id }) {
                recent[i].lines += [.init(role: "user", text: question), .init(role: "assistant", text: reply)]
                recent[i].serverHistory = try? JSONSerialization.data(withJSONObject: history)
                persist()
            }
        case .failure(let error):
            errorMessage = error.message
        }
        isWorking = false
    }

    /// Back to an empty screen for a new chart.
    public func startOver() {
        messages = []
        serverHistory = []
        currentID = nil
        canFollowUp = false
        errorMessage = nil
    }

    public func open(_ record: ChartAnalysisRecord) {
        currentID = record.id
        errorMessage = nil
        messages = record.lines.enumerated().map { i, line in
            TradeIntelligenceMessage(role: line.role, text: line.text,
                                     imageDataList: i == 0 ? (record.thumbnail.map { [$0] } ?? []) : [])
        }
        if let data = record.serverHistory, let history = (try? JSONSerialization.jsonObject(with: data)) as? [Any] {
            serverHistory = history
            canFollowUp = true
        } else {
            serverHistory = []
            canFollowUp = false
        }
    }

    public func delete(_ record: ChartAnalysisRecord) {
        recent.removeAll { $0.id == record.id }
        if currentID == record.id { startOver() }
        persist()
    }

    private func persist() {
        store.save(recent)
        recent = Array(recent.prefix(ChartAnalysisStore.keep))
        // Mirror the store's trimming so a reopened older analysis behaves the same now as after a relaunch.
        for i in recent.indices where i >= ChartAnalysisStore.keepConversation { recent[i].serverHistory = nil }
    }
}

// MARK: - The screen

public struct ChartDeskView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var desk = ChartDeskClient()
    @State private var screenshots: [ChartScreenshot] = []
    @State private var note = ""
    @State private var isDropTargeted = false
    @State private var intakeError: String?
    #if os(iOS)
    @State private var photoItems: [PhotosPickerItem] = []
    #endif
    let onMoreTools: () -> Void

    public init(onMoreTools: @escaping () -> Void) {
        self.onMoreTools = onMoreTools
    }

    public static let maxScreenshots = 4

    public var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(theme.divider)
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if desk.messages.isEmpty {
                        dropZone
                        if !screenshots.isEmpty { thumbnails }
                        TextField("Anything to add? (optional — e.g. \"thinking of a long\")", text: $note)
                            .textFieldStyle(.plain)
                            .font(PCorpFont.body(13))
                            .padding(10)
                            .cardSurface(radius: 8)
                        if let message = intakeError ?? desk.errorMessage {
                            Text(message).font(PCorpFont.body(12)).foregroundStyle(theme.statusRisk)
                        }
                        Button {
                            Task { await desk.analyze(screenshots, note: note) }
                        } label: {
                            HStack(spacing: 8) {
                                if desk.isWorking { ProgressView().controlSize(.small) }
                                Text(desk.isWorking ? "Reading the chart…" : "Find buy and sell areas")
                            }
                            .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.actionFilled)
                        .disabled(screenshots.isEmpty || desk.isWorking)
                    } else {
                        AdvisoryConversationThread(
                            messages: desk.messages, isSending: desk.isWorking, errorMessage: desk.errorMessage,
                            onSend: { text in Task { await desk.followUp(text) } },
                            onReset: { desk.startOver(); screenshots = []; note = "" })
                        if !desk.canFollowUp {
                            Text("This is an older analysis: you can read it, but follow-up questions only work on your 5 most recent.")
                                .font(PCorpFont.body(11)).foregroundStyle(theme.textTertiary)
                        }
                    }
                    Text("Analysis only — you decide and place every trade yourself.")
                        .font(PCorpFont.body(11))
                        .foregroundStyle(theme.textTertiary)
                    if !desk.recent.isEmpty { recentList }
                }
                .padding(24)
                .frame(maxWidth: 760, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        #if os(macOS)
        .onPasteCommand(of: [.image, .png, .tiff, .fileURL]) { providers in
            if desk.messages.isEmpty { load(providers) }
        }
        #endif
    }

    private var header: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Trading")
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text("Black Crown Markets · MT5 · rand account")
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            Button("More tools", action: onMoreTools)
                .buttonStyle(.bordered)
        }
        .padding(24)
    }

    private var dropZone: some View {
        VStack(spacing: 10) {
            Image(systemName: "chart.xyaxis.line")
                .font(.system(size: 30, weight: .light))
                .foregroundStyle(theme.textSecondary)
            #if os(macOS)
            Text("Drop chart screenshots here")
                .font(PCorpFont.body(15, weight: .semibold))
                .foregroundStyle(theme.textPrimary)
            Text("or paste (⌘V) · up to \(Self.maxScreenshots), e.g. different timeframes")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textTertiary)
            Button("Choose screenshots…", action: chooseFiles)
                .buttonStyle(.bordered)
                .disabled(screenshots.count >= Self.maxScreenshots)
            #else
            Text("Add chart screenshots")
                .font(PCorpFont.body(15, weight: .semibold))
                .foregroundStyle(theme.textPrimary)
            Text("Up to \(Self.maxScreenshots), e.g. different timeframes")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textTertiary)
            HStack(spacing: 10) {
                PhotosPicker(selection: $photoItems, maxSelectionCount: Self.maxScreenshots, matching: .images) {
                    Text("Photos")
                }
                .buttonStyle(.bordered)
                Button("Paste") { pasteFromClipboard() }
                    .buttonStyle(.bordered)
            }
            #endif
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 34)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .strokeBorder(isDropTargeted ? theme.accentFill : theme.divider, style: StrokeStyle(lineWidth: 1.5, dash: [6, 5]))
        )
        #if os(macOS)
        .onDrop(of: [.fileURL, .image], isTargeted: $isDropTargeted) { providers in
            load(providers)
            return true
        }
        #else
        .onChange(of: photoItems) { _, items in
            guard !items.isEmpty else { return }
            Task {
                for item in items {
                    if let data = try? await item.loadTransferable(type: Data.self) { add(data) }
                }
                photoItems = []
            }
        }
        #endif
    }

    private var thumbnails: some View {
        HStack(spacing: 8) {
            ForEach(screenshots) { shot in
                ZStack(alignment: .topTrailing) {
                    if let image = PlatformImage(data: shot.data) {
                        platformImage(image)
                            .resizable()
                            .scaledToFill()
                            .frame(width: 84, height: 64)
                            .clipShape(RoundedRectangle(cornerRadius: 6))
                    }
                    Button { screenshots.removeAll { $0.id == shot.id } } label: {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(theme.textPrimary)
                            .background(Circle().fill(theme.background))
                    }
                    .buttonStyle(.plain)
                    .offset(x: 5, y: -5)
                    .accessibilityLabel("Remove screenshot")
                }
            }
        }
    }

    private var recentList: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("RECENT")
                .font(PCorpFont.label())
                .trackedLabel()
                .foregroundStyle(theme.textTertiary)
                .padding(.top, 8)
            ForEach(desk.recent) { record in
                HStack(spacing: 10) {
                    Button { desk.open(record); screenshots = []; note = "" } label: {
                        HStack(spacing: 10) {
                            if let data = record.thumbnail, let image = PlatformImage(data: data) {
                                platformImage(image).resizable().scaledToFill()
                                    .frame(width: 48, height: 36).clipShape(RoundedRectangle(cornerRadius: 4))
                            }
                            VStack(alignment: .leading, spacing: 2) {
                                Text(record.headline.isEmpty ? "Chart analysis" : record.headline)
                                    .font(PCorpFont.body(12.5))
                                    .foregroundStyle(theme.textPrimary)
                                    .lineLimit(1)
                                Text(record.date.formatted(date: .abbreviated, time: .shortened) + (record.note.isEmpty ? "" : " · \(record.note)"))
                                    .font(PCorpFont.body(11))
                                    .foregroundStyle(theme.textTertiary)
                                    .lineLimit(1)
                            }
                            Spacer(minLength: 0)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    Button { desk.delete(record) } label: {
                        Image(systemName: "trash").foregroundStyle(theme.textTertiary)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Delete this analysis")
                }
                .padding(8)
                .cardSurface(radius: 8)
            }
        }
    }

    private func add(_ data: Data) {
        guard screenshots.count < Self.maxScreenshots else {
            intakeError = "Up to \(Self.maxScreenshots) screenshots at a time."
            return
        }
        guard let shot = ChartScreenshot(imageData: data) else {
            intakeError = "That file isn't an image I can read."
            return
        }
        intakeError = nil
        screenshots.append(shot)
    }

    #if os(macOS)
    private func chooseFiles() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.image]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        guard panel.runModal() == .OK else { return }
        for url in panel.urls { if let data = try? Data(contentsOf: url) { add(data) } }
    }

    private func load(_ providers: [NSItemProvider]) {
        for provider in providers {
            if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
                _ = provider.loadObject(ofClass: URL.self) { url, _ in
                    guard let url, let data = try? Data(contentsOf: url) else { return }
                    DispatchQueue.main.async { add(data) }
                }
            } else if provider.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
                provider.loadDataRepresentation(forTypeIdentifier: UTType.image.identifier) { data, _ in
                    guard let data else { return }
                    DispatchQueue.main.async { add(data) }
                }
            }
        }
    }
    #else
    private func pasteFromClipboard() {
        let images = UIPasteboard.general.images ?? []
        guard !images.isEmpty else {
            intakeError = "Nothing to paste — copy a screenshot first."
            return
        }
        for image in images { if let data = image.pngData() { add(data) } }
    }
    #endif
}
