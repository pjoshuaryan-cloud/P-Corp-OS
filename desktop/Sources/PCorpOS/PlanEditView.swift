import SwiftUI
import AppKit
import UniformTypeIdentifiers
import PCorpKit

/// Plan an edit for one POST job (2026-10-09): pick the style, the song and the opening clip, plan, then render a
/// preview, review the moments, and add accents -- everything before Premiere, which builds the sequence from the
/// saved plan ("Assemble Edit" in the plugin).
///
/// Shown inline over the job list (not as a nested popover/sheet): PostView is itself a fixed-size popover, and the
/// song picker uses NSOpenPanel exactly like PostView's own folder picker does, from the same popover level.
///
/// Planning REPLACES the job's saved plan (the backend keeps the old one as a backup file first), so when a plan
/// with reviewed moments or accents exists this asks before replacing it.
struct PlanEditView: View {
    let job: PostJob
    let onBack: () -> Void

    @StateObject private var client: EditPlanClient
    @Environment(\.appTheme) private var theme
    @EnvironmentObject private var toastCenter: ToastCenter

    @State private var styleSlug: String?
    @State private var songPath: String?
    @State private var startAutomatic = true
    @State private var startText = ""
    @State private var lengthAutomatic = true
    @State private var lengthText = ""
    @State private var openingFileId: Int?
    @State private var clipFilter = ""
    @State private var addAccents = true
    @State private var addSoundEffects = true
    @State private var confirmReplace = false
    @State private var isPlanning = false
    @State private var didApplyDefaults = false
    @State private var confirmDescribe = false
    @State private var scriptText = ""
    @State private var brandGraphics = true
    @State private var burnCaptions = true
    @State private var cardTagline = ""
    @State private var cardContact = ""
    @State private var cameraIds: [Int] = []
    @State private var dialogueFileId: Int?

    init(job: PostJob, onBack: @escaping () -> Void) {
        self.job = job
        self.onBack = onBack
        _client = StateObject(wrappedValue: EditPlanClient(jobId: job.id))
    }

    // MARK: - Derived

    private var options: EditOptions? { client.options }
    private var selectedStyle: EditStyleOption? { options?.styles.first { $0.slug == styleSlug } }
    private var isStory: Bool { selectedStyle?.isNarratedStory == true }
    private var isDialogue: Bool { selectedStyle?.isDialogueLed == true }
    private var dialogueSourceId: Int? { cameraIds.contains(dialogueFileId ?? -1) ? dialogueFileId : cameraIds.first }
    private var scriptTrimmed: String { scriptText.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var cardContactLines: [String]? {
        let lines = cardContact.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        return lines.isEmpty ? nil : Array(lines.prefix(4))
    }
    private var parsedStart: Double? { Double(startText.replacingOccurrences(of: ",", with: ".")) }
    private var parsedLength: Double? { Double(lengthText.replacingOccurrences(of: ",", with: ".")) }
    private var songName: String? { songPath.map { URL(fileURLWithPath: $0).lastPathComponent } }
    private var songIsOutsideProject: Bool {
        guard let songPath, let folder = options?.music.folder else { return false }
        return URL(fileURLWithPath: songPath).deletingLastPathComponent().path != folder
    }

    private var inputProblem: String? {
        if styleSlug == nil { return "Choose a style." }
        if isDialogue && cameraIds.count < 2 { return "Pick at least two clips that filmed the same interview." }
        if !isDialogue && songPath == nil { return "Choose a song." }
        if !startAutomatic && (parsedStart == nil || (parsedStart ?? 0) < 0) { return "The song start must be a number of seconds (0 or more)." }
        if !lengthAutomatic && (parsedLength == nil || (parsedLength ?? 0) <= 0) { return "The length must be a number of seconds above 0." }
        return nil
    }

    private var replacesWorkThatTookTime: Bool {
        guard let plan = options?.savedPlan else { return false }
        return plan.reviewed > 0 || plan.accents != nil
    }

    private var filteredClips: [EditClipOption] {
        let all = options?.clips ?? []
        let q = clipFilter.trimmingCharacters(in: .whitespaces).lowercased()
        guard !q.isEmpty else { return all }
        return all.filter { $0.name.lowercased().contains(q) || $0.scene.lowercased().contains(q) }
    }

    // MARK: - Body

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(theme.divider)
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        if let error = client.errorMessage { messageText(error, color: theme.statusRisk) }
                        if let warning = client.warningMessage { messageText(warning, color: theme.statusHot) }

                        if client.isLoading && options == nil {
                            ProgressView().controlSize(.small)
                        } else if let options {
                            if job.mediaAnalyzedAt == nil {
                                messageText("Run Analyze Media on this job first -- the plan needs to know what each clip is.", color: theme.statusHot)
                            }
                            if let plan = options.savedPlan {
                                currentPlanCard(plan, options: options).id("current-plan")
                                Divider().overlay(theme.divider)
                            }
                            planForm(options)
                        }
                    }
                    .padding(16)
                }
                .onChange(of: options?.savedPlan?.plannedAt) { _, _ in
                    withAnimation { proxy.scrollTo("current-plan", anchor: .top) }
                }
            }
        }
        .background(theme.background)
        .task {
            await client.load()
            applyDefaultsOnce()
        }
        .alert("Replace the current plan?", isPresented: $confirmReplace) {
            Button("Cancel", role: .cancel) {}
            Button("Plan Again", role: .destructive) { Task { await runPlan() } }
        } message: {
            if let plan = options?.savedPlan {
                Text("The current plan has \(plan.reviewed) reviewed moment(s)\(plan.accents != nil ? " and accents" : ""). Planning again starts a fresh plan, and Premiere will build from that one. The current plan is kept as a backup file in the job's edit_plans folder.")
            }
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
            Button(action: onBack) {
                Label("Jobs", systemImage: "chevron.left")
            }
            .buttonStyle(.bordered)
            VStack(alignment: .leading, spacing: 1) {
                Text("Plan Edit").font(PCorpFont.display(18)).foregroundStyle(theme.textPrimary)
                Text(job.shootName).font(PCorpFont.body(11)).foregroundStyle(theme.textSecondary).lineLimit(1)
            }
            Spacer()
            RefreshIconButton { await client.load() }
        }
        .padding(16)
    }

    // MARK: - Current plan

    @ViewBuilder
    private func currentPlanCard(_ plan: EditSavedPlan, options: EditOptions) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                sectionLabel("CURRENT PLAN")
                Spacer()
                Text("planned \(Self.friendlyTime(plan.plannedAt))").font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
            }
            Text("\(plan.shots) shots · \(String(format: "%.1f", plan.seconds)) s · \(options.styles.first { $0.slug == plan.style }?.title ?? plan.style ?? "style")")
                .font(PCorpFont.body(13)).foregroundStyle(theme.textPrimary)
            planLine("Song", "\(plan.musicName)" + (plan.tempoBpm.map { " · \(String(format: "%.0f", $0)) bpm" } ?? "") + (plan.musicInSeconds.map { " · starts at \(String(format: "%.1f", $0)) s" } ?? ""))
            planLine("Opening clip", plan.openingClip?.name ?? "none")
            planLine("Rhythm", rhythmText(plan.checks))
            planLine("Moments", plan.reviewed == 0 ? "Not reviewed yet" : "\(plan.reviewed) of \(plan.shots) reviewed, \(plan.swapped) swapped")
            planLine("Accents", accentsText(plan.accents))
            planLine("Preview", previewText(plan.preview))
            ForEach(plan.notes + plan.accentNotes, id: \.self) { note in
                Text(note).font(PCorpFont.body(10.5)).foregroundStyle(theme.statusHot)
            }

            HStack(spacing: 8) {
                AsyncButton(action: renderPreview) { Text(plan.preview == nil ? "Render Preview" : "Re-render Preview") }
                    .buttonStyle(.bordered)
                if let preview = plan.preview {
                    Button("Open Preview") { open(file: preview.path) }.buttonStyle(.bordered)
                }
                Button("Review Moments") { NSWorkspace.shared.open(client.reviewPageURL()) }.buttonStyle(.bordered)
            }
            HStack(spacing: 8) {
                AsyncButton(action: { await client.setAccents(enabled: true, soundEffects: addSoundEffects) }) {
                    Text(plan.accents == nil ? "Add Accents" : "Re-apply Accents")
                }
                .buttonStyle(.bordered)
                .disabled(selectedStyle?.hasAccents == false && plan.accents == nil)
                if plan.accents != nil {
                    AsyncButton(action: { await client.setAccents(enabled: false, soundEffects: false) }) { Text("Remove Accents") }
                        .buttonStyle(.bordered)
                }
                Text(addSoundEffects ? "with sound effects" : "no sound effects")
                    .font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
            }
            Text("Review Moments opens a page in your browser: for each shot, keep it or pick another moment. It saves as you click, and accents stay valid because the cuts don't move.")
                .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
            Text(nextStepText)
                .font(PCorpFont.body(11.5)).foregroundStyle(theme.textSecondary)
                .padding(.top, 2)
        }
        .padding(12)
        .cardSurface(radius: 10)
    }

    private var nextStepText: String {
        job.status == "premiere_project_created"
            ? "Next: in Premiere, open the P Corp panel and click Assemble Edit."
            : "Next: create the Premiere project (Prepare POST Project in the plugin), then click Assemble Edit."
    }

    private func rhythmText(_ checks: EditPlanChecks) -> String {
        var parts: [String] = []
        if let median = checks.shotLengthMedian { parts.append("median shot \(String(format: "%.2f", median)) s" + (checks.styleMedian.map { " (style \(String(format: "%.2f", $0)))" } ?? "")) }
        if let onHits = checks.cutsOnHits { parts.append("\(Int((onHits * 100).rounded()))% of cuts on a music hit") }
        if let distinct = checks.distinctClips { parts.append("\(distinct) different clips") }
        return parts.isEmpty ? "—" : parts.joined(separator: " · ")
    }

    private func accentsText(_ accents: EditAccentCounts?) -> String {
        guard let a = accents else { return "none" }
        var parts = ["\(a.flashes) flashes", "\(a.zoomHits) zoom hits", "\(a.shotZoomBlur) zoom-blurred shots", "\(a.blackAndWhiteShots) black & white"]
        if a.logo > 0 { parts.append("logo") }
        parts.append(a.sfx > 0 ? "\(a.sfx) sound effects" : "no sound effects")
        return parts.joined(separator: " · ")
    }

    private func previewText(_ preview: EditPreviewInfo?) -> String {
        guard let preview else { return "not rendered" }
        return "rendered \(Self.friendlyTime(preview.renderedAt))" + (preview.upToDate ? "" : " — out of date (the moments changed since)")
    }

    // MARK: - The planning form

    @ViewBuilder
    private func planForm(_ options: EditOptions) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionLabel(options.savedPlan == nil ? "PLAN AN EDIT" : "PLAN AGAIN")

            styleSection(options)
            if isStory { scriptSection; brandSection(options) }
            songSection(options)
            lengthSection
            if isDialogue { camerasSection(options) } else { openingSection(options) }
            accentsSection(options)

            if let problem = inputProblem {
                Text(problem).font(PCorpFont.body(11)).foregroundStyle(theme.textTertiary)
            }
            HStack(spacing: 10) {
                Button {
                    if replacesWorkThatTookTime { confirmReplace = true } else { Task { await runPlan() } }
                } label: {
                    Text(options.savedPlan == nil ? "Plan Edit" : "Plan Again")
                }
                .buttonStyle(.actionFilled)
                .disabled(inputProblem != nil || isPlanning || job.mediaAnalyzedAt == nil)
                if isPlanning {
                    ProgressView().controlSize(.small)
                    Text(isDialogue ? "Lining up the cameras by sound and finding the gaps in the dialogue…" : (isStory ? "Planning the story…" : "Listening to the song and cutting on its hits…")).font(PCorpFont.body(11)).foregroundStyle(theme.textSecondary)
                }
            }
            Text("Nothing in Premiere changes until you click Assemble Edit there.")
                .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
        }
    }

    // MARK: - Form sections

    /// Corporate story only: the opening/closing brand cards, the corner logo and the burned-in captions, all from the job's logo.
    @ViewBuilder
    private func brandSection(_ options: EditOptions) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            fieldLabel("Brand cards, logo and captions")
            Toggle(isOn: $brandGraphics) {
                Text("Lay them over the b-roll").font(PCorpFont.body(12))
            }
            .toggleStyle(.switch).controlSize(.small)
            .disabled(options.logo == nil)
            if let logo = options.logo {
                Text("Logo: \(URL(fileURLWithPath: logo).lastPathComponent). Opening and closing cards, a logo in the top-right corner for the body, and captions at the bottom, matched to your reference. They go on V2, V3 and V4 above the b-roll.")
                    .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
            } else {
                Text("No logo found in this job's graphics folder. Put a PNG logo there to get brand cards, the corner logo and captions.")
                    .font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
            }
            if brandGraphics && options.logo != nil {
                TextField("Opening card tagline (optional)", text: $cardTagline)
                    .textFieldStyle(.plain).font(PCorpFont.body(12)).padding(8).cardSurface(radius: 8)
                TextEditor(text: $cardContact)
                    .font(PCorpFont.body(12)).scrollContentBackground(.hidden).padding(6)
                    .frame(minHeight: 56, maxHeight: 84)
                    .background(RoundedRectangle(cornerRadius: 6).fill(theme.surface))
                    .overlay(RoundedRectangle(cornerRadius: 6).stroke(theme.surfaceBorder, lineWidth: 1))
                Text("Closing card lines, one per line, up to four (email, phone…). Optional.")
                    .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                if !scriptTrimmed.isEmpty {
                    Toggle(isOn: $burnCaptions) {
                        Text("Burn the captions into the picture").font(PCorpFont.body(12))
                    }
                    .toggleStyle(.switch).controlSize(.small)
                    Text("Premiere's scripting can't make editable captions, so these are images. A captions.srt is always written for editable ones.")
                        .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                }
            }
        }
    }

    /// Narrated b-roll story only: paste the narration and each phrase becomes one shot (a caption file is written beside the plan).
    @ViewBuilder
    private var scriptSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            fieldLabel("Narration script (optional)")
            TextEditor(text: $scriptText)
                .font(PCorpFont.body(12))
                .scrollContentBackground(.hidden)
                .padding(6)
                .frame(minHeight: 90, maxHeight: 160)
                .background(RoundedRectangle(cornerRadius: 6).fill(theme.surface))
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(theme.surfaceBorder, lineWidth: 1))
            Text(scriptTrimmed.isEmpty
                 ? "Leave empty to cut at the style's own rhythm. Paste the voice-over and each phrase of about four words becomes a shot, timed to how long it takes to say, with a matching captions (.srt) file."
                 : "\(scriptTrimmed.split(whereSeparator: { $0.isWhitespace }).count) words. Shot lengths are estimated from the style's narration pace; re-time them to the real voice-over.")
                .font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
        }
    }

    @ViewBuilder
    private func styleSection(_ options: EditOptions) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            fieldLabel("Style")
            if options.styles.isEmpty {
                Text("No saved styles yet. A style comes from a finished edit saved as a reference.")
                    .font(PCorpFont.body(11)).foregroundStyle(theme.textTertiary)
            }
            ForEach(options.styles) { style in
                Button { styleSlug = style.slug } label: {
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: styleSlug == style.slug ? "largecircle.fill.circle" : "circle")
                            .foregroundStyle(styleSlug == style.slug ? theme.accent : theme.textTertiary)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(style.title).font(PCorpFont.body(12.5)).foregroundStyle(theme.textPrimary)
                            if !style.description.isEmpty {
                                Text(style.description).font(PCorpFont.body(10.5)).foregroundStyle(theme.textSecondary)
                            }
                            Text(styleFacts(style)).font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .cardSurface(radius: 8)
                }
                .buttonStyle(.plain)
            }
        }

    }

    @ViewBuilder
    private func songSection(_ options: EditOptions) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            fieldLabel(isDialogue ? "Start" : "Song")
            if !isDialogue { HStack(spacing: 8) {
                Menu {
                    ForEach(options.music.files) { file in
                        Button("\(file.name) (\(String(format: "%.1f", file.megabytes)) MB)") { songPath = file.path }
                    }
                    if !options.music.files.isEmpty { Divider() }
                    Button("Choose a file…") { chooseSong(musicFolder: options.music.folder) }
                } label: {
                    Text(songName ?? "Choose a song…").lineLimit(1)
                }
                .fixedSize()
                if songIsOutsideProject {
                    Text("copied into \(URL(fileURLWithPath: options.music.folder).lastPathComponent) when you plan")
                        .font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
                }
            }
            if options.music.files.isEmpty && songPath == nil {
                Text("This job's music folder has no songs yet.").font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
            } }
            HStack(spacing: 8) {
                Picker("Start", selection: $startAutomatic) {
                    Text("Automatic").tag(true)
                    Text("At…").tag(false)
                }
                .pickerStyle(.segmented)
                .frame(width: 180)
                if !startAutomatic {
                    numberField("seconds", text: $startText)
                }
                Text(startAutomatic ? (isDialogue ? "where the real speech starts" : (isStory ? "the song is a bed: it starts on a strong hit and fades out over the closing shot" : "the stretch of the song with the most strong hits")) : (isDialogue ? "into the dialogue camera's clip" : "into the song"))
                    .font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
            }
        }

    }

    @ViewBuilder
    private var lengthSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            fieldLabel("Length")
            HStack(spacing: 8) {
                Picker("Length", selection: $lengthAutomatic) {
                    Text("Style's own").tag(true)
                    Text("Custom").tag(false)
                }
                .pickerStyle(.segmented)
                .frame(width: 200)
                if isStory && !scriptTrimmed.isEmpty {
                    Text("set by the script: each phrase is one shot").font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
                } else if lengthAutomatic {
                    if let seconds = selectedStyle?.seconds {
                        Text("\(String(format: "%.1f", seconds)) s" + (isDialogue ? ", or as much as every camera has" : "")).font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
                    }
                } else {
                    numberField("seconds", text: $lengthText)
                }
            }
        }

    }

    @ViewBuilder
    private func openingSection(_ options: EditOptions) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                fieldLabel("Opening clip")
                Spacer()
                Text(openingFileId == nil ? "None" : (options.clips.first { $0.fileId == openingFileId }?.name ?? ""))
                    .font(PCorpFont.body(10.5)).foregroundStyle(theme.textSecondary)
                if openingFileId != nil {
                    Button("Clear") { openingFileId = nil }.buttonStyle(.borderless).font(PCorpFont.body(10.5))
                }
            }
            Text("Opens the edit and comes back as the closing card, where the logo goes. Optional.")
                .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
            describeClipsBlock(options)
            TextField("Search by file name or what the clip shows", text: $clipFilter)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(12))
                .padding(8)
                .cardSurface(radius: 8)
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 84, maximum: 96), spacing: 8, alignment: .top)], alignment: .leading, spacing: 10) {
                    ForEach(filteredClips) { clip in
                        ClipCell(clip: clip, thumbURL: client.thumbURL(fileId: clip.fileId), selected: openingFileId == clip.fileId)
                            .onTapGesture { openingFileId = (openingFileId == clip.fileId) ? nil : clip.fileId }
                    }
                }
                .padding(6)
                if filteredClips.isEmpty {
                    Text("No clips match.").font(PCorpFont.body(11)).foregroundStyle(theme.textTertiary).padding(8)
                }
            }
            .frame(height: 270)
            .cardSurface(radius: 8)
        }

    }

    /// Talking head only: pick the clips that filmed the same interview. The planner lines them up by their sound.
    @ViewBuilder
    private func camerasSection(_ options: EditOptions) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                fieldLabel("Cameras")
                Spacer()
                Text(cameraIds.isEmpty ? "None picked" : "\(cameraIds.count) picked")
                    .font(PCorpFont.body(10.5)).foregroundStyle(theme.textSecondary)
                if !cameraIds.isEmpty {
                    Button("Clear") { cameraIds = []; dialogueFileId = nil }.buttonStyle(.borderless).font(PCorpFont.body(10.5))
                }
            }
            Text("Pick the clips that filmed the same interview, one per camera angle (at least two). They are lined up by what each microphone heard, so each needs its own audio. The edit switches angle at quiet gaps in the dialogue.")
                .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
            if cameraIds.count >= 2 {
                HStack(spacing: 8) {
                    Text("Dialogue from").font(PCorpFont.body(11)).foregroundStyle(theme.textSecondary)
                    Menu {
                        ForEach(cameraIds, id: \.self) { id in
                            Button(options.clips.first { $0.fileId == id }?.name ?? "clip \(id)") { dialogueFileId = id }
                        }
                    } label: {
                        Text(options.clips.first { $0.fileId == dialogueSourceId }?.name ?? "first camera").lineLimit(1)
                    }
                    .fixedSize()
                    Text("that camera's own sound becomes the dialogue track").font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
                }
            }
            TextField("Search by file name", text: $clipFilter)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(12))
                .padding(8)
                .cardSurface(radius: 8)
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 84, maximum: 96), spacing: 8, alignment: .top)], alignment: .leading, spacing: 10) {
                    ForEach(filteredClips) { clip in
                        ClipCell(clip: clip, thumbURL: client.thumbURL(fileId: clip.fileId), selected: cameraIds.contains(clip.fileId))
                            .onTapGesture {
                                if let at = cameraIds.firstIndex(of: clip.fileId) { cameraIds.remove(at: at) } else { cameraIds.append(clip.fileId) }
                            }
                    }
                }
                .padding(6)
                if filteredClips.isEmpty {
                    Text("No clips match.").font(PCorpFont.body(11)).foregroundStyle(theme.textTertiary).padding(8)
                }
            }
            .frame(height: 270)
            .cardSurface(radius: 8)
        }
    }

    @ViewBuilder
    private func accentsSection(_ options: EditOptions) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            fieldLabel("Accents")
            Toggle("Add accents — flashes, zoom hits, black & white ending, logo", isOn: $addAccents)
                .disabled(selectedStyle?.hasAccents == false)
                .font(PCorpFont.body(12))
            Toggle("Add sound effects (stand-ins from your SFX library — swap them in Premiere)", isOn: $addSoundEffects)
                .disabled(!addAccents || selectedStyle?.hasAccents == false)
                .font(PCorpFont.body(12))
            if selectedStyle?.hasAccents == false {
                Text("This style has no accents — it was hard cuts only.").font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
            } else if let logo = options.logo {
                Text("Logo: \(URL(fileURLWithPath: logo).lastPathComponent)").font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
            } else if addAccents {
                Text("No logo found in the job's graphics folder, so the closing card will have none. Put a PNG there and re-apply accents.")
                    .font(PCorpFont.body(10.5)).foregroundStyle(theme.statusHot)
            }
        }

    }

    // MARK: - Describing clips (costs real credits)

    private var describeIsRunning: Bool { client.momentsStatus?.run?.isRunning == true }

    @ViewBuilder
    private func describeClipsBlock(_ options: EditOptions) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            if let status = client.momentsStatus {
                if let run = status.run, run.isRunning {
                    ProgressView(value: Double(min(run.done + run.failed.count, run.total)), total: Double(max(run.total, 1)))
                    HStack {
                        Text("Describing clips with Claude: \(run.done) of \(run.total) done" + (run.failed.isEmpty ? "" : ", \(run.failed.count) couldn't be read"))
                            .font(PCorpFont.body(10.5)).foregroundStyle(theme.textSecondary)
                        Spacer()
                        AsyncButton(action: { await client.stopDescribingClips() }) { Text("Stop") }.buttonStyle(.bordered)
                    }
                    Text("It keeps going if you close this screen. Clips already described are kept if you stop.")
                        .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                } else if status.missing > 0 {
                    HStack(spacing: 8) {
                        Text("\(status.missing) of \(status.total) clips have no description, so they show by file name only and the planner can't use what they show.")
                            .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                        Spacer(minLength: 0)
                        Button("Describe \(status.missing)…") { confirmDescribe = true }
                            .buttonStyle(.bordered)
                            .disabled(!status.apiKeySet)
                    }
                    if !status.apiKeySet {
                        Text("No Claude API key is set on this Mac's backend, so clips can't be described.")
                            .font(PCorpFont.body(10)).foregroundStyle(theme.statusRisk)
                    }
                    if let run = status.run, let message = run.message {
                        Text(message).font(PCorpFont.body(10.5))
                            .foregroundStyle(run.state == "stopped" || run.state == "failed" ? theme.statusRisk : theme.textSecondary)
                    }
                } else {
                    Text("All \(status.total) clips are described.").font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
                }
            } else if options.moments.probed < options.moments.total {
                Text("\(options.moments.total - options.moments.probed) of \(options.moments.total) clips have no description yet, so they're shown by file name only.")
                    .font(PCorpFont.body(10)).foregroundStyle(theme.textTertiary)
            }
        }
        // Polls while a run is going. Completion is handled by onChange (a task is cancelled when its id changes,
        // which would cut a reload that runs at the end of the task itself).
        .task(id: describeIsRunning) {
            guard describeIsRunning else { return }
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                if Task.isCancelled { return }
                await client.loadMomentsRun()
                if !describeIsRunning { return }
            }
        }
        .onChange(of: describeIsRunning) { wasRunning, isRunning in
            guard wasRunning, !isRunning else { return }
            Task {
                await client.refreshOptions()
                if let run = client.momentsStatus?.run {
                    toastCenter.show(run.message ?? "Finished describing clips.", style: run.state == "done" ? .success : .warning)
                }
            }
        }
        .alert("Describe \(client.momentsStatus?.missing ?? 0) clips with Claude?", isPresented: $confirmDescribe) {
            Button("Cancel", role: .cancel) {}
            Button("Describe \(client.momentsStatus?.missing ?? 0) Clips") {
                guard let missing = client.momentsStatus?.missing else { return }
                Task { _ = await client.startDescribingClips(maxClips: missing) }
            }
        } message: {
            if let estimate = client.momentsStatus?.estimate {
                Text(describeCostText(estimate))
            }
        }
    }

    private func describeCostText(_ estimate: MomentsEstimate) -> String {
        let tokensIn = Int((Double(estimate.inputTokens) / 1000).rounded())
        let tokensOut = Int((Double(estimate.outputTokens) / 1000).rounded())
        return "This sends frames from \(estimate.clips) clips to Claude: about \(tokensIn)k tokens in and \(tokensOut)k out. "
            + "That is at most about $\(String(format: "%.2f", estimate.usdAtMost)) (counting \(estimate.assumption)); your real price may differ. "
            + "Your balance is checked first. You can stop at any time and the clips already described are kept."
    }

    private func styleFacts(_ style: EditStyleOption) -> String {
        var parts: [String] = []
        if let seconds = style.seconds { parts.append("\(String(format: "%.0f", seconds)) s") }
        if let shots = style.shots { parts.append("\(shots) shots") }
        if let median = style.medianShotSeconds { parts.append("median shot \(String(format: "%.2f", median)) s") }
        if !style.format.isEmpty { parts.append(style.format) }
        parts.append(style.hasAccents ? "with accents" : "hard cuts only")
        return parts.joined(separator: " · ")
    }

    // MARK: - Actions

    private func applyDefaultsOnce() {
        guard !didApplyDefaults, let options else { return }
        didApplyDefaults = true
        let saved = options.savedPlan
        styleSlug = options.styles.first { $0.slug == saved?.style }?.slug ?? options.styles.first?.slug
        if let name = saved?.musicName, let match = options.music.files.first(where: { $0.name == name }) {
            songPath = match.path
        } else {
            songPath = options.music.defaultPath ?? options.music.files.first?.path
        }
        openingFileId = saved?.openingClip?.fileId
        addAccents = saved == nil ? true : (saved?.accents != nil)
        if selectedStyle?.hasAccents == false { addAccents = false }
    }

    private func runPlan() async {
        guard inputProblem == nil, let slug = styleSlug else { return }
        isPlanning = true
        let body = EditPlanRequestBody(
            style: [slug], musicPath: songPath,
            musicInSeconds: startAutomatic ? nil : parsedStart,
            targetSeconds: lengthAutomatic ? nil : parsedLength,
            bookendFileId: isDialogue ? nil : openingFileId,
            script: isStory && !scriptTrimmed.isEmpty ? scriptTrimmed : nil,
            cameraFileIds: isDialogue ? cameraIds : nil,
            audioFileId: isDialogue ? dialogueSourceId : nil,
            brandGraphics: isStory ? brandGraphics : nil,
            burnCaptions: isStory ? burnCaptions : nil,
            cardTagline: isStory && !cardTagline.trimmingCharacters(in: .whitespaces).isEmpty ? cardTagline.trimmingCharacters(in: .whitespaces) : nil,
            cardContact: isStory ? cardContactLines : nil
        )
        let saved = await client.plan(body, withAccents: addAccents && selectedStyle?.hasAccents != false, withSoundEffects: addSoundEffects)
        isPlanning = false
        if saved { toastCenter.show("Edit planned", style: .success) }
    }

    private func renderPreview() async {
        if let path = await client.renderPreview() {
            open(file: path)
        }
    }

    private func open(file path: String) {
        guard FileManager.default.fileExists(atPath: path) else {
            toastCenter.show("That file isn't there — is the drive connected?", style: .warning)
            return
        }
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    private func chooseSong(musicFolder: String) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.audio]
        panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        panel.prompt = "Choose Song"
        panel.message = "Choose the song for this edit. It is copied into the job's music folder."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        songPath = url.path
    }

    // MARK: - Small pieces

    private func sectionLabel(_ text: String) -> some View {
        Text(text).font(PCorpFont.body(10.5)).tracking(1.2).foregroundStyle(theme.textTertiary)
    }

    private func fieldLabel(_ text: String) -> some View {
        Text(text).font(PCorpFont.body(12.5)).fontWeight(.semibold).foregroundStyle(theme.textPrimary)
    }

    private func planLine(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(label).font(PCorpFont.body(11)).foregroundStyle(theme.textTertiary).frame(width: 82, alignment: .leading)
            Text(value).font(PCorpFont.body(11.5)).foregroundStyle(theme.textSecondary).fixedSize(horizontal: false, vertical: true)
        }
    }

    private func messageText(_ text: String, color: Color) -> some View {
        Text(text).font(PCorpFont.body(11.5)).foregroundStyle(color).fixedSize(horizontal: false, vertical: true)
    }

    private func numberField(_ placeholder: String, text: Binding<String>) -> some View {
        TextField(placeholder, text: text)
            .textFieldStyle(.plain)
            .font(PCorpFont.body(12))
            .padding(6)
            .frame(width: 80)
            .cardSurface(radius: 6)
    }

    /// "2026-10-09T08:19:08" (the backend's local time) -> "9 Oct, 08:19".
    static func friendlyTime(_ iso: String) -> String {
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "en_US_POSIX")
        parser.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        guard let date = parser.date(from: iso) else { return iso }
        let out = DateFormatter()
        out.dateFormat = "d MMM, HH:mm"
        return out.string(from: date)
    }
}

/// One clip in the opening-clip picker: a still, its file name, and what it shows if that's known.
private struct ClipCell: View {
    let clip: EditClipOption
    let thumbURL: URL
    let selected: Bool
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            AsyncImage(url: thumbURL) { phase in
                switch phase {
                case .success(let image):
                    image.resizable().scaledToFill()
                case .failure:
                    Image(systemName: "film").foregroundStyle(theme.textTertiary)
                default:
                    ProgressView().controlSize(.small)
                }
            }
            .frame(width: 84, height: 120)
            .background(theme.surface)
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(selected ? theme.accent : theme.surfaceBorder, lineWidth: selected ? 3 : 1))
            .overlay(alignment: .topTrailing) {
                if selected {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(theme.accent).background(Circle().fill(theme.background)).padding(4)
                }
            }
            Text(clip.name).font(PCorpFont.body(9)).foregroundStyle(theme.textSecondary).lineLimit(1)
            if !clip.scene.isEmpty {
                Text(clip.scene).font(PCorpFont.body(9)).foregroundStyle(theme.textTertiary).lineLimit(2).fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(width: 84, alignment: .topLeading)
        .contentShape(Rectangle())
    }
}
