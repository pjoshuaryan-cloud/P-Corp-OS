import SwiftUI
import PCorpKit

/// iOS port of desktop's own PostView.swift -- READ-ONLY by design
/// (2026-09-25, Phase 1). Picking a source drive needs a live listing
/// only the Mac physically connected to it can produce, so job
/// creation/start/cancel/delete only exist on desktop; this screen just
/// shows job status/progress, same visibility every other Mac-only
/// capability (e.g. trade proposals' execution status) already gives
/// the phone via the same shared Postgres.
struct PostView: View {
    @StateObject private var client = PostClient()
    @Environment(\.appTheme) private var theme

    @State private var pollTask: Task<Void, Never>?
    @State private var mediaReport: MediaReport?
    @State private var mediaReportJobId = 0
    @State private var mediaReportJobName = ""
    @State private var mediaReportFiles: [PostJobFile] = []
    @State private var proxyStatuses: [ProxyStatus]?
    @State private var proxyStatusJobName = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(theme.divider)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let error = client.errorMessage {
                        Text(error).font(PCorpFont.body(12)).foregroundStyle(theme.statusRisk)
                    }
                    if client.isLoading && client.jobs.isEmpty {
                        SkeletonList(count: 2)
                    } else if client.jobs.isEmpty {
                        Text("No POST jobs yet. Create one from the desktop app once a drive is connected to your Mac.")
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                    } else {
                        VStack(alignment: .leading, spacing: 8) {
                            ForEach(client.jobs) { job in
                                PostJobStatusRow(job: job, onViewReport: {
                                    Task {
                                        mediaReport = await client.fetchMediaReport(jobId: job.id)
                                        mediaReportJobId = job.id
                                        mediaReportJobName = job.shootName
                                        mediaReportFiles = await client.fetchJobFiles(id: job.id)
                                    }
                                }, onViewProxyStatus: {
                                    Task {
                                        proxyStatuses = await client.fetchProxies(jobId: job.id)
                                        proxyStatusJobName = job.shootName
                                    }
                                })
                            }
                        }
                    }
                }
                .padding(16)
            }
            .refreshable { await client.fetch() }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        .task {
            await client.fetch()
            startPollingIfNeeded()
        }
        .onDisappear { pollTask?.cancel() }
        .sheet(isPresented: Binding(
            get: { mediaReport != nil },
            set: { if !$0 { mediaReport = nil } }
        )) {
            if let report = mediaReport {
                MediaReportView(report: report, shootName: mediaReportJobName, jobId: mediaReportJobId, files: mediaReportFiles, client: client)
            }
        }
        .sheet(isPresented: Binding(
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
            VStack(alignment: .leading, spacing: 2) {
                Text("POST")
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text("Post-production prep -- view-only here, create jobs from the Mac")
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
        }
        .padding(16)
    }

    private func startPollingIfNeeded() {
        pollTask?.cancel()
        pollTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 3_000_000_000)
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
}

private struct PostJobStatusRow: View {
    let job: PostJob
    let onViewReport: () -> Void
    let onViewProxyStatus: () -> Void
    @Environment(\.appTheme) private var theme

    private var statusColor: Color {
        switch job.status {
        case "ingested", "premiere_project_created", "complete": return theme.statusGood
        case "ingest_failed", "cancelled": return theme.statusRisk
        case "scanning", "ready", "ingesting", "verifying", "analyzing_media", "generating_proxies": return theme.statusHot
        default: return theme.textSecondary
        }
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

            if job.mediaAnalyzedAt != nil {
                Button("View Report", action: onViewReport)
                    .buttonStyle(.bordered)
            }
            if job.proxiesGeneratedAt != nil {
                Button("Proxy Status", action: onViewProxyStatus)
                    .buttonStyle(.bordered)
            }
        }
        .padding(10)
        .cardSurface(radius: 8)
    }

    private func formattedBytes(_ bytes: Int) -> String {
        ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)
    }
}

/// Phase 2 (2026-09-25) -- iOS port of desktop's own MediaReportView,
/// same NavigationStack-with-Done sheet precedent as CustomerDetailView.
/// Deliberately labeled as computed categorization throughout, never
/// creative judgment.
private struct MediaReportView: View {
    let report: MediaReport
    let shootName: String
    let jobId: Int
    let files: [PostJobFile]
    let client: PostClient
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss

    @State private var transcriptSheetFile: PostJobFile?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
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
                    Text("Transcribed by Premiere's own native transcription -- never generated or verified for accuracy by P Corp OS.")
                        .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                    let dialogue = report.dialogueSummary
                    Text("\(dialogue.filesWithTranscripts) transcribed, \(dialogue.filesPendingTranscription) pending"
                         + (dialogue.filesFlaggedProfanity > 0 ? ", \(dialogue.filesFlaggedProfanity) flagged for profanity" : "")
                         + (dialogue.filesFlaggedFillerWords > 0 ? ", \(dialogue.filesFlaggedFillerWords) flagged for filler words" : ""))
                        .font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                    ForEach(files.filter { $0.status == "verified" }) { file in
                        Button(file.relativePath) { transcriptSheetFile = file }
                            .font(PCorpFont.body(11.5))
                            .foregroundStyle(theme.statusHot)
                    }
                }
                .padding(16)
            }
            .background(theme.background)
            .navigationTitle(shootName)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .sheet(item: $transcriptSheetFile) { file in
                TranscriptView(jobId: jobId, file: file, client: client)
            }
        }
    }

    private func sectionLabel(_ text: String) -> some View {
        Text(text)
            .font(PCorpFont.label(10))
            .trackedLabel(1.1)
            .foregroundStyle(theme.textSecondary)
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
}

/// Phase 4 (2026-09-26) -- iOS port of desktop's own ProxyStatusView,
/// same NavigationStack-with-Done sheet precedent as MediaReportView.
/// Read-only, matching Phase 1's own desktop-only-actions decision --
/// no Generate/Regenerate button here.
private struct ProxyStatusView: View {
    let statuses: [ProxyStatus]
    let shootName: String
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
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
            .background(theme.background)
            .navigationTitle(shootName)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func statusColor(for status: String) -> Color {
        switch status {
        case "complete": return theme.statusGood
        case "failed": return theme.statusRisk
        default: return theme.statusHot
        }
    }
}

/// Phase 6 (2026-09-27) -- iOS port of desktop's own TranscriptView, same
/// NavigationStack-with-Done sheet precedent as MediaReportView/
/// ProxyStatusView. Plain, speaker-grouped text only, fetched on demand.
private struct TranscriptView: View {
    let jobId: Int
    let file: PostJobFile
    let client: PostClient
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss

    @State private var transcript: Transcript?
    @State private var isLoading = true

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
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
            .background(theme.background)
            .navigationTitle(file.relativePath)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .task {
                transcript = await client.fetchTranscript(jobId: jobId, fileId: file.id)
                isLoading = false
            }
        }
    }
}
