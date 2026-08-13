import PCorpKit
import SwiftUI

/// Close port of desktop's own FrankView.swift (2026-08-13) — the first of
/// the 7 sections deferred to "a future round" when the hamburger sidebar
/// shipped. Everything it needs was already cross-platform in PCorpKit
/// (MemoryClient, MemoryRecord, AppTheme, PCorpFont, the `.icon` button
/// style), so this is a direct port, not a rebuild — same header, same
/// empty/loading/error states, same memory record cards.
///
/// One real touch-vs-pointer adaptation: desktop reveals each row's forget
/// (trash) button on `.onHover`, which has no equivalent on a touchscreen
/// — there's no "hovering" over a row you haven't tapped. The trash button
/// is just always visible here instead of hover-gated, the same tradeoff
/// mobile UIs generally make for hover-only affordances.
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
        .padding(20)
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
                .padding(20)
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
                .frame(maxWidth: 320)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, 24)
    }
}

private struct MemoryRecordRow: View {
    let record: MemoryRecord
    let onForget: () -> Void
    @Environment(\.appTheme) private var theme
    // Real gap found live (2026-08-13): desktop's trash button only
    // appears on hover, which is itself a soft "are you sure" buffer --
    // there's no touch equivalent, so making it always-tappable here (see
    // this file's own top doc comment) meant one mis-tap could delete a
    // memory with zero warning. This confirmation dialog is the touch
    // replacement for that hover buffer, not decoration.
    @State private var showForgetConfirmation = false

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

            Button {
                showForgetConfirmation = true
            } label: {
                Image(systemName: "trash")
                    .font(.system(size: 11))
                    .foregroundStyle(theme.textSecondary)
            }
            .buttonStyle(.plain)
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
        .confirmationDialog(
            "Forget \"\(record.title)\"?",
            isPresented: $showForgetConfirmation,
            titleVisibility: .visible
        ) {
            Button("Forget", role: .destructive, action: onForget)
            Button("Cancel", role: .cancel) {}
        }
    }
}
