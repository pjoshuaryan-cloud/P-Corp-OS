import SwiftUI

/// Moved here from desktop's own KnowledgeView.swift (2026-08-13) so iOS's
/// Knowledge section can reuse it -- zero platform-specific code to begin
/// with (pure SwiftUI + Foundation's AttributedString), so this was a pure
/// relocation, not a rewrite.
///
/// Deliberately not a full markdown engine — no tables, no code blocks, no
/// nested lists. Handles exactly what these docs actually use (headings,
/// bullet/numbered lists, horizontal rules, inline bold/italic/links via
/// Foundation's AttributedString(markdown:)), which is enough to make them
/// genuinely readable without pulling in a third-party dependency.
public struct SimpleMarkdownView: View {
    let text: String
    @Environment(\.appTheme) private var theme

    public init(text: String) {
        self.text = text
    }

    public var body: some View {
        Text(attributedText)
            .frame(maxWidth: .infinity, alignment: .leading)
            // Real bug found live (2026-08-27): plain SwiftUI Text isn't
            // selectable by default, and even after enabling selection,
            // rendering each block (heading/paragraph/list item) as its
            // own separate Text meant a drag-select couldn't cross block
            // boundaries -- confirmed live, selection stopped dead at
            // the edge of whichever Text it started in. The real fix
            // isn't more textSelection modifiers, it's fewer Text views:
            // the whole reply is now ONE AttributedString rendered by a
            // single Text, so selecting/copying the entire message just
            // works the way selecting a paragraph in any normal document
            // does.
            .textSelection(.enabled)
    }

    /// Builds one continuous AttributedString for the whole document,
    /// replacing the old per-block VStack-of-Text-views approach (see
    /// body's own comment for why). Heading/list/paragraph styling is now
    /// per-run font/color attributes on one string rather than separate
    /// Views -- inline emphasis (bold/italic/links) from inline(_:) below
    /// still renders correctly layered on top, since AttributedString's
    /// markdown-parsed `inlinePresentationIntent` attribute is independent
    /// of the `.font`/`.foregroundColor` attributes set here.
    private var attributedText: AttributedString {
        let blocks = Self.parse(text)
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

    private func isListItem(_ block: Block) -> Bool {
        if case .listItem = block { return true }
        return false
    }

    private func headingSize(_ level: Int) -> CGFloat {
        switch level {
        case 1: return 22
        case 2: return 17
        default: return 14
        }
    }

    private func inline(_ raw: String) -> AttributedString {
        var options = AttributedString.MarkdownParsingOptions()
        options.interpretedSyntax = .inlineOnlyPreservingWhitespace
        return (try? AttributedString(markdown: raw, options: options)) ?? AttributedString(raw)
    }

    private enum Block {
        case heading(level: Int, text: String)
        case listItem(marker: String, text: String)
        case rule
        case paragraph(text: String)
    }

    private static func parse(_ text: String) -> [Block] {
        var blocks: [Block] = []
        // Real bug found live (2026-08-27): every non-empty line became
        // its own separate `.paragraph` block, and therefore its own
        // separate Text view -- .textSelection(.enabled) selects within
        // one Text at a time, so a normal multi-sentence reply (which
        // streams in as plain wrapped lines, not one per sentence) could
        // only ever be copied one line at a time. Consecutive plain
        // lines now accumulate into a single paragraph (standard
        // markdown "soft wrap" behavior -- only a blank line, heading,
        // list item, or rule actually starts a new block), joined with a
        // space, so ordinary prose renders and selects as one continuous
        // block again.
        var paragraphLines: [String] = []
        func flushParagraph() {
            guard !paragraphLines.isEmpty else { return }
            blocks.append(.paragraph(text: paragraphLines.joined(separator: " ")))
            paragraphLines = []
        }

        for rawLine in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let trimmed = rawLine.trimmingCharacters(in: .whitespaces)
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
        }
        flushParagraph()
        return blocks
    }
}
