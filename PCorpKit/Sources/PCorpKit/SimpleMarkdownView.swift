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
        VStack(alignment: .leading, spacing: 10) {
            ForEach(Array(Self.parse(text).enumerated()), id: \.offset) { _, block in
                view(for: block)
            }
        }
    }

    @ViewBuilder
    private func view(for block: Block) -> some View {
        switch block {
        case .heading(let level, let content):
            Text(inline(content))
                .font(PCorpFont.display(headingSize(level), weight: .bold))
                .foregroundStyle(theme.textPrimary)
                .padding(.top, level == 1 ? 2 : 8)
        case .listItem(let marker, let content):
            HStack(alignment: .top, spacing: 8) {
                Text(marker)
                    .foregroundStyle(theme.textSecondary)
                    .frame(minWidth: 14, alignment: .trailing)
                Text(inline(content))
                    .foregroundStyle(theme.textPrimary)
            }
            .font(PCorpFont.body(13))
        case .rule:
            Divider().overlay(theme.divider).padding(.vertical, 4)
        case .paragraph(let content):
            Text(inline(content))
                .font(PCorpFont.body(13))
                .foregroundStyle(theme.textPrimary)
        }
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
        for rawLine in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let trimmed = rawLine.trimmingCharacters(in: .whitespaces)
            if trimmed.isEmpty {
                continue
            } else if trimmed == "---" {
                blocks.append(.rule)
            } else if trimmed.hasPrefix("#") {
                let level = trimmed.prefix(while: { $0 == "#" }).count
                let content = trimmed.drop(while: { $0 == "#" }).trimmingCharacters(in: .whitespaces)
                blocks.append(.heading(level: min(level, 3), text: content))
            } else if trimmed.hasPrefix("- ") || trimmed.hasPrefix("* ") {
                blocks.append(.listItem(marker: "•", text: String(trimmed.dropFirst(2))))
            } else if let numberedMatch = trimmed.range(of: #"^\d+\.\s"#, options: .regularExpression) {
                let marker = String(trimmed[numberedMatch]).trimmingCharacters(in: .whitespaces)
                blocks.append(.listItem(marker: marker, text: String(trimmed[numberedMatch.upperBound...])))
            } else {
                blocks.append(.paragraph(text: trimmed))
            }
        }
        return blocks
    }
}
