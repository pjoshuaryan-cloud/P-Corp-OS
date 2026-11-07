import CoreImage.CIFilterBuiltins
import SwiftUI
#if os(iOS)
import VisionKit
#else
import AppKit
#endif

/// The private journal inside Personal (2026-11-07), the same screen on iPhone and Mac. It locks when he leaves it, when the app goes to the
/// background (iPhone) or loses focus (Mac), and after five minutes untouched. While the iPhone app is in the app switcher it shows nothing.
public struct JournalView: View {
    private enum Composer { case voice, text }
    private struct Recorded { let url: URL; let duration: TimeInterval }

    @StateObject private var vault = JournalVault()
    @StateObject private var recorder = JournalRecorder()
    @StateObject private var player = JournalPlayer()
    @Environment(\.appTheme) private var theme
    #if os(iOS)
    @Environment(\.scenePhase) private var scenePhase
    #endif

    private let onClose: () -> Void

    @State private var filter: String?
    @State private var search = ""
    @State private var composer: Composer?
    @State private var recorded: Recorded?
    @State private var draftCategory = ""
    @State private var draftTitle = ""
    @State private var draftText = ""
    @State private var expandedID: String?
    /// The note being changed, when the write box is open on one that's already saved.
    @State private var editing: JournalEntry?
    @State private var confirmDeleteID: String?
    @State private var editingCategories = false
    @State private var categoryDraft: [String] = []
    @State private var newCategory = ""
    @State private var shownCode: String?
    @State private var typedCode = ""
    @State private var lastGroupCheck = ""
    @State private var scanning = false
    @State private var confirmForget = false
    /// How far back each highlight card has been stepped: 0 is the latest.
    @State private var weekStep = 0
    @State private var monthStep = 0
    /// Highlight cards are folded to a line until tapped, so writing a quick note never means scrolling past them.
    @State private var openHighlights: Set<JournalPeriod.Kind> = []
    @State private var remindersOn = JournalReminders.enabled

    public init(onClose: @escaping () -> Void) {
        self.onClose = onClose
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(theme.divider)
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let message = vault.message {
                        Text(message).font(PCorpFont.body(12.5)).foregroundStyle(theme.statusRisk)
                    }
                    content
                }
                .padding(20)
                .frame(maxWidth: 720, alignment: .leading)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(theme.background)
        .overlay { privacyCover }
        .simultaneousGesture(TapGesture().onEnded { vault.touch() })
        .task {
            JournalRecorder.clearLeftovers()
            await vault.load()
            if vault.phase == .locked { await vault.unlock() }
        }
        .onDisappear { closeUp() }
        .onChange(of: vault.phase) { _, phase in
            if phase != .open { dropDrafts() }
        }
        .onChange(of: recorder.elapsed) { _, _ in vault.touch() }
        .onChange(of: draftText) { _, _ in vault.touch() }
        #if os(iOS)
        .onChange(of: scenePhase) { _, phase in
            if phase == .background { closeUp() }
        }
        #else
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didResignActiveNotification)) { _ in
            if !vault.authenticating { closeUp() }
        }
        #endif
    }

    /// Nothing readable while the iPhone app is in the app switcher.
    @ViewBuilder private var privacyCover: some View {
        #if os(iOS)
        if scenePhase != .active && !vault.authenticating {
            ZStack {
                theme.background
                Image(systemName: "lock.fill").font(.system(size: 28)).foregroundStyle(theme.textTertiary)
            }
        }
        #endif
    }

    private func closeUp() {
        if recorder.isRecording { recorder.cancel() }
        player.stop()
        dropDrafts()
        shownCode = nil
        search = ""
        expandedID = nil
        confirmDeleteID = nil
        confirmForget = false
        weekStep = 0
        monthStep = 0
        openHighlights = []
        vault.lock()
    }

    private func dropDrafts() {
        if recorder.isRecording { recorder.cancel() }
        if let recorded { JournalRecorder.discard(recorded.url) }
        recorded = nil
        composer = nil
        editing = nil
        draftText = ""
        draftTitle = ""
        shownCode = nil
        editingCategories = false
    }

    // ---- header

    private var header: some View {
        HStack(spacing: 12) {
            Button {
                closeUp()
                onClose()
            } label: {
                Image(systemName: "chevron.left").font(.system(size: 14, weight: .semibold))
            }
            .buttonStyle(.plain)
            .foregroundStyle(theme.textSecondary)
            .accessibilityLabel("Back to Personal")
            VStack(alignment: .leading, spacing: 2) {
                Text("Journal").font(PCorpFont.display(22)).foregroundStyle(theme.textPrimary)
                Text("Private. Only your iPhone and Mac can read it.").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
            }
            Spacer()
            if vault.phase == .open {
                Menu {
                    Button("Show recovery key") { Task { shownCode = await vault.recoveryCode() } }
                    Button("Categories") { categoryDraft = vault.categories; editingCategories = true }
                    if JournalReminders.supported {
                        Button(remindersOn ? "Turn weekly and monthly reminders off" : "Turn weekly and monthly reminders on") {
                            JournalReminders.enabled.toggle()
                            remindersOn = JournalReminders.enabled
                        }
                    }
                    Button("Remove from this device", role: .destructive) { confirmForget = true }
                } label: {
                    Image(systemName: "ellipsis.circle").font(.system(size: 16))
                }
                .menuStyle(.button)
                .buttonStyle(.plain)
                .fixedSize()
                Button {
                    closeUp()
                } label: {
                    Label("Lock", systemImage: "lock.fill").font(PCorpFont.body(12, weight: .medium))
                }
                .buttonStyle(.actionTinted)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
    }

    // ---- what to show

    @ViewBuilder private var content: some View {
        switch vault.phase {
        case .checking:
            ProgressView().frame(maxWidth: .infinity)
        case .fresh:
            freshCard
        case .elsewhere:
            restoreCard(intro: "Your journal is on your other device. Open it here with your recovery key.")
        case .writeDown(let code):
            writeDownCard(code)
        case .locked:
            lockedCard
        case .offline:
            card {
                Text("No signal, so I can't tell whether you already have a journal.").font(PCorpFont.body(13)).foregroundStyle(theme.textPrimary)
                AsyncButton(action: { await vault.load() }) { Text("Try again") }.buttonStyle(.actionFilled)
            }
        case .open:
            openJournal
        }
    }

    private func card<Content: View>(@ViewBuilder _ body: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12, content: body)
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .cardSurface(radius: Radius.md)
    }

    private var freshCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            card {
                Text("A journal only you can read").font(PCorpFont.body(15, weight: .semibold)).foregroundStyle(theme.textPrimary)
                Text("Voice notes and writing, in categories you choose. It's encrypted on this device before it's saved, so the server, Frank and anyone else see only scrambled data. You open it with Face ID or Touch ID.")
                    .font(PCorpFont.body(12.5)).foregroundStyle(theme.textSecondary)
                Text("You'll get a recovery key to write down. It's the only way back in if you lose both your iPhone and your Mac, and nobody else can recover it for you.")
                    .font(PCorpFont.body(12.5)).foregroundStyle(theme.textSecondary)
                AsyncButton(action: { await vault.start() }) { Text("Start my journal") }
                    .buttonStyle(.actionFilled)
                    .disabled(vault.busy)
            }
            restoreCard(intro: "Already started one on your other device? Open it here with its recovery key.")
        }
    }

    private func restoreCard(intro: String) -> some View {
        card {
            Text(intro).font(PCorpFont.body(12.5)).foregroundStyle(theme.textSecondary)
            TextField("Recovery key", text: $typedCode, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .font(PCorpFont.mono(13))
                .autocorrectionDisabled()
                #if os(iOS)
                .textInputAutocapitalization(.characters)
                #endif
            HStack(spacing: 8) {
                AsyncButton(action: { await vault.restore(code: typedCode) }) { Text("Open journal") }
                    .buttonStyle(.actionFilled)
                    .disabled(typedCode.count < 20 || vault.busy)
                #if os(iOS)
                if DataScannerViewController.isSupported {
                    Button("Scan from your Mac") { scanning = true }.buttonStyle(.actionTinted)
                }
                #endif
            }
            #if os(iOS)
            if scanning {
                JournalCodeScanner { code in
                    scanning = false
                    typedCode = code
                    Task { await vault.restore(code: code) }
                }
                .frame(height: 280)
                .clipShape(RoundedRectangle(cornerRadius: Radius.sm))
                Text("On your Mac: Journal, the … menu, Show recovery key.").font(PCorpFont.body(11.5)).foregroundStyle(theme.textTertiary)
                Button("Stop scanning") { scanning = false }.buttonStyle(.actionTinted)
            }
            #endif
        }
    }

    private func writeDownCard(_ code: String) -> some View {
        let lastGroup = String(code.split(separator: "-").last ?? "")
        return card {
            Text("Write down your recovery key").font(PCorpFont.body(15, weight: .semibold)).foregroundStyle(theme.textPrimary)
            Text("Keep it somewhere safe, away from your phone. It opens your journal on a new device, and if you lose both your iPhone and your Mac, it's the only way back in.")
                .font(PCorpFont.body(12.5)).foregroundStyle(theme.textSecondary)
            codeBlock(code)
            Text("Type its last group to show you've written it down.").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
            TextField(String(repeating: "•", count: lastGroup.count), text: $lastGroupCheck)
                .textFieldStyle(.roundedBorder)
                .font(PCorpFont.mono(13))
                .autocorrectionDisabled()
                #if os(iOS)
                .textInputAutocapitalization(.characters)
                #endif
                .frame(maxWidth: 160)
            AsyncButton(action: {
                lastGroupCheck = ""
                await vault.wroteItDown()
            }) { Text("I've written it down") }
                .buttonStyle(.actionFilled)
                .disabled(JournalCrypto.tidied(lastGroupCheck) != lastGroup)
        }
    }

    private func codeBlock(_ code: String) -> some View {
        Text(code)
            .font(PCorpFont.mono(15, weight: .semibold))
            .foregroundStyle(theme.textPrimary)
            .textSelection(.enabled)
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(theme.surfaceElevated, in: RoundedRectangle(cornerRadius: Radius.sm))
    }

    private var lockedCard: some View {
        card {
            HStack(spacing: 10) {
                Image(systemName: "lock.fill").foregroundStyle(theme.textSecondary)
                Text("Your journal is locked").font(PCorpFont.body(14, weight: .semibold)).foregroundStyle(theme.textPrimary)
            }
            AsyncButton(action: { await vault.unlock() }) { Text("Unlock") }.buttonStyle(.actionFilled)
        }
    }

    // ---- the journal itself

    private var shown: [JournalEntry] {
        vault.entries.filter { (filter == nil || $0.category == filter) && $0.matches(search) }
    }

    @ViewBuilder private var openJournal: some View {
        if let code = shownCode { recoveryCard(code) }
        if editingCategories { categoryEditor }
        if confirmForget { forgetCard }
        if let note = vault.syncNote {
            Text(note).font(PCorpFont.body(11.5)).foregroundStyle(theme.textTertiary)
        }
        highlightCard(.week, step: $weekStep)
        highlightCard(.month, step: $monthStep)
        composeArea
        if let notice = vault.notice {
            Text(notice).font(PCorpFont.body(11.5)).foregroundStyle(theme.textTertiary)
        }
        filters
        TextField("Search your journal", text: $search)
            .textFieldStyle(.roundedBorder)
            .font(PCorpFont.body(13))
            .autocorrectionDisabled()
        if shown.isEmpty {
            Text(vault.entries.isEmpty ? "Nothing here yet. Record a voice note or write something." : "Nothing matches.")
                .font(PCorpFont.body(12.5)).foregroundStyle(theme.textSecondary)
                .padding(.top, 8)
        } else {
            VStack(spacing: 8) {
                ForEach(shown) { entry in entryRow(entry) }
            }
        }
    }

    private func recoveryCard(_ code: String) -> some View {
        card {
            Text("Your recovery key").font(PCorpFont.body(14, weight: .semibold)).foregroundStyle(theme.textPrimary)
            codeBlock(code)
            #if os(macOS)
            if let qr = JournalQR.image(for: code) {
                Text("To open the journal on your iPhone: Personal, Journal, Scan from your Mac.").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                Image(decorative: qr, scale: 1).interpolation(.none).resizable().frame(width: 200, height: 200)
            }
            #endif
            Text("Anyone with this key can read your journal. Hide it when you're done.").font(PCorpFont.body(11.5)).foregroundStyle(theme.statusHot)
            Button("Hide") { shownCode = nil }.buttonStyle(.actionTinted)
        }
    }

    private var forgetCard: some View {
        card {
            Text("Remove the journal from this device?").font(PCorpFont.body(14, weight: .semibold)).foregroundStyle(theme.textPrimary)
            Text("This device forgets the key and its copy. Your other device and the server keep everything, and your recovery key opens it here again.")
                .font(PCorpFont.body(12.5)).foregroundStyle(theme.textSecondary)
            HStack(spacing: 8) {
                AsyncButton(action: {
                    confirmForget = false
                    await vault.forgetThisDevice()
                }) { Text("Remove from this device") }.buttonStyle(.actionFilled)
                Button("Cancel") { confirmForget = false }.buttonStyle(.actionTinted)
            }
        }
    }

    private var categoryEditor: some View {
        card {
            Text("Categories").font(PCorpFont.body(14, weight: .semibold)).foregroundStyle(theme.textPrimary)
            ForEach(Array(categoryDraft.enumerated()), id: \.offset) { index, name in
                HStack {
                    Text(name).font(PCorpFont.body(13)).foregroundStyle(theme.textPrimary)
                    Spacer()
                    if categoryDraft.count > 1 {
                        Button { categoryDraft.remove(at: index) } label: { Image(systemName: "minus.circle") }
                            .buttonStyle(.plain).foregroundStyle(theme.statusRisk)
                            .accessibilityLabel("Remove \(name)")
                    }
                }
            }
            HStack {
                TextField("New category", text: $newCategory).textFieldStyle(.roundedBorder).font(PCorpFont.body(13))
                Button("Add") {
                    let name = newCategory.trimmingCharacters(in: .whitespacesAndNewlines)
                    if !name.isEmpty { categoryDraft.append(name) }
                    newCategory = ""
                }
                .buttonStyle(.actionTinted)
                .disabled(newCategory.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            Text("Removing a category doesn't delete its notes. They keep their label and still show under All.").font(PCorpFont.body(11.5)).foregroundStyle(theme.textTertiary)
            HStack(spacing: 8) {
                AsyncButton(action: {
                    await vault.setCategories(categoryDraft)
                    editingCategories = false
                }) { Text("Save") }.buttonStyle(.actionFilled)
                Button("Cancel") { editingCategories = false }.buttonStyle(.actionTinted)
            }
        }
    }

    // ---- writing and recording

    @ViewBuilder private var composeArea: some View {
        switch composer {
        case nil:
            HStack(spacing: 10) {
                AsyncButton(action: startRecording) { Label("Record", systemImage: "mic.fill") }.buttonStyle(.actionFilled)
                Button {
                    vault.notice = nil
                    draftCategory = ""
                    composer = .text
                } label: { Label("Write", systemImage: "square.and.pencil") }
                .buttonStyle(.actionTinted)
            }
        case .voice:
            card {
                if recorder.isRecording {
                    HStack(spacing: 10) {
                        Circle().fill(theme.statusRisk).frame(width: 10, height: 10)
                        Text("Recording \(Self.clock(recorder.elapsed))").font(PCorpFont.mono(14)).foregroundStyle(theme.textPrimary)
                    }
                    HStack(spacing: 8) {
                        Button("Stop") { stopRecording() }.buttonStyle(.actionFilled)
                        Button("Discard") { dropDrafts() }.buttonStyle(.actionTinted)
                    }
                } else if let recorded {
                    Text("Voice note, \(Self.clock(recorded.duration))").font(PCorpFont.body(14, weight: .semibold)).foregroundStyle(theme.textPrimary)
                    detailsFields
                    Text(vault.busy ? "Saving, and working out the words on this device…" : "The words are worked out on this device. Nothing is sent anywhere to do it.")
                        .font(PCorpFont.body(11.5)).foregroundStyle(theme.textTertiary)
                    HStack(spacing: 8) {
                        AsyncButton(action: {
                            let made = recorded
                            self.recorded = nil
                            await vault.addVoiceNote(file: made.url, duration: made.duration, category: draftCategory.isEmpty ? nil : draftCategory, title: draftTitle)
                            dropDrafts()
                        }) { Text("Save voice note") }.buttonStyle(.actionFilled).disabled(vault.busy)
                        Button("Discard") { dropDrafts() }.buttonStyle(.actionTinted)
                    }
                }
            }
        case .text:
            card {
                if editing != nil {
                    Text("Edit note").font(PCorpFont.body(14, weight: .semibold)).foregroundStyle(theme.textPrimary)
                }
                detailsFields
                TextEditor(text: $draftText)
                    .font(PCorpFont.body(14))
                    .frame(minHeight: 140)
                    .padding(6)
                    .overlay(alignment: .topLeading) {
                        if draftText.isEmpty {
                            Text("What's on your mind?")
                                .font(PCorpFont.body(14))
                                .foregroundStyle(theme.textTertiary)
                                .padding(.horizontal, 11)
                                .padding(.vertical, 14)
                                .allowsHitTesting(false)
                        }
                    }
                    .overlay(RoundedRectangle(cornerRadius: Radius.sm).stroke(theme.surfaceBorder, lineWidth: 1))
                    .background(theme.surfaceElevated, in: RoundedRectangle(cornerRadius: Radius.sm))
                HStack(spacing: 8) {
                    AsyncButton(action: {
                        if var changed = editing {
                            if !draftCategory.isEmpty { changed.category = draftCategory }
                            changed.title = draftTitle
                            changed.text = draftText
                            await vault.save(changed, sort: draftCategory.isEmpty)
                        } else {
                            await vault.save(JournalEntry(category: draftCategory, title: draftTitle, text: draftText), sort: draftCategory.isEmpty)
                        }
                        dropDrafts()
                    }) { Text("Save") }
                        .buttonStyle(.actionFilled)
                        .disabled(editing?.audioID == nil && draftText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && draftTitle.trimmingCharacters(in: .whitespaces).isEmpty)
                    Button("Cancel") { dropDrafts() }.buttonStyle(.actionTinted)
                }
            }
        }
    }

    private var detailsFields: some View {
        VStack(alignment: .leading, spacing: 8) {
            Picker("Category", selection: $draftCategory) {
                Text("Sort it for me").tag("")
                ForEach(vault.categories, id: \.self) { Text($0).tag($0) }
            }
            .pickerStyle(.menu)
            TextField("Title (optional)", text: $draftTitle).textFieldStyle(.roundedBorder).font(PCorpFont.body(13))
        }
    }

    /// Opens the write box on a saved note: its words, title and category. A voice note keeps its recording and what was worked out from it.
    private func startEditing(_ entry: JournalEntry) {
        dropDrafts()
        editing = entry
        draftCategory = entry.category
        draftTitle = entry.title
        draftText = entry.text
        expandedID = nil
        confirmDeleteID = nil
        composer = .text
    }

    private func startRecording() async {
        vault.message = nil
        vault.notice = nil
        draftCategory = ""
        if let problem = await recorder.start() {
            vault.message = problem
            return
        }
        composer = .voice
    }

    private func stopRecording() {
        guard let made = recorder.stop() else { return }
        recorded = Recorded(url: made.url, duration: made.duration)
    }

    private var filters: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                chip("All", selected: filter == nil) { filter = nil }
                ForEach(vault.categories, id: \.self) { name in
                    chip(name, selected: filter == name) { filter = name }
                }
            }
        }
    }

    private func chip(_ title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(PCorpFont.body(12, weight: selected ? .semibold : .regular))
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(selected ? theme.accentFill : theme.surfaceElevated, in: Capsule())
                .foregroundStyle(selected ? theme.accentText : theme.textPrimary)
        }
        .buttonStyle(.plain)
    }

    // ---- highlights

    @ViewBuilder private func highlightCard(_ kind: JournalPeriod.Kind, step: Binding<Int>) -> some View {
        let list = vault.periods(kind)
        if !list.isEmpty {
            let index = min(step.wrappedValue, list.count - 1)
            let period = list[index]
            let digest = vault.digest(period)
            let written = vault.written(period)
            let isOpen = openHighlights.contains(kind)
            card {
                HStack(alignment: .top, spacing: 8) {
                    Button {
                        if isOpen { openHighlights.remove(kind) } else { openHighlights.insert(kind) }
                    } label: {
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: isOpen ? "chevron.down" : "chevron.right").font(.system(size: 11, weight: .semibold)).foregroundStyle(theme.textTertiary).padding(.top, 4)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(period.title).font(PCorpFont.body(14.5, weight: .semibold)).foregroundStyle(theme.textPrimary)
                                Text(isOpen ? period.span : period.span + " · " + Self.preview(digest, written)).font(PCorpFont.body(11.5)).foregroundStyle(theme.textTertiary).lineLimit(1)
                            }
                            Spacer(minLength: 0)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(isOpen ? "Fold \(period.title)" : "Open \(period.title)")
                    Button { step.wrappedValue = index + 1 } label: { Image(systemName: "chevron.left") }
                        .buttonStyle(.plain).foregroundStyle(theme.textSecondary)
                        .disabled(index + 1 >= list.count).opacity(index + 1 >= list.count ? 0.3 : 1)
                        .accessibilityLabel(kind == .week ? "Earlier week" : "Earlier month")
                    Button { step.wrappedValue = index - 1 } label: { Image(systemName: "chevron.right") }
                        .buttonStyle(.plain).foregroundStyle(theme.textSecondary)
                        .disabled(index == 0).opacity(index == 0 ? 0.3 : 1)
                        .accessibilityLabel(kind == .week ? "Later week" : "Later month")
                }
                if !isOpen {
                    EmptyView()
                } else if let written {
                    Text(written.summary).font(PCorpFont.body(13.5)).foregroundStyle(theme.textPrimary).fixedSize(horizontal: false, vertical: true)
                } else if vault.writingHighlights.contains(period.id) {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text(Self.writingLine).font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                    }
                }
                if isOpen {
                Text(Self.countLine(digest)).font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                if let mood = digest.moodLine {
                    Text(mood).font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                }
                if !digest.themes.isEmpty {
                    Text("You kept coming back to: " + digest.themes.joined(separator: ", ")).font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                }
                if let written, !written.remember.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("WORTH REMEMBERING").font(PCorpFont.label(9.5)).foregroundStyle(theme.textTertiary)
                        ForEach(written.remember, id: \.self) { item in
                            Text("• " + item).font(PCorpFont.body(12.5)).foregroundStyle(theme.textPrimary).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                if !digest.standouts.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("IN YOUR WORDS").font(PCorpFont.label(9.5)).foregroundStyle(theme.textTertiary)
                        ForEach(digest.standouts, id: \.self) { line in
                            Text("“" + line + "”").font(PCorpFont.body(12.5)).italic().foregroundStyle(theme.textPrimary).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                if written == nil && !JournalModel.available {
                    Text("A written summary is added when you open your journal on your Mac.").font(PCorpFont.body(11)).foregroundStyle(theme.textTertiary)
                }
                }
            }
            .task(id: period.id + digest.basis) { await vault.writeHighlight(period) }
        }
    }

    #if os(macOS)
    private static let writingLine = "Writing a summary on this Mac…"
    #else
    private static let writingLine = "Writing a summary on this iPhone…"
    #endif

    /// The one line a folded card shows: the start of the Mac's summary, or the counts.
    private static func preview(_ d: JournalDigest, _ written: JournalHighlight?) -> String {
        if let written { return written.summary }
        var bits = [d.notes == 1 ? "1 note" : "\(d.notes) notes"]
        if d.mood != nil, let line = d.moodLine?.replacingOccurrences(of: "Mood: ", with: "").split(separator: ".").first { bits.append(String(line)) }
        if !d.themes.isEmpty { bits.append(d.themes.prefix(2).joined(separator: ", ")) }
        return bits.joined(separator: " · ")
    }

    private static func countLine(_ d: JournalDigest) -> String {
        var parts = [d.notes == 1 ? "1 note" : "\(d.notes) notes"]
        if d.voiceNotes > 0 {
            let voice = d.voiceNotes == 1 ? "1 voice note" : "\(d.voiceNotes) voice notes"
            parts.append(d.voiceMinutes > 0 ? "\(voice) (\(d.voiceMinutes) min)" : voice)
        }
        let line = parts.joined(separator: " · ")
        let cats = d.categories.map { "\($0.category) \($0.notes)" }.joined(separator: " · ")
        return cats.isEmpty ? line : line + "\n" + cats
    }

    // ---- one note

    private func entryRow(_ entry: JournalEntry) -> some View {
        let open = expandedID == entry.id
        return VStack(alignment: .leading, spacing: 8) {
            Button {
                expandedID = open ? nil : entry.id
                confirmDeleteID = nil
            } label: {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        Text(entry.category.uppercased()).font(PCorpFont.label(9.5)).foregroundStyle(theme.accent)
                        if entry.audioID != nil {
                            Label(Self.clock(entry.duration ?? 0), systemImage: "waveform").font(PCorpFont.body(11)).foregroundStyle(theme.textTertiary)
                        }
                        Spacer()
                        Text(entry.createdAt, format: .dateTime.day().month(.abbreviated).hour().minute()).font(PCorpFont.body(11)).foregroundStyle(theme.textTertiary)
                    }
                    Text(Self.headline(entry)).font(PCorpFont.body(13.5, weight: .medium)).foregroundStyle(theme.textPrimary).lineLimit(open ? nil : 2).multilineTextAlignment(.leading)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if open { entryDetail(entry) }
        }
        .padding(14)
        .cardSurface(radius: Radius.md)
    }

    @ViewBuilder private func entryDetail(_ entry: JournalEntry) -> some View {
        if !entry.title.isEmpty && !entry.text.isEmpty {
            Text(entry.text).font(PCorpFont.body(13.5)).foregroundStyle(theme.textPrimary).textSelection(.enabled)
        }
        if let transcript = entry.transcript, !entry.title.isEmpty || !entry.text.isEmpty {
            Text(transcript).font(PCorpFont.body(13.5)).foregroundStyle(theme.textPrimary).textSelection(.enabled)
        }
        if entry.audioID != nil && entry.transcript == nil {
            Text("No words were worked out for this one on the device it was recorded on. Play it to hear it.").font(PCorpFont.body(11.5)).foregroundStyle(theme.textTertiary)
        }
        // One row when it fits; on a narrow phone, delete moves to its own line rather than squeezing a button until its word breaks.
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) {
                mainActions(entry)
                Spacer(minLength: 8)
                deleteActions(entry)
            }
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) { mainActions(entry) }
                HStack(spacing: 8) { deleteActions(entry) }
            }
        }
    }

    @ViewBuilder private func mainActions(_ entry: JournalEntry) -> some View {
        if entry.audioID != nil {
            AsyncButton(action: {
                if player.playingID == entry.id {
                    player.stop()
                } else if let audio = await vault.audio(for: entry) {
                    player.play(audio, id: entry.id)
                }
            }) { Label(player.playingID == entry.id ? "Stop" : "Play", systemImage: player.playingID == entry.id ? "stop.fill" : "play.fill").lineLimit(1) }
            .buttonStyle(.actionFilled)
            .fixedSize()
        }
        if confirmDeleteID != entry.id {
            Menu {
                ForEach(vault.categories, id: \.self) { name in
                    Button(name) {
                        var moved = entry
                        moved.category = name
                        Task { await vault.save(moved) }
                    }
                }
            } label: { Text("Category").lineLimit(1) }
            .menuStyle(.button)
            .fixedSize()
            Button { startEditing(entry) } label: { Text("Edit").lineLimit(1) }.buttonStyle(.actionTinted).fixedSize()
        }
    }

    @ViewBuilder private func deleteActions(_ entry: JournalEntry) -> some View {
        if confirmDeleteID == entry.id {
            AsyncButton(action: {
                if player.playingID == entry.id { player.stop() }
                await vault.delete(entry)
                confirmDeleteID = nil
            }) { Text("Delete for good").lineLimit(1) }.buttonStyle(.actionFilled).fixedSize()
            Button { confirmDeleteID = nil } label: { Text("Keep").lineLimit(1) }.buttonStyle(.actionTinted).fixedSize()
        } else {
            Button { confirmDeleteID = entry.id } label: { Text("Delete").lineLimit(1) }.buttonStyle(.actionTinted).fixedSize()
        }
    }

    private static func headline(_ entry: JournalEntry) -> String {
        if !entry.title.isEmpty { return entry.title }
        if !entry.text.isEmpty { return entry.text }
        if let transcript = entry.transcript, !transcript.isEmpty { return transcript }
        return "Voice note"
    }

    private static func clock(_ seconds: TimeInterval) -> String {
        let total = Int(seconds.rounded())
        return String(format: "%d:%02d", total / 60, total % 60)
    }
}

#if os(macOS)
/// The recovery key as a QR code, for the iPhone to scan off the Mac's screen.
enum JournalQR {
    static func image(for text: String) -> CGImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(text.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage?.transformed(by: CGAffineTransform(scaleX: 8, y: 8)) else { return nil }
        return CIContext().createCGImage(output, from: output.extent)
    }
}
#endif

#if os(iOS)
/// Reads the recovery key's QR code off the Mac's screen with the camera.
struct JournalCodeScanner: UIViewControllerRepresentable {
    let found: (String) -> Void

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let scanner = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.qr])], qualityLevel: .balanced, recognizesMultipleItems: false, isHighFrameRateTrackingEnabled: false, isHighlightingEnabled: true)
        scanner.delegate = context.coordinator
        try? scanner.startScanning()
        return scanner
    }

    func updateUIViewController(_ controller: DataScannerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(found: found) }

    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        let found: (String) -> Void
        private var done = false
        init(found: @escaping (String) -> Void) { self.found = found }

        func dataScanner(_ dataScanner: DataScannerViewController, didAdd addedItems: [RecognizedItem], allItems: [RecognizedItem]) {
            guard !done else { return }
            for item in addedItems {
                if case .barcode(let code) = item, let text = code.payloadStringValue, (try? JournalCrypto.key(fromRecoveryCode: text)) != nil {
                    done = true
                    dataScanner.stopScanning()
                    found(text)
                    return
                }
            }
        }
    }
}
#endif
