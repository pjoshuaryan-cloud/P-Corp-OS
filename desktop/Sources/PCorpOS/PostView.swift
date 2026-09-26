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
    @State private var mediaReportJobName: String = ""
    @State private var proxyStatuses: [ProxyStatus]?
    @State private var proxyStatusJobName: String = ""

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
                                            mediaReportJobName = job.shootName
                                        }
                                    },
                                    onFetchProxyRecommendations: { await client.fetchProxyRecommendations(jobId: job.id) },
                                    onGenerateProxies: { Task { await client.generateProxies(jobId: job.id) } },
                                    onViewProxyStatus: {
                                        Task {
                                            proxyStatuses = await client.fetchProxies(jobId: job.id)
                                            proxyStatusJobName = job.shootName
                                        }
                                    }
                                )
                            }
                        }
                    }
                }
                .padding(16)
            }
        }
        .frame(width: 520, height: 680)
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
                MediaReportView(report: report, shootName: mediaReportJobName)
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
                    await client.fetch()
                }
            }
        }
    }

    // MARK: - New Shoot form

    @State private var draftProfile = "joshx"
    @State private var draftShootName = ""
    @State private var draftClientName = ""
    @State private var draftSourcePath: String?
    @State private var draftDestinationPath: String?
    @State private var draftDeliverableFormat = postDeliverableFormatOptions[0]
    @State private var draftResolution = postResolutionOptions[0]
    @State private var draftFrameRate = postFrameRateOptions[2]  // defaults to "25", easily changed per shoot

    private var canCreateJob: Bool {
        !draftShootName.trimmingCharacters(in: .whitespaces).isEmpty
            && draftSourcePath != nil && draftDestinationPath != nil
            && (draftProfile != "alpha_mode" || !draftClientName.trimmingCharacters(in: .whitespaces).isEmpty)
    }

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
            volumePicker("Destination drive", selection: $draftDestinationPath)

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

            Text("Nothing is copied until you tap Start on the created job -- original footage is never modified or deleted.")
                .font(PCorpFont.body(10.5))
                .foregroundStyle(theme.textTertiary)
        }
        .padding(12)
        .cardSurface(radius: 10)
    }

    @ViewBuilder
    private func volumePicker(_ label: String, selection: Binding<String?>) -> some View {
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
                    Text(volume.name).tag(String?.some(volume.path))
                }
            }
        }
    }

    private func createShoot() async {
        guard let sourcePath = draftSourcePath, let destinationPath = draftDestinationPath else { return }
        let draft = PostJobDraft(
            profile: draftProfile, shootName: draftShootName, sourcePath: sourcePath,
            destinationVolumePath: destinationPath,
            clientName: draftProfile == "alpha_mode" ? draftClientName : nil,
            sourceVolumeName: client.sourceVolumes.first(where: { $0.path == sourcePath })?.name,
            sourceVolumeUuid: client.sourceVolumes.first(where: { $0.path == sourcePath })?.uuid,
            deliverableFormat: draftDeliverableFormat, resolution: draftResolution, frameRate: draftFrameRate
        )
        if let jobId = await client.createJob(draft) {
            toastCenter.show("POST job created", style: .success)
            draftShootName = ""; draftClientName = ""; draftSourcePath = nil; draftDestinationPath = nil
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
    @Environment(\.appTheme) private var theme

    @State private var recommendedProxyCount: Int?

    private var statusColor: Color {
        switch job.status {
        case "ingested", "premiere_project_created", "complete": return theme.statusGood
        case "ingest_failed", "cancelled": return theme.statusRisk
        case "scanning", "ready", "ingesting", "verifying", "analyzing_media", "generating_proxies": return theme.statusHot
        default: return theme.textSecondary
        }
    }

    private var canStart: Bool { ["created", "ingest_failed", "cancelled"].contains(job.status) }
    private var canCancel: Bool { job.isActive }
    private var canAnalyzeMedia: Bool { job.status == "ingested" }
    private var canCheckForProxies: Bool { job.status == "ingested" && job.mediaAnalyzedAt != nil }

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

            if job.status == "analyzing_media" {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Analyzing media…").font(PCorpFont.body(10.5)).foregroundStyle(theme.textSecondary)
                }
            } else if job.status == "generating_proxies" {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Generating proxies…").font(PCorpFont.body(10.5)).foregroundStyle(theme.textSecondary)
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
                     + (job.proxiesGeneratedAt != nil ? " Proxies generated." : ""))
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
                if canCheckForProxies && (recommendedProxyCount ?? 0) > 0 {
                    Button(job.proxiesGeneratedAt == nil ? "Generate Proxies" : "Regenerate Proxies", action: onGenerateProxies)
                        .buttonStyle(.bordered)
                }
                if job.proxiesGeneratedAt != nil {
                    Button("Proxy Status", action: onViewProxyStatus)
                        .buttonStyle(.bordered)
                }
                Button("Delete", role: .destructive, action: onDelete)
                    .buttonStyle(.bordered)
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
    @Environment(\.appTheme) private var theme

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
            }
            .padding(16)
        }
        .frame(width: 460, height: 560)
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
