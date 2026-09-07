import SwiftUI

/// Moved here from desktop's own KnowledgeView.swift (2026-08-13) so iOS's
/// Knowledge section can reuse it -- zero platform-specific code to begin
/// with (pure SwiftUI + Foundation's AttributedString), so this was a pure
/// relocation, not a rewrite.
///
/// Tables and fenced code blocks (2026-09-05) -- the two gaps this file's
/// own doc comment used to name explicitly as unsupported. See Chunk below
/// for why the document is no longer always one single Text view.
public struct SimpleMarkdownView: View {
    let text: String
    @Environment(\.appTheme) private var theme

    public init(text: String) {
        self.text = text
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            ForEach(Array(Self.parseChunks(text).enumerated()), id: \.offset) { _, chunk in
                switch chunk {
                case .prose(let blocks):
                    // Real bug found live (2026-08-27): plain SwiftUI Text
                    // isn't selectable by default, and even after enabling
                    // selection, rendering each block (heading/paragraph/
                    // list item) as its own separate Text meant a drag-
                    // select couldn't cross block boundaries -- confirmed
                    // live, selection stopped dead at the edge of whichever
                    // Text it started in. The fix: every consecutive run of
                    // ordinary prose (heading/list/rule/paragraph, with no
                    // table/code in between) still merges into ONE
                    // AttributedString rendered by a single Text, so
                    // selecting/copying a normal reply still works exactly
                    // like selecting a paragraph in any normal document.
                    //
                    // A table or code block was never real selectable text
                    // in the old renderer either -- it just showed as
                    // garbled inline pipe/backtick characters. Splitting
                    // the document at those specific boundaries (2026-09-05,
                    // adding real table/code-block rendering) doesn't
                    // regress the fix above: it only stops a drag-select
                    // from crossing a boundary that previously wasn't a
                    // real content boundary at all. Each CodeBlockView/
                    // TableView gets its own .textSelection(.enabled), so
                    // copying code or table content directly still works --
                    // just no longer as part of one drag spanning a table
                    // and its surrounding prose.
                    Text(Self.proseAttributedText(blocks, theme: theme))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                case .codeBlock(let language, let code):
                    CodeBlockView(language: language, code: code)
                case .table(let header, let rows):
                    TableView(header: header, rows: rows)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// Builds one continuous AttributedString for a single run of prose
    /// blocks (see Chunk.prose) -- was `attributedText`, operating directly
    /// on `self.text`/`self.theme`; now `static` and parameterized, since a
    /// document can contain more than one prose run once tables/code
    /// blocks are mixed in. Heading/list/paragraph styling is per-run font/
    /// color attributes on one string rather than separate Views -- inline
    /// emphasis (bold/italic/links/code) from inline(_:) below still
    /// renders correctly layered on top, since AttributedString's
    /// markdown-parsed `inlinePresentationIntent` attribute is independent
    /// of the `.font`/`.foregroundColor` attributes set here.
    private static func proseAttributedText(_ blocks: [Block], theme: AppTheme) -> AttributedString {
        var result = AttributedString()
        for (index, block) in blocks.enumerated() {
            if index > 0 {
                let tight = isListItem(blocks[index - 1]) && isListItem(block)
                result += AttributedString(tight ? "\n" : "\n\n")
            }
            switch block {
            case .heading(let level, let content):
                var run = inline(content)
                run.font = PCorpFont.display(headingSize(level), weight: .bold)
                run.foregroundColor = theme.textPrimary
                result += run
            case .listItem(let marker, let content):
                var markerRun = AttributedString("\(marker)  ")
                markerRun.font = PCorpFont.body(13)
                markerRun.foregroundColor = theme.textSecondary
                var contentRun = inline(content)
                contentRun.font = PCorpFont.body(13)
                contentRun.foregroundColor = theme.textPrimary
                result += markerRun
                result += contentRun
            case .rule:
                var run = AttributedString(String(repeating: "—", count: 24))
                run.font = PCorpFont.body(10)
                run.foregroundColor = theme.textSecondary.opacity(0.4)
                result += run
            case .paragraph(let content):
                var run = inline(content)
                run.font = PCorpFont.body(13)
                run.foregroundColor = theme.textPrimary
                result += run
            }
        }
        return result
    }

    private static func isListItem(_ block: Block) -> Bool {
        if case .listItem = block { return true }
        return false
    }

    private static func headingSize(_ level: Int) -> CGFloat {
        switch level {
        case 1: return 22
        case 2: return 17
        default: return 14
        }
    }

    /// `static` (was an instance method) so TableView's cell rendering can
    /// reuse the exact same inline-parsing logic without duplicating it.
    ///
    /// Inline code spans (single backticks, `` `like_this` ``) -- real,
    /// easy fix included alongside tables/code blocks (2026-09-05):
    /// `.inlineOnlyPreservingWhitespace` already parses these into an
    /// `inlinePresentationIntent` of `.code`, but plain SwiftUI Text
    /// doesn't automatically render that as monospace on its own -- verified
    /// directly, a bare backtick span rendered with the backticks stripped
    /// but no font change at all. Ranges are collected first, then mutated,
    /// rather than mutating `result` while iterating its own `runs` view.
    fileprivate static func inline(_ raw: String) -> AttributedString {
        var options = AttributedString.MarkdownParsingOptions()
        options.interpretedSyntax = .inlineOnlyPreservingWhitespace
        var result = (try? AttributedString(markdown: raw, options: options)) ?? AttributedString(raw)
        let codeRanges = result.runs
            .filter { $0.inlinePresentationIntent?.contains(.code) == true }
            .map(\.range)
        for range in codeRanges {
            result[range].font = PCorpFont.mono(13)
        }
        return result
    }

    private enum Block {
        case heading(level: Int, text: String)
        case listItem(marker: String, text: String)
        case rule
        case paragraph(text: String)
    }

    /// A document is a sequence of chunks, not a flat list of blocks --
    /// see body's own comment on why tables/code blocks can't just be more
    /// attributed runs in the single prose Text.
    private enum Chunk {
        case prose([Block])
        case codeBlock(language: String?, code: String)
        case table(header: [String], rows: [[String]])
    }

    private static func parseChunks(_ text: String) -> [Chunk] {
        var chunks: [Chunk] = []
        var blocks: [Block] = []
        // Real bug found live (2026-08-27): every non-empty line became
        // its own separate `.paragraph` block, and therefore its own
        // separate Text view -- .textSelection(.enabled) selects within
        // one Text at a time, so a normal multi-sentence reply (which
        // streams in as plain wrapped lines, not one per sentence) could
        // only ever be copied one line at a time. Consecutive plain
        // lines now accumulate into a single paragraph (standard
        // markdown "soft wrap" behavior -- only a blank line, heading,
        // list item, rule, code fence, or table actually starts a new
        // block), joined with a space, so ordinary prose renders and
        // selects as one continuous block again.
        var paragraphLines: [String] = []

        func flushParagraph() {
            guard !paragraphLines.isEmpty else { return }
            blocks.append(.paragraph(text: paragraphLines.joined(separator: " ")))
            paragraphLines = []
        }
        func flushProse() {
            flushParagraph()
            guard !blocks.isEmpty else { return }
            chunks.append(.prose(blocks))
            blocks = []
        }

        let lines = text.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        var i = 0
        while i < lines.count {
            let trimmed = lines[i].trimmingCharacters(in: .whitespaces)

            if trimmed.hasPrefix("```") {
                flushProse()
                let language = String(trimmed.dropFirst(3)).trimmingCharacters(in: .whitespaces)
                var codeLines: [String] = []
                i += 1
                // Real, deliberate case: an unterminated fence (no closing
                // ``` before EOF) still flushes whatever was accumulated as
                // a code block -- this is exactly what a still-streaming
                // reply looks like at every render before its closing fence
                // has arrived, and losing that content (or dumping raw
                // backticks into a paragraph) would be worse than showing
                // an in-progress code block that keeps growing.
                while i < lines.count {
                    let bodyTrimmed = lines[i].trimmingCharacters(in: .whitespaces)
                    if bodyTrimmed == "```" {
                        i += 1
                        break
                    }
                    codeLines.append(lines[i]) // verbatim, not trimmed -- indentation is significant
                    i += 1
                }
                chunks.append(.codeBlock(language: language.isEmpty ? nil : language, code: codeLines.joined(separator: "\n")))
                continue
            }

            if isTableRow(trimmed), i + 1 < lines.count, isTableSeparator(lines[i + 1].trimmingCharacters(in: .whitespaces)) {
                flushProse()
                let header = tableCells(trimmed)
                i += 2 // header + confirmed separator row
                var rows: [[String]] = []
                while i < lines.count {
                    let rowTrimmed = lines[i].trimmingCharacters(in: .whitespaces)
                    guard isTableRow(rowTrimmed) else { break }
                    rows.append(tableCells(rowTrimmed))
                    i += 1
                }
                // Ragged rows (fewer cells than the widest row) get padded
                // rather than left to break Grid's column alignment -- same
                // "never crash, degrade to something reasonable" precedent
                // already used by backend/app/documents.py's own markdown
                // table parser.
                let width = max(header.count, rows.map(\.count).max() ?? 0)
                chunks.append(.table(header: pad(header, to: width), rows: rows.map { pad($0, to: width) }))
                continue
            }

            if trimmed.isEmpty {
                flushParagraph()
            } else if trimmed == "---" {
                flushParagraph()
                blocks.append(.rule)
            } else if trimmed.hasPrefix("#") {
                flushParagraph()
                let level = trimmed.prefix(while: { $0 == "#" }).count
                let content = trimmed.drop(while: { $0 == "#" }).trimmingCharacters(in: .whitespaces)
                blocks.append(.heading(level: min(level, 3), text: content))
            } else if trimmed.hasPrefix("- ") || trimmed.hasPrefix("* ") {
                flushParagraph()
                blocks.append(.listItem(marker: "•", text: String(trimmed.dropFirst(2))))
            } else if let numberedMatch = trimmed.range(of: #"^\d+\.\s"#, options: .regularExpression) {
                flushParagraph()
                let marker = String(trimmed[numberedMatch]).trimmingCharacters(in: .whitespaces)
                blocks.append(.listItem(marker: marker, text: String(trimmed[numberedMatch.upperBound...])))
            } else {
                paragraphLines.append(trimmed)
            }
            i += 1
        }
        flushProse()
        return chunks
    }

    /// A candidate table row -- confirmed as a real table only once the
    /// NEXT line passes isTableSeparator below. Requiring a leading `|` is
    /// a deliberately stricter bar than "any line containing a pipe" --
    /// "the plan costs $10 | $15 depending on tier" must fall through to
    /// plain text, not become a one-row table.
    private static func isTableRow(_ trimmed: String) -> Bool {
        guard trimmed.hasPrefix("|") else { return false }
        return trimmed.dropFirst().contains("|")
    }

    /// The actual disambiguator between a real table and a stray pipe --
    /// every cell must be pure dashes with optional leading/trailing colons
    /// (`---`, `:---`, `---:`, `:---:`), matching standard markdown table
    /// syntax's alignment-marker row. Alignment itself isn't acted on here,
    /// just accepted so it doesn't disqualify an otherwise-valid row.
    private static func isTableSeparator(_ trimmed: String) -> Bool {
        guard trimmed.hasPrefix("|") else { return false }
        let cells = tableCells(trimmed)
        guard !cells.isEmpty else { return false }
        return cells.allSatisfy { $0.range(of: #"^:?-+:?$"#, options: .regularExpression) != nil }
    }

    private static func tableCells(_ trimmed: String) -> [String] {
        var line = trimmed
        if line.hasPrefix("|") { line.removeFirst() }
        if line.hasSuffix("|") { line.removeLast() }
        return line.split(separator: "|", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespaces) }
    }

    private static func pad(_ cells: [String], to width: Int) -> [String] {
        guard cells.count < width else { return cells }
        return cells + Array(repeating: "", count: width - cells.count)
    }
}

/// A fenced code block -- verbatim monospace text, never run through the
/// inline bold/italic/link parser (real code containing a literal
/// `_foo_` or `**kwargs` must never be misread as emphasis syntax).
private struct CodeBlockView: View {
    let language: String?
    let code: String
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let language, !language.isEmpty {
                Text(language.uppercased())
                    .font(PCorpFont.label(9))
                    .foregroundStyle(theme.textTertiary)
                    .trackedLabel()
                    .padding(.horizontal, 12)
                    .padding(.top, 8)
            }
            // showsIndicators: true here (unlike TableView's own default
            // elsewhere in this file being the same) -- a visible
            // scrollbar matters more on a narrow chat bubble than it would
            // on Knowledge's full-width page, where this same view is also
            // used, since there's less room for a long line to fit without
            // scrolling at all.
            ScrollView(.horizontal, showsIndicators: true) {
                Text(code)
                    .font(PCorpFont.mono(12))
                    .foregroundStyle(theme.textPrimary)
                    .textSelection(.enabled)
                    .padding(12)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: Radius.sm).fill(theme.surfaceElevated))
        .overlay(RoundedRectangle(cornerRadius: Radius.sm).strokeBorder(theme.surfaceBorder))
    }
}

/// A markdown table -- real Grid/GridRow layout, not hand-rolled column
/// math. Header row + alternating body-row shading matches the same visual
/// language already shipped tonight in backend/app/documents.py's PDF
/// table rendering (dark header row, alternating body backgrounds), for
/// one consistent "what a table looks like in this product" across chat
/// and generated documents.
private struct TableView: View {
    let header: [String]
    let rows: [[String]]
    @Environment(\.appTheme) private var theme

    var body: some View {
        ScrollView(.horizontal, showsIndicators: true) {
            Grid(alignment: .topLeading, horizontalSpacing: 0, verticalSpacing: 0) {
                GridRow {
                    ForEach(Array(header.enumerated()), id: \.offset) { _, cell in
                        cellText(cell, isHeader: true)
                    }
                }
                ForEach(Array(rows.enumerated()), id: \.offset) { rowIndex, row in
                    GridRow {
                        ForEach(Array(row.enumerated()), id: \.offset) { _, cell in
                            cellText(cell, isHeader: false)
                                .background(rowIndex.isMultiple(of: 2) ? Color.clear : theme.surfaceElevated.opacity(0.5))
                        }
                    }
                }
            }
            .textSelection(.enabled)
        }
        .background(RoundedRectangle(cornerRadius: Radius.sm).fill(theme.surface))
        .overlay(RoundedRectangle(cornerRadius: Radius.sm).strokeBorder(theme.surfaceBorder))
    }

    @ViewBuilder
    private func cellText(_ raw: String, isHeader: Bool) -> some View {
        Text(SimpleMarkdownView.inline(raw))
            .font(PCorpFont.body(12, weight: isHeader ? .semibold : .regular))
            .foregroundStyle(isHeader ? theme.accentText : theme.textPrimary)
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(isHeader ? theme.textPrimary.opacity(0.85) : Color.clear)
            .overlay(Rectangle().strokeBorder(theme.divider, lineWidth: 0.5))
    }
}
