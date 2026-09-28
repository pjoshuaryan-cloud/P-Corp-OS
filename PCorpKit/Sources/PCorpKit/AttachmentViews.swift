import SwiftUI

/// The pre-send composer strip -- one chip per staged attachment, real
/// thumbnail for an image, an SF Symbol for everything else. Replaces the
/// old single-slot `attachedImageChip` that used to be independently
/// hand-duplicated, byte-for-byte, on both platforms (2026-09-05) -- same
/// bordered-surface chrome `ApprovalRequestCard`'s own doc comment already
/// calls out as this app's established "card surface" language.
public struct AttachmentChipStrip: View {
    let attachments: [PendingAttachment]
    let onRemove: (PendingAttachment.ID) -> Void
    @Environment(\.appTheme) private var theme

    public init(attachments: [PendingAttachment], onRemove: @escaping (PendingAttachment.ID) -> Void) {
        self.attachments = attachments
        self.onRemove = onRemove
    }

    public var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(attachments) { attachment in
                    HStack(spacing: 8) {
                        thumbnailOrIcon(attachment)
                        Text(attachment.kind == .image ? "Image attached" : attachment.filename)
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                            .lineLimit(1)
                        Button(action: { onRemove(attachment.id) }) {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(theme.textTertiary)
                        }
                        .buttonStyle(.plain)
                    }
                    .padding(8)
                    .background(RoundedRectangle(cornerRadius: 12).fill(theme.surface.opacity(0.5)))
                    .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))
                }
            }
        }
    }

    @ViewBuilder
    private func thumbnailOrIcon(_ attachment: PendingAttachment) -> some View {
        if attachment.kind == .image, let thumbnail = attachment.thumbnail {
            platformImage(thumbnail)
                .resizable()
                .aspectRatio(contentMode: .fill)
                .frame(width: 32, height: 32)
                .clipShape(RoundedRectangle(cornerRadius: 6))
        } else {
            Image(systemName: attachment.kind.symbolName)
                .font(.system(size: 14))
                .foregroundStyle(theme.textSecondary)
                .frame(width: 32, height: 32)
        }
    }
}

/// Shown inside a sent chat bubble for a message that has attachments --
/// either real ones from this session (`attachments`, a genuine 240pt
/// image preview matching the original single-image behavior, an icon
/// row for a non-image kind) or placeholder names from a reopened old
/// conversation (`storedAttachmentNames`, bytes never re-fetched -- same
/// confirmed 2026-08-05 decision, now covering every kind). Only ever
/// used from a user message's own rendering -- Frank never attaches
/// anything to his own replies -- so the accent-on-filled-bubble color
/// choice below is safe to hardcode, matching the original single-image
/// version's exact color.
public struct MessageAttachmentsView: View {
    let attachments: [SentAttachment]
    let storedAttachmentNames: [String]
    @Environment(\.appTheme) private var theme

    public init(attachments: [SentAttachment], storedAttachmentNames: [String]) {
        self.attachments = attachments
        self.storedAttachmentNames = storedAttachmentNames
    }

    public var body: some View {
        VStack(alignment: .trailing, spacing: 8) {
            ForEach(attachments) { attachment in
                if attachment.kind == .image, let thumbnail = attachment.thumbnail {
                    platformImage(thumbnail)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(maxWidth: 240, maxHeight: 240)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                } else {
                    placeholderRow(symbolName: attachment.kind.symbolName, label: attachment.filename)
                }
            }
            ForEach(storedAttachmentNames, id: \.self) { name in
                placeholderRow(symbolName: "paperclip", label: name)
            }
        }
    }

    private func placeholderRow(symbolName: String, label: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: symbolName)
            Text(label)
        }
        .font(PCorpFont.body(12))
        .foregroundStyle(theme.accentText.opacity(0.8))
    }
}

/// A real PDF Frank generated, shown in his own reply bubble (2026-09-09,
/// "viewable & saveable" fix) -- deliberately not folded into
/// MessageAttachmentsView above, which documents itself as "only ever used
/// from a user message's own rendering" and has no tap-handling shape at
/// all. `onTap` is platform-specific (desktop: NSWorkspace against the
/// real local file; iOS: fetch over GET /documents/{filename} then
/// QuickLook), so it lives in the caller, not here.
///
/// Real bug found live (2026-09-28): the original version was a single
/// small inline text link (12pt, 0.8 opacity, one-line-truncated) sitting
/// right at the bottom edge of the reply bubble -- functionally correct
/// (it opened the real PDF when clicked) but Josh genuinely could not
/// find it across two separate live tries, reporting "nothing... it must
/// be readable and saveable" even with the row plainly on screen in a
/// shared screenshot. A working feature nobody can see is not a working
/// feature. Rebuilt as its own real card -- the same bordered-surface
/// "card surface" language AttachmentChipStrip already uses above, not a
/// plain text link -- with a colored icon badge, the full title (wrapped,
/// never truncated to a confusing fragment), a visible "PDF" kind label,
/// and an explicit "Open" affordance so it reads unambiguously as a
/// clickable deliverable, not decoration.
public struct GeneratedDocumentRow: View {
    let document: GeneratedDocument
    let onTap: () -> Void
    @Environment(\.appTheme) private var theme

    public init(document: GeneratedDocument, onTap: @escaping () -> Void) {
        self.document = document
        self.onTap = onTap
    }

    public var body: some View {
        Button(action: onTap) {
            HStack(spacing: 10) {
                ZStack {
                    RoundedRectangle(cornerRadius: 8).fill(theme.accentFill.opacity(0.18))
                    Image(systemName: "doc.richtext.fill")
                        .font(.system(size: 16))
                        .foregroundStyle(theme.accentText)
                }
                .frame(width: 34, height: 34)

                VStack(alignment: .leading, spacing: 2) {
                    Text(document.title)
                        .font(PCorpFont.body(13, weight: .semibold))
                        .foregroundStyle(theme.textPrimary)
                        .lineLimit(2)
                    Text("PDF — tap to open")
                        .font(PCorpFont.body(10.5))
                        .foregroundStyle(theme.textTertiary)
                }

                Spacer(minLength: 8)

                Image(systemName: "arrow.up.forward.square")
                    .font(.system(size: 13))
                    .foregroundStyle(theme.accentText)
            }
            .padding(10)
            .frame(maxWidth: 280)
            .background(RoundedRectangle(cornerRadius: 12).fill(theme.surface.opacity(0.6)))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))
        }
        .buttonStyle(.plain)
    }
}

func platformImage(_ image: PlatformImage) -> Image {
    #if canImport(UIKit)
    return Image(uiImage: image)
    #else
    return Image(nsImage: image)
    #endif
}
