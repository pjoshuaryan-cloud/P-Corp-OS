import SwiftUI
import PCorpKit

/// POST -- video post-production prep: drive detection, footage
/// ingestion with checksum verification, crash-safe resumability
/// (2026-09-25, Phase 1). Same "plain REST fetch + poll while active"
/// pattern as every other dashboard in this app; no live-push
/// infrastructure exists anywhere to plug into instead.
///
/// Job creation/start/cancel/delete are desktop-only by design: picking
/// a source drive needs a live listing only the Mac physically
/// connected to it can produce -- Josh is always at his Mac when he
/// plugs a card in, so there's no real "propose from the couch" step to
/// build here, unlike trade proposals. iOS's own PostView.swift is
/// read-only.
struct PostView: View {
    @StateObject private var client = PostClient()
    @Environment(\.appTheme) private var theme
    @EnvironmentObject private var toastCenter: ToastCenter

    @State private var isAddingShoot = false
    @State private var pollTask: Task<Void, Never>?
    @State private var mediaReport: MediaReport?
    @State private var mediaReportJobId: Int = 0
    @State private var mediaReportJobName: String = ""
    @State private var mediaReportFiles: [PostJobFile] = []
    @State private var proxyStatuses: [ProxyStatus]?
    @State private var proxyStatusJobName: String = ""
    @State private var planningJob: PostJob?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(theme.divider)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let error = client.errorMessage {
                        errorText(error)
                    }

                    Button(isAddingShoot ? "Cancel" : "+ New POST Job") {
                        isAddingShoot.toggle()
                        if isAddingShoot { Task { await client.fetchSources(); await client.fetchProfiles() } }
                    }
                    .buttonStyle(.bordered)

                    if isAddingShoot {
                        newShootForm
                    }

                    Divider().overlay(theme.divider).padding(.vertical, 4)

                    sectionLabel("JOBS")
                    if client.isLoading && client.jobs.isEmpty {
                        SkeletonList(count: 2)
                    } else if client.jobs.isEmpty {
                        Text("No POST jobs yet -- connect a drive and create one above.")
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                    } else {
                        VStack(alignment: .leading, spacing: 8) {
                            ForEach(client.jobs) { job in
                                PostJobRow(
                                    job: job,
                                    onStart: { Task { await client.startJob(id: job.id) } },
                                    onCancel: { Task { await client.cancelJob(id: job.id) } },
                                    onDelete: { Task { await client.deleteJob(id: job.id) } },
                                    onAnalyzeMedia: { Task { await client.analyzeMedia(jobId: job.id) } },
                                    onViewReport: {
                                        Task {
                                            mediaReport = await client.fetchMediaReport(jobId: job.id)
                                            mediaReportJobId = job.id
                                            mediaReportJobName = job.shootName
                                            mediaReportFiles = await client.fetchJobFiles(id: job.id)
                                        }
                                    },
                                    onFetchProxyRecommendations: { await client.fetchProxyRecommendations(jobId: job.id) },
                                    onGenerateProxies: { Task { await client.generateProxies(jobId: job.id) } },
                                    onViewProxyStatus: {
                                        Task {
                                            proxyStatuses = await client.fetchProxies(jobId: job.id)
                                            proxyStatusJobName = job.shootName
                                        }
                                    },
                                    onDetectHighlights: { Task { await client.detectHighlights(jobId: job.id) } },
                                    onPlanEdit: { planningJob = job }
                                )
                            }
                        }
                    }
                }
                .padding(16)
            }
        }
        .frame(width: 520, height: 680)
        // Plan Edit covers the job list (see PlanEditView for why it isn't a nested popover or sheet).
        .overlay {
            if let job = planningJob {
                PlanEditView(job: job, onBack: { planningJob = nil })
            }
        }
        .task {
            await client.fetch()
            startPollingIfNeeded()
        }
        .onDisappear { pollTask?.cancel() }
        .popover(isPresented: Binding(
            get: { mediaReport != nil },
            set: { if !$0 { mediaReport = nil } }
        )) {
            if let report = mediaReport {
                MediaReportView(report: report, shootName: mediaReportJobName, jobId: mediaReportJobId, files: mediaReportFiles, client: client)
            }
        }
        .popover(isPresented: Binding(
            get: { proxyStatuses != nil },
            set: { if !$0 { proxyStatuses = nil } }
        )) {
            if let statuses = proxyStatuses {
                ProxyStatusView(statuses: statuses, shootName: proxyStatusJobName)
            }
        }
    }

    private var header: some View {
        HStack {
            Text("POST")
                .font(PCorpFont.display(20))
                .foregroundStyle(theme.textPrimary)
            Spacer()
            RefreshIconButton { await client.fetch() }
        }
        .padding(16)
    }

    private func sectionLabel(_ text: String) -> some View {
        Text(text)
            .font(PCorpFont.label(10))
            .trackedLabel(1.1)
            .foregroundStyle(theme.textSecondary)
    }

    private func errorText(_ text: String) -> some View {
        Text(text)
            .font(PCorpFont.body(12))
            .foregroundStyle(theme.statusRisk)
    }

    /// Polls every 2-3s while any job is actively scanning/ingesting/
    /// verifying, matching the "no push infra, poll while active"
    /// decision from planning -- stops naturally once nothing needs it.
    private func startPollingIfNeeded() {
        pollTask?.cancel()
        pollTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 2_500_000_000)
                if Task.isCancelled { break }
                if client.jobs.contains(where: { $0.isActive }) {
                    for job in client.jobs where job.isActive {
                        _ = await client.pollJob(id: job.id)
                    }
                } else {
                    await client.refreshJobsQuietly()
                }
            }
        }
    }

    // MARK: - New Shoot form

    @State private var draftProfile = "joshx"
    @State private var draftShootName = ""
    @State private var draftClientName = ""
    @State private var draftSourcePath: String?
    // Optional narrowing of draftSourcePath (the whole drive) to one folder on it.
    @State private var draftSourceFolderPath: String?
    @State private var draftDestinationPath: String?
    @State private var draftDeliverableFormat = postDeliverableFormatOptions[0]
    @State private var draftResolution = postResolutionOptions[0]
    @State private var draftFrameRate = postFrameRateOptions[2]  // defaults to "25", easily changed per shoot

    /// Why Create Job is greyed out (the first thing still missing), or nil when the form is complete. The rule lives in PCorpKit so it can be tested.
    private var createJobBlocker: String? {
        PostFormRules.createJobBlocker(shootName: draftShootName, profile: draftProfile, clientName: draftClientName, sourcePath: draftSourcePath, destinationPath: draftDestinationPath)
    }
    private var canCreateJob: Bool { createJobBlocker == nil }

    @ViewBuilder
    private var newShootForm: some View {
        VStack(alignment: .leading, spacing: 8) {
            Picker("Profile", selection: $draftProfile) {
                ForEach(postProfileNames, id: \.self) { name in
                    Text(client.profiles[name]?.label ?? name.capitalized).tag(name)
                }
            }
            TextField("Shoot name", text: $draftShootName)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(12.5))
                .padding(10)
                .cardSurface(radius: 8)

            if draftProfile == "alpha_mode" {
                TextField("Client name (required for Alpha Mode)", text: $draftClientName)
                    .textFieldStyle(.plain)
                    .font(PCorpFont.body(12.5))
                    .padding(10)
                    .cardSurface(radius: 8)
            }

            volumePicker("Source drive", selection: $draftSourcePath)
            if let volumePath = draftSourcePath {
                sourceFolderRow(volumePath: volumePath)
            }
            volumePicker("Destination drive", selection: $draftDestinationPath, showFreeSpace: true)

            Picker("Deliverable format", selection: $draftDeliverableFormat) {
                ForEach(postDeliverableFormatOptions, id: \.self) { Text($0).tag($0) }
            }
            Picker("Resolution", selection: $draftResolution) {
                ForEach(postResolutionOptions, id: \.self) { Text($0.replacingOccurrences(of: "_", with: " ").uppercased()).tag($0) }
            }
            Picker("Frame rate", selection: $draftFrameRate) {
                ForEach(postFrameRateOptions, id: \.self) { Text($0).tag($0) }
            }

            AsyncButton(action: createShoot) {
                Text("Create Job")
            }
            .buttonStyle(.actionFilled)
            .disabled(!canCreateJob)
            if let reason = createJobBlocker {
                Text(reason).font(PCorpFont.body(10.5)).foregroundStyle(theme.statusHot)
            }

            Text("Nothing is copied until you tap Start on the created job -- original footage is never modified or deleted.")
                .font(PCorpFont.body(10.5))
                .foregroundStyle(theme.textTertiary)
        }
        .padding(12)
        .cardSurface(radius: 10)
        .onChange(of: draftSourcePath) { _, _ in draftSourceFolderPath = nil }
    }

    /// Without a chosen folder the job copies the ENTIRE source drive (right
    /// for a camera card, wrong for a big hard drive), so that state is
    /// spelled out rather than left implicit.
    @ViewBuilder
    private func sourceFolderRow(volumePath: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Text("Source folder")
                    .font(PCorpFont.body(12.5))
                    .foregroundStyle(theme.textPrimary)
                Spacer()
                if draftSourceFolderPath != nil {
                    Button("Use entire drive") { draftSourceFolderPath = nil }
                        .buttonStyle(.borderless)
                }
                Button(draftSourceFolderPath == nil ? "Choose Folder…" : "Change…") {
                    chooseSourceFolder(volumePath: volumePath)
                }
                .buttonStyle(.bordered)
            }
            if let folder = draftSourceFolderPath {
                Text("Copying only: \(folder.dropFirst(volumePath.count).trimmingCharacters(in: CharacterSet(charactersIn: "/")))")
                    .font(PCorpFont.body(10.5))
                    .foregroundStyle(theme.textSecondary)
            } else {
                Text("Copying the ENTIRE drive. Choose a folder to copy just that folder.")
                    .font(PCorpFont.body(10.5))
                    .foregroundStyle(theme.statusHot)
            }
        }
    }

    private func chooseSourceFolder(volumePath: String) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = URL(fileURLWithPath: volumePath)
        panel.prompt = "Choose Folder"
        panel.message = "Choose the one folder to copy for this job."
        guard panel.runModal() == .OK, let url = panel.url else { return }

        // Compare symlink-resolved paths, but store the path under the same
        // mount point the drive picker used so the two always agree.
        let root = URL(fileURLWithPath: volumePath).resolvingSymlinksInPath().path
        let chosen = url.resolvingSymlinksInPath().path
        if chosen == root {
            draftSourceFolderPath = nil
        } else if chosen.hasPrefix(root + "/") {
            let relative = String(chosen.dropFirst(root.count + 1))
            draftSourceFolderPath = URL(fileURLWithPath: volumePath).appendingPathComponent(relative).path
        } else {
            toastCenter.show("Choose a folder on the selected source drive", style: .warning)
        }
    }

    @ViewBuilder
    private func volumePicker(_ label: String, selection: Binding<String?>, showFreeSpace: Bool = false) -> some View {
        if client.isLoadingSources {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Scanning connected drives…").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
            }
        } else if client.sourceVolumes.isEmpty {
            Text("No external drives detected. Connect one and reopen this form.")
                .font(PCorpFont.body(11))
                .foregroundStyle(theme.textTertiary)
        } else {
            Picker(label, selection: selection) {
                Text("Select…").tag(String?.none)
                ForEach(client.sourceVolumes) { volume in
                    Text(volumeMenuLabel(volume, showFreeSpace: showFreeSpace)).tag(String?.some(volume.path))
                }
            }
        }
    }

    private func volumeMenuLabel(_ volume: SourceVolume, showFreeSpace: Bool) -> String {
        guard showFreeSpace, let free = volume.freeBytes else { return volume.name }
        return "\(volume.name) — \(ByteCountFormatter.string(fromByteCount: Int64(free), countStyle: .file)) free"
    }

    private func createShoot() async {
        guard let sourcePath = draftSourcePath, let destinationPath = draftDestinationPath else { return }
        let draft = PostJobDraft(
            profile: draftProfile, shootName: draftShootName, sourcePath: draftSourceFolderPath ?? sourcePath,
            destinationVolumePath: destinationPath,
            clientName: draftProfile == "alpha_mode" ? draftClientName : nil,
            sourceVolumeName: client.sourceVolumes.first(where: { $0.path == sourcePath })?.name,
            sourceVolumeUuid: client.sourceVolumes.first(where: { $0.path == sourcePath })?.uuid,
            deliverableFormat: draftDeliverableFormat, resolution: draftResolution, frameRate: draftFrameRate
        )
        if let jobId = await client.createJob(draft) {
            toastCenter.show("POST job created", style: .success)
            draftShootName = ""; draftClientName = ""; draftSourcePath = nil; draftSourceFolderPath = nil; draftDestinationPath = nil
            isAddingShoot = false
            _ = jobId
        }
    }
}

/// A single job's card: status pill, progress bar while active, and
/// context-appropriate actions (Start for a fresh/failed/cancelled job,
/// Cancel while active, Delete always available -- never touches copied
/// files on disk, matching POST's own file-safety principle).
private struct PostJobRow: View {
    let job: PostJob
    let onStart: () -> Void
    let onCancel: () -> Void
    let onDelete: () -> Void
    let onAnalyzeMedia: () -> Void
    let onViewReport: () -> Void
    let onFetchProxyRecommendations: () async -> [ProxyRecommendation]
    let onGenerateProxies: () -> Void
    let onViewProxyStatus: () -> Void
    let onDetectHighlights: () -> Void
    let onPlanEdit: () -> Void
    @Environment(\.appTheme) private var theme

    @State private var recommendedProxyCount: Int?

    private var statusColor: Color {
        switch job.status {
        case "ingested", "premiere_project_created", "complete": return theme.statusGood
        case "ingest_failed", "cancelled": return theme.statusRisk
        case "scanning", "ready", "ingesting", "verifying", "analyzing_media", "generating_proxies", "analyzing_color": return theme.statusHot
        default: return theme.textSecondary
        }
    }

    /// The statuses the start-to-ready picture covers; later steps (proxies, highlights, the Premiere project) keep their own lines.
    private static let pipelineStatuses: Set<String> = ["created", "scanning", "ready", "ingesting", "verifying", "analyzing_media", "ingested", "ingest_failed", "cancelled"]

    private var canStart: Bool { ["created", "ingest_failed", "cancelled"].contains(job.status) }
    private var canCancel: Bool { job.isActive }
    private var canAnalyzeMedia: Bool { job.status == "ingested" }
    private var canCheckForProxies: Bool { job.status == "ingested" && job.mediaAnalyzedAt != nil }
    private var canPlanEdit: Bool {
        (job.status == "ingested" || job.status == "premiere_project_created") && job.mediaAnalyzedAt != nil
    }
    /// The backend's reason for the shoot's state; if it sent none but the old rule says no, a general one, so a greyed button never goes unexplained.
    private var planEditBlocker: String? {
        if let reason = job.pipeline?.planEditBlocker { return reason }
        return canPlanEdit ? nil : "Plan Edit unlocks once the shoot is copied and analysed."
    }
    private var moreActions: [PostFormRules.MoreAction] {
        PostFormRules.moreActions(status: job.status, mediaAnalyzed: job.mediaAnalyzedAt != nil, proxiesGenerated: job.proxiesGeneratedAt != nil, recommendedProxyCount: recommendedProxyCount)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(job.shootName).font(PCorpFont.body(13, weight: .semibold)).foregroundStyle(theme.textPrimary)
                    Text(job.profile == "alpha_mode" ? "Alpha Mode" : "Joshx").font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
                }
                Spacer()
                Text(job.status.replacingOccurrences(of: "_", with: " ").uppercased())
                    .font(PCorpFont.label(9))
                    .foregroundStyle(statusColor)
            }

            if let pipeline = job.pipeline, Self.pipelineStatuses.contains(job.status) {
                // One picture of the whole start-to-ready run (read the drive, copy, check, analyse), computed by the backend so every screen says the same thing.
                PostPipelineView(pipeline: pipeline)
                if job.status == "ingested" {
                    let later = [job.proxiesGeneratedAt != nil ? "Proxies generated." : nil, job.highlightsGeneratedAt != nil ? "Highlights detected." : nil].compactMap { $0 }
                    if !later.isEmpty {
                        Text(later.joined(separator: " ")).font(PCorpFont.body(10.5)).foregroundStyle(theme.textSecondary)
                    }
                }
            } else if job.status == "analyzing_media" {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Analyzing media…").font(PCorpFont.body(10.5)).foregroundStyle(theme.textSecondary)
                }
            } else if job.status == "generating_proxies" {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Generating proxies…").font(PCorpFont.body(10.5)).foregroundStyle(theme.textSecondary)
                }
            } else if job.status == "analyzing_color" {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Detecting highlights…").font(PCorpFont.body(10.5)).foregroundStyle(theme.textSecondary)
                }
            } else if job.isActive && job.totalBytes > 0 {
                ProgressView(value: Double(job.bytesCopied), total: Double(job.totalBytes))
                    .tint(statusColor)
                Text("\(job.filesCopied)/\(job.totalFiles) files, \(formattedBytes(job.bytesCopied))/\(formattedBytes(job.totalBytes))"
                     + (job.estimatedRemainingSeconds.map { ", ~\(Int($0 / 60))m remaining" } ?? ""))
                    .font(PCorpFont.body(10.5))
                    .foregroundStyle(theme.textSecondary)
            } else if job.status == "ingested" {
                Text("\(job.filesCopied) file(s) copied and verified."
                     + (job.mediaAnalyzedAt != nil ? " Media analyzed." : "")
                     + (job.proxiesGeneratedAt != nil ? " Proxies generated." : "")
                     + (job.highlightsGeneratedAt != nil ? " Highlights detected." : ""))
                    .font(PCorpFont.body(10.5))
                    .foregroundStyle(theme.textSecondary)
                if let count = recommendedProxyCount, count > 0 {
                    Text("\(count) file(s) would benefit from proxies.")
                        .font(PCorpFont.body(10.5))
                        .foregroundStyle(theme.textSecondary)
                }
            } else if job.status == "premiere_project_created" {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Premiere project created.").font(PCorpFont.body(10.5)).foregroundStyle(theme.textSecondary)
                    if let path = job.premiereProjectPath {
                        Text(path).font(PCorpFont.body(9.5)).foregroundStyle(theme.textTertiary)
                    }
                }
            } else if let error = job.errorMessage {
                Text(error).font(PCorpFont.body(10.5)).foregroundStyle(theme.statusRisk)
            }

            HStack(spacing: 8) {
                if canStart {
                    Button(job.status == "created" ? "Start" : "Retry", action: onStart)
                        .buttonStyle(.bordered)
                }
                if canCancel {
                    Button("Cancel", action: onCancel)
                        .buttonStyle(.bordered)
                }
                if canAnalyzeMedia {
                    Button(job.mediaAnalyzedAt == nil ? "Analyze Media" : "Re-analyze", action: onAnalyzeMedia)
                        .buttonStyle(.bordered)
                }
                if job.mediaAnalyzedAt != nil {
                    Button("View Report", action: onViewReport)
                        .buttonStyle(.bordered)
                }
                // Proxies and highlight detection are rarely wanted (proxies aren't attached in Premiere by default), so they live under More.
                if !moreActions.isEmpty {
                    Menu {
                        ForEach(moreActions, id: \.self) { action in
                            switch action {
                            case .generateProxies:
                                Button((job.proxiesGeneratedAt == nil ? "Generate Proxies" : "Regenerate Proxies") + (recommendedProxyCount.map { " (\($0) would benefit)" } ?? ""), action: onGenerateProxies)
                            case .proxyStatus:
                                Button("Proxy Status", action: onViewProxyStatus)
                            case .detectHighlights:
                                Button(job.highlightsGeneratedAt == nil ? "Detect Highlights" : "Re-detect Highlights", action: onDetectHighlights)
                            }
                        }
                    } label: {
                        Text("More")
                    }
                    .menuStyle(.button)
                    .buttonStyle(.bordered)
                    .fixedSize()
                }
                // Always shown: a button that appears and disappears leaves you guessing. When it can't be pressed yet, the line below says what it is waiting for.
                Button("Plan Edit", action: onPlanEdit)
                    .buttonStyle(.bordered)
                    .disabled(planEditBlocker != nil)
                Button("Delete", role: .destructive, action: onDelete)
                    .buttonStyle(.bordered)
            }
            if let reason = planEditBlocker {
                Text(reason).font(PCorpFont.body(10.5)).foregroundStyle(theme.textSecondary)
            }
        }
        .padding(10)
        .cardSurface(radius: 8)
        // Refetches only when the job's own analysis/proxy state actually
        // changes (not on every 2.5s poll tick) -- id includes proxiesGeneratedAt
        // so a completed generation run clears/refreshes the "N would benefit"
        // count rather than showing a stale pre-generation figure.
        .task(id: "\(job.id)-\(job.status)-\(job.mediaAnalyzedAt ?? "")-\(job.proxiesGeneratedAt ?? "")") {
            recommendedProxyCount = canCheckForProxies ? await onFetchProxyRecommendations().count : nil
        }
    }

    private func formattedBytes(_ bytes: Int) -> String {
        ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)
    }
}

/// Phase 2 (2026-09-25) -- the media intelligence report. Deliberately
/// labeled as computed categorization throughout, never creative
/// judgment -- matches the spec's own "generate useful metadata and
/// suggestions, never decide the final edit" boundary.
private struct MediaReportView: View {
    let report: MediaReport
    let shootName: String
    let jobId: Int
    let files: [PostJobFile]
    let client: PostClient
    @Environment(\.appTheme) private var theme

    @State private var transcriptSheetFile: PostJobFile?
    @State private var smartSelectsSheetFile: PostJobFile?
    @State private var highlightsSheetFile: PostJobFile?
    @State private var visualAnalysisSheetFile: PostJobFile?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Media Report").font(PCorpFont.display(18)).foregroundStyle(theme.textPrimary)
                Text(shootName).font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)

                sectionLabel("OVERVIEW")
                Text("\(report.totalFiles) file(s) analyzed. "
                     + report.mediaTypeCounts.map { "\($1) \($0)" }.sorted().joined(separator: ", "))
                    .font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                Text("\(report.horizontalCount) horizontal, \(report.verticalCount) vertical")
                    .font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)

                if !report.cameras.isEmpty {
                    Divider().overlay(theme.divider)
                    sectionLabel("CAMERAS DETECTED")
                    Text("Best-effort, from whatever metadata each file's camera actually wrote -- not every camera tags this.")
                        .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                    ForEach(report.cameras) { camera in
                        Text("\(camera.make ?? "Unknown") \(camera.model ?? "") — \(camera.count) file(s)")
                            .font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                    }
                }

                if !report.resolutions.isEmpty {
                    Divider().overlay(theme.divider)
                    sectionLabel("RESOLUTIONS")
                    ForEach(report.resolutions) { res in
                        Text("\(res.width)×\(res.height) — \(res.count) file(s)")
                            .font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                    }
                }

                if !report.frameRates.isEmpty {
                    Divider().overlay(theme.divider)
                    sectionLabel("FRAME RATES")
                    ForEach(report.frameRates) { fr in
                        Text("\(fr.fps, specifier: "%.2f")fps — \(fr.count) file(s)")
                            .font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                    }
                }

                if !report.slowMotionFiles.isEmpty {
                    Divider().overlay(theme.divider)
                    sectionLabel("POTENTIAL SLOW MOTION")
                    ForEach(report.slowMotionFiles) { f in
                        Text("\(f.path) — \(f.frameRate.map { String(format: "%.0ffps", $0) } ?? "")")
                            .font(PCorpFont.body(11.5)).foregroundStyle(theme.textSecondary)
                    }
                }

                if !report.duplicateGroups.isEmpty {
                    Divider().overlay(theme.divider)
                    sectionLabel("POTENTIAL DUPLICATES")
                    Text("Exact byte-for-byte matches, from the checksums already computed during ingestion.")
                        .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                    ForEach(Array(report.duplicateGroups.enumerated()), id: \.offset) { _, group in
                        Text(group.joined(separator: "  ≈  "))
                            .font(PCorpFont.body(11.5)).foregroundStyle(theme.statusHot)
                    }
                }

                if !report.corruptFiles.isEmpty {
                    Divider().overlay(theme.divider)
                    sectionLabel("CORRUPT / UNREADABLE FILES")
                    ForEach(report.corruptFiles) { f in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(f.path).font(PCorpFont.body(11.5, weight: .semibold)).foregroundStyle(theme.statusRisk)
                            if let error = f.error {
                                Text(error).font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                            }
                        }
                    }
                }

                if !report.colorProfileCounts.isEmpty {
                    Divider().overlay(theme.divider)
                    sectionLabel("COLOR PROFILE")
                    Text("Log detection is a best-effort guess from camera metadata, not a read of the actual gamma curve -- most cameras don't reliably tag this.")
                        .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                    if report.mixedColorSpaces {
                        Text("This shoot mixes Log/HDR and standard footage -- these won't grade the same way straight out of the box.")
                            .font(PCorpFont.body(11)).foregroundStyle(theme.statusHot)
                    }
                    ForEach(report.colorProfileCounts.sorted(by: { $0.key < $1.key }), id: \.key) { profile, count in
                        Text("\(colorProfileLabel(profile)) — \(count) file(s)")
                            .font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                    }
                }

                if !report.flaggedExposureFiles.isEmpty {
                    Divider().overlay(theme.divider)
                    sectionLabel("EXPOSURE FLAGS")
                    Text("A rough signal from sampled frames, not every frame -- worth a quick look, not a verdict.")
                        .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                    ForEach(report.flaggedExposureFiles) { f in
                        Text("\(f.path) — \(f.flag)")
                            .font(PCorpFont.body(11.5)).foregroundStyle(theme.statusRisk)
                    }
                }

                if !report.flaggedColorCastFiles.isEmpty {
                    Divider().overlay(theme.divider)
                    sectionLabel("COLOR CAST FLAGS")
                    Text("A rough directional read from average color balance, never a measured color temperature.")
                        .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                    ForEach(report.flaggedColorCastFiles) { f in
                        Text("\(f.path) — \(f.flag)")
                            .font(PCorpFont.body(11.5)).foregroundStyle(theme.statusHot)
                    }
                }

                Divider().overlay(theme.divider)
                sectionLabel("DIALOGUE")
                Text("Transcribed by Premiere's own native transcription -- never generated or verified for accuracy by P Corp OS. \"Smart Selects\" are real, deterministic clean-sentence candidates, never a claim about which take is creatively best.")
                    .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                let dialogue = report.dialogueSummary
                Text("\(dialogue.filesWithTranscripts) transcribed, \(dialogue.filesPendingTranscription) pending"
                     + (dialogue.filesFlaggedProfanity > 0 ? ", \(dialogue.filesFlaggedProfanity) flagged for profanity" : "")
                     + (dialogue.filesFlaggedFillerWords > 0 ? ", \(dialogue.filesFlaggedFillerWords) flagged for filler words" : ""))
                    .font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                ForEach(files.filter { $0.status == "verified" }) { file in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(file.relativePath).font(PCorpFont.body(11.5)).foregroundStyle(theme.textSecondary)
                        HStack(spacing: 10) {
                            Button("Transcript") { transcriptSheetFile = file }
                                .buttonStyle(.plain).font(PCorpFont.body(10.5)).foregroundStyle(theme.statusHot)
                            Button("Smart Selects") { smartSelectsSheetFile = file }
                                .buttonStyle(.plain).font(PCorpFont.body(10.5)).foregroundStyle(theme.statusHot)
                        }
                    }
                }

                Divider().overlay(theme.divider)
                sectionLabel("HIGHLIGHTS")
                Text("A real, deterministic motion/audio signal for footage with no dialogue to anchor Smart Selects on -- never a claim about which moment is creatively best. Use \"Assemble Rough Cut\" in the Premiere plugin to place these on a sequence.")
                    .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                ForEach(files.filter { $0.status == "verified" }) { file in
                    Button(file.relativePath) { highlightsSheetFile = file }
                        .buttonStyle(.plain)
                        .font(PCorpFont.body(11.5))
                        .foregroundStyle(theme.statusHot)
                }

                Divider().overlay(theme.divider)
                sectionLabel("VISUAL ANALYSIS")
                Text("Claude's real, honest read of a handful of sampled frames per file -- never a full-motion or frame-by-frame analysis, and never a claim about which take is best. Costs a real API call per run, unlike every other report on this page.")
                    .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                ForEach(files.filter { $0.status == "verified" }) { file in
                    Button(file.relativePath) { visualAnalysisSheetFile = file }
                        .buttonStyle(.plain)
                        .font(PCorpFont.body(11.5))
                        .foregroundStyle(theme.statusHot)
                }
            }
            .padding(16)
        }
        .frame(width: 460, height: 560)
        .popover(item: $transcriptSheetFile) { file in
            TranscriptView(jobId: jobId, file: file, client: client)
        }
        .popover(item: $smartSelectsSheetFile) { file in
            SmartSelectsView(jobId: jobId, file: file, client: client)
        }
        .popover(item: $highlightsSheetFile) { file in
            HighlightsView(jobId: jobId, file: file, client: client)
        }
        .popover(item: $visualAnalysisSheetFile) { file in
            VisualAnalysisView(jobId: jobId, file: file, client: client)
        }
    }

    private func colorProfileLabel(_ profile: String) -> String {
        switch profile {
        case "hdr_hlg": return "HDR (HLG)"
        case "hdr_pq": return "HDR (PQ/HDR10)"
        case "log": return "Log (best-effort guess)"
        case "sdr": return "Standard (SDR)"
        default: return "Unknown"
        }
    }

    private func sectionLabel(_ text: String) -> some View {
        Text(text)
            .font(PCorpFont.label(10))
            .trackedLabel(1.1)
            .foregroundStyle(theme.textSecondary)
    }
}

/// Phase 4 (2026-09-26) -- per-file proxy generation status
/// (Queued/Processing/Complete/Failed), same card-list precedent as
/// MediaReportView's own flagged-file lists.
private struct ProxyStatusView: View {
    let statuses: [ProxyStatus]
    let shootName: String
    @Environment(\.appTheme) private var theme

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Text("Proxy Status").font(PCorpFont.display(18)).foregroundStyle(theme.textPrimary)
                Text(shootName).font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)

                if statuses.isEmpty {
                    Text("No proxies generated for this job.")
                        .font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                } else {
                    ForEach(statuses) { proxy in
                        VStack(alignment: .leading, spacing: 2) {
                            HStack {
                                Text(proxy.relativePath).font(PCorpFont.body(11.5, weight: .semibold)).foregroundStyle(theme.textPrimary)
                                Spacer()
                                Text(proxy.status.uppercased())
                                    .font(PCorpFont.label(9))
                                    .foregroundStyle(statusColor(for: proxy.status))
                            }
                            if let error = proxy.errorMessage {
                                Text(error).font(PCorpFont.body(10)).foregroundStyle(theme.statusRisk)
                            }
                        }
                        .padding(8)
                        .cardSurface(radius: 6)
                    }
                }
            }
            .padding(16)
        }
        .frame(width: 420, height: 480)
    }

    private func statusColor(for status: String) -> Color {
        switch status {
        case "complete": return theme.statusGood
        case "failed": return theme.statusRisk
        default: return theme.statusHot
        }
    }
}

/// Phase 6 (2026-09-27) -- a real, speaker-grouped transcript, fetched
/// on demand (never preloaded into the whole Media Report). Plain text
/// only, never a word-by-word timeline/caption-editing UI -- that's out
/// of this app's own scope. Transcribed entirely by Premiere's own
/// native, on-device engine; this view only displays what's already
/// stored, never generates or verifies it.
private struct TranscriptView: View {
    let jobId: Int
    let file: PostJobFile
    let client: PostClient
    @Environment(\.appTheme) private var theme

    @State private var transcript: Transcript?
    @State private var isLoading = true

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Text("Transcript").font(PCorpFont.display(18)).foregroundStyle(theme.textPrimary)
                Text(file.relativePath).font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)

                if isLoading {
                    ProgressView().controlSize(.small)
                } else if let transcript {
                    Text("\(transcript.wordCount ?? 0) word(s), \(transcript.speakerCount ?? 0) speaker(s)"
                         + (transcript.hasProfanity ? " -- contains profanity" : "")
                         + (transcript.hasFillerWords ? " -- contains filler words" : ""))
                        .font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
                    Divider().overlay(theme.divider)
                    Text(transcript.readableText)
                        .font(PCorpFont.body(12.5)).foregroundStyle(theme.textSecondary)
                } else {
                    Text("No transcript for this file yet -- use \"Transcribe Dialogue\" in the Premiere plugin once this file is imported into a project.")
                        .font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                }
            }
            .padding(16)
        }
        .frame(width: 460, height: 480)
        .task {
            transcript = await client.fetchTranscript(jobId: jobId, fileId: file.id)
            isLoading = false
        }
    }
}

/// Phase 8a (2026-09-27) -- real, deterministic candidate soundbites
/// (clean, complete sentences with no profanity/filler tags) derived
/// from an already-stored transcript. Display only -- real marker
/// creation in Premiere happens entirely in the plugin's own "Suggest
/// Smart Selects" button, never from this view.
private struct SmartSelectsView: View {
    let jobId: Int
    let file: PostJobFile
    let client: PostClient
    @Environment(\.appTheme) private var theme

    @State private var candidates: [SmartSelectCandidate] = []
    @State private var isLoading = true

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Text("Smart Select Candidates").font(PCorpFont.display(18)).foregroundStyle(theme.textPrimary)
                Text(file.relativePath).font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                Text("Real, deterministic clean-sentence candidates -- never a claim about which moment is creatively best. Use \"Suggest Smart Selects\" in the Premiere plugin to add these as real markers.")
                    .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)

                if isLoading {
                    ProgressView().controlSize(.small)
                } else if candidates.isEmpty {
                    Text("No candidates yet -- this file may not have a transcript, or has no clean, complete sentences long enough to qualify.")
                        .font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                } else {
                    ForEach(candidates) { candidate in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(String(format: "%.1fs (%.1fs long)", candidate.start, candidate.duration))
                                .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                            Text("\u{201C}\(candidate.text)\u{201D}")
                                .font(PCorpFont.body(12.5)).foregroundStyle(theme.textSecondary)
                        }
                        .padding(8)
                        .cardSurface(radius: 6)
                    }
                }
            }
            .padding(16)
        }
        .frame(width: 460, height: 480)
        .task {
            candidates = await client.fetchSmartSelects(jobId: jobId, fileId: file.id)
            isLoading = false
        }
    }
}

/// Phase 9 (2026-09-28) -- non-dialogue highlight candidates (real
/// motion/audio-energy signal, no LLM in the path), same card-list
/// precedent as SmartSelectsView. Real marker/rough-cut assembly
/// happens entirely in the Premiere plugin, never from this view.
private struct HighlightsView: View {
    let jobId: Int
    let file: PostJobFile
    let client: PostClient
    @Environment(\.appTheme) private var theme

    @State private var candidates: [HighlightCandidate] = []
    @State private var isLoading = true

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Text("Highlight Candidates").font(PCorpFont.display(18)).foregroundStyle(theme.textPrimary)
                Text(file.relativePath).font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                Text("Real, deterministic motion/audio-energy candidates -- never a claim about which moment is creatively best. Use \"Assemble Rough Cut\" in the Premiere plugin to place these on a sequence.")
                    .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)

                if isLoading {
                    ProgressView().controlSize(.small)
                } else if candidates.isEmpty {
                    Text("No candidates yet -- run \"Detect Highlights\" on this job first, or this file may not have any qualifying motion/audio peaks.")
                        .font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                } else {
                    ForEach(candidates) { candidate in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(String(format: "%.1fs (%.1fs long)", candidate.start, candidate.duration))
                                .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                            Text(candidate.source.capitalized)
                                .font(PCorpFont.body(12.5)).foregroundStyle(theme.textSecondary)
                        }
                        .padding(8)
                        .cardSurface(radius: 6)
                    }
                }
            }
            .padding(16)
        }
        .frame(width: 460, height: 480)
        .task {
            candidates = await client.fetchHighlights(jobId: jobId, fileId: file.id)
            isLoading = false
        }
    }
}

/// Phase 8b (2026-09-27) -- real Claude vision judgment on sampled
/// frames. A genuine architectural shift from every other POST report
/// (which are all deterministic/local) -- this costs a real API call
/// per run, so "Analyze Frames" is a deliberate, explicit action, never
/// automatic and never Frank-reachable.
private struct VisualAnalysisView: View {
    let jobId: Int
    let file: PostJobFile
    let client: PostClient
    @Environment(\.appTheme) private var theme

    @State private var analysis: VisualAnalysis?
    @State private var isLoading = true
    @State private var isAnalyzing = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Text("Visual Analysis").font(PCorpFont.display(18)).foregroundStyle(theme.textPrimary)
                Text(file.relativePath).font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                Text("Claude's real, honest read of a handful of sampled frames -- not full-motion, not a claim about which take is best. Costs a real API call each time you run it.")
                    .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                if let error = client.errorMessage {
                    Text(error).font(PCorpFont.body(11)).foregroundStyle(theme.statusRisk)
                }

                if isLoading {
                    ProgressView().controlSize(.small)
                } else if let analysis {
                    Text("\(analysis.frameCount) frame(s) sampled.")
                        .font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
                    Divider().overlay(theme.divider)
                    Text(analysis.analysisText)
                        .font(PCorpFont.body(12.5)).foregroundStyle(theme.textSecondary)
                } else {
                    Text("No visual analysis for this file yet.")
                        .font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                }

                AsyncButton(action: runAnalysis) {
                    Text(analysis == nil ? "Analyze Frames" : "Re-analyze Frames")
                }
                .buttonStyle(.actionFilled)
                .disabled(isAnalyzing)
            }
            .padding(16)
        }
        .frame(width: 460, height: 480)
        .task {
            analysis = await client.fetchVisualAnalysis(jobId: jobId, fileId: file.id)
            isLoading = false
        }
    }

    private func runAnalysis() async {
        isAnalyzing = true
        if let result = await client.analyzeFrames(jobId: jobId, fileId: file.id) {
            analysis = result
        }
        isAnalyzing = false
    }
}


/// The shoot's whole run in one place (2026-10-20): four stages, one bar, one plain sentence. Replaces the separate status lines for copy, check and analyse, so
/// "is it done yet?" has one answer on the card.
private struct PostPipelineView: View {
    let pipeline: PostPipeline
    @Environment(\.appTheme) private var theme

    private var barColor: Color {
        if pipeline.needsAttention { return theme.statusRisk }
        return pipeline.percent >= 100 ? theme.statusGood : theme.statusHot
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 10) {
                ForEach(pipeline.stages) { stage in
                    HStack(spacing: 4) {
                        icon(for: stage)
                        Text(stage.label)
                            .font(PCorpFont.body(10, weight: stage.state == "active" ? .semibold : .regular))
                            .foregroundStyle(stage.state == "pending" ? theme.textTertiary : (stage.state == "failed" ? theme.statusRisk : theme.textSecondary))
                    }
                }
            }
            ProgressView(value: Double(max(0, min(pipeline.percent, 100))), total: 100).tint(barColor)
            Text(pipeline.headline)
                .font(PCorpFont.body(10.5))
                .foregroundStyle(pipeline.needsAttention ? theme.statusRisk : theme.textSecondary)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(pipeline.percent) percent. \(pipeline.headline)")
    }

    @ViewBuilder
    private func icon(for stage: PostPipelineStage) -> some View {
        switch stage.state {
        case "done": Image(systemName: "checkmark.circle.fill").font(.system(size: 10)).foregroundStyle(theme.statusGood)
        case "active": ProgressView().controlSize(.mini)
        case "failed": Image(systemName: "xmark.circle.fill").font(.system(size: 10)).foregroundStyle(theme.statusRisk)
        default: Image(systemName: "circle").font(.system(size: 10)).foregroundStyle(theme.textTertiary)
        }
    }
}
