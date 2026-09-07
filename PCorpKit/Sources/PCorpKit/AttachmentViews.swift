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

func platformImage(_ image: PlatformImage) -> Image {
    #if canImport(UIKit)
    return Image(uiImage: image)
    #else
    return Image(nsImage: image)
    #endif
}
