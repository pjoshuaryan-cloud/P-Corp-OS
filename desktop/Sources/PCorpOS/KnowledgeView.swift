import SwiftUI
import PCorpKit

/// The "Knowledge" nav section — a browser for this project's own markdown
/// docs (KnowledgeDocs.swift), not a generic file browser. Master-detail:
/// a doc list on the left, the selected doc's content on the right.
struct KnowledgeView: View {
    @Environment(\.appTheme) private var theme
    @State private var selectedDoc: KnowledgeDoc = KnowledgeDocs.all[0]

    var body: some View {
        HStack(spacing: 0) {
            docList
            Divider().overlay(theme.divider)
            docContent
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
    }

    private var docList: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Knowledge")
                    .font(PCorpFont.display(20))
                    .foregroundStyle(theme.textPrimary)
                Text("Frank's own foundational documents")
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.textSecondary)
            }
            .padding(20)

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(KnowledgeDocs.all) { doc in
                        DocRow(doc: doc, isSelected: doc.id == selectedDoc.id) {
                            selectedDoc = doc
                        }
                    }
                }
                .padding(.horizontal, 12)
            }
        }
        .frame(width: 260)
    }

    private var docContent: some View {
        ScrollView {
            SimpleMarkdownView(text: KnowledgeDocs.content(for: selectedDoc))
                .padding(28)
                .frame(maxWidth: 720, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

private struct DocRow: View {
    let doc: KnowledgeDoc
    let isSelected: Bool
    let action: () -> Void
    @Environment(\.appTheme) private var theme
    @State private var isHovering = false

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 1) {
                Text(doc.title)
                    .font(PCorpFont.body(13, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(doc.subtitle)
                    .font(PCorpFont.body(10.5))
                    .foregroundStyle(theme.textSecondary)
                    .lineLimit(1)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(isSelected ? theme.textPrimary.opacity(0.08) : (isHovering ? theme.textPrimary.opacity(0.04) : Color.clear))
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hovering in
            withAnimation(.easeOut(duration: 0.12)) { isHovering = hovering }
        }
    }
}

/// Deliberately not a full markdown engine — no tables, no code blocks, no
/// nested lists. Handles exactly what these docs actually use (headings,
/// bullet/numbered lists, horizontal rules, inline bold/italic/links via
/// Foundation's AttributedString(markdown:)), which is enough to make them
/// genuinely readable without pulling in a third-party dependency.
struct SimpleMarkdownView: View {
    let text: String
    @Environment(\.appTheme) private var theme

    var body: some View {
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
