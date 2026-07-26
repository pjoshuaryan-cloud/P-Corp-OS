import SwiftUI

/// The "Frank" nav section — makes the memory_records table (backend/app/db.py)
/// actually visible. Before this, a saved memory only existed as something
/// Frank silently wrote to SQLite; there was no way for Joshua to see it
/// without a raw DB query. Creation still happens exclusively through
/// Frank's own save_memory tool, not a manual form — but forgetting
/// (MEMORY_SYSTEM.md's flagged gap) can now happen either from here or from
/// Frank's own forget_memory tool during conversation, both hitting the
/// same soft-delete underneath.
struct FrankView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var client = MemoryClient()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(theme.divider)
            content
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        .task { await client.fetch() }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Frank")
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text("What Frank remembers")
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            Button {
                Task { await client.fetch() }
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(.icon)
        }
        .padding(24)
    }

    @ViewBuilder
    private var content: some View {
        if client.isLoading && client.records.isEmpty {
            emptyState(
                icon: "brain",
                title: "Loading…",
                subtitle: "Fetching memory from the backend."
            )
        } else if let error = client.errorMessage {
            emptyState(icon: "wifi.slash", title: "Backend unreachable", subtitle: error)
        } else if client.records.isEmpty {
            emptyState(
                icon: "brain",
                title: "Nothing remembered yet",
                subtitle: "Frank saves memories on his own during conversation — nothing to show until he does."
            )
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    ForEach(client.records.reversed()) { record in
                        MemoryRecordRow(record: record) {
                            Task { await client.forget(record) }
                        }
                    }
                }
                .padding(24)
            }
        }
    }

    private func emptyState(icon: String, title: String, subtitle: String) -> some View {
        VStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 28))
                .foregroundStyle(theme.textSecondary)
            Text(title)
                .font(PCorpFont.body(14, weight: .semibold))
                .foregroundStyle(theme.textPrimary)
            Text(subtitle)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 340)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct MemoryRecordRow: View {
    let record: MemoryRecord
    let onForget: () -> Void
    @Environment(\.appTheme) private var theme
    @State private var isHovering = false

    private var typeColor: Color {
        switch record.type {
        case "user": return .blue
        case "feedback": return .orange
        case "project": return .green
        case "reference": return .purple
        default: return theme.textSecondary
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 8) {
                    Text(record.type.uppercased())
                        .font(PCorpFont.label(9))
                        .trackedLabel(1.2)
                        .foregroundStyle(typeColor)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(Capsule().fill(typeColor.opacity(0.12)))
                    if record.sensitive {
                        Image(systemName: "lock.fill")
                            .font(.system(size: 9))
                            .foregroundStyle(theme.textSecondary)
                    }
                    Spacer()
                    Text(record.createdAt)
                        .font(PCorpFont.body(10.5))
                        .foregroundStyle(theme.textTertiary)
                }
                Text(record.title)
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(record.content)
                    .font(PCorpFont.body(12.5))
                    .foregroundStyle(theme.textSecondary)
            }

            // Manual forgetting — same soft-delete Frank's own forget_memory
            // tool uses. Hover-revealed, matching this shell's existing
            // pattern (e.g. RightRail's insight rows) rather than a
            // permanently-visible delete button cluttering every row.
            Button(action: onForget) {
                Image(systemName: "trash")
                    .font(.system(size: 11))
                    .foregroundStyle(theme.textSecondary)
            }
            .buttonStyle(.plain)
            .opacity(isHovering ? 1 : 0)
            .help("Forget this memory")
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(.regularMaterial)
        )
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(theme.background.opacity(0.35))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .strokeBorder(theme.surfaceBorder)
        )
        .onHover { hovering in
            withAnimation(.easeOut(duration: 0.12)) { isHovering = hovering }
        }
    }
}
