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

// SimpleMarkdownView moved to PCorpKit (2026-08-13) so iOS's Knowledge
// section can reuse it -- see PCorpKit/Sources/PCorpKit/
// SimpleMarkdownView.swift.
