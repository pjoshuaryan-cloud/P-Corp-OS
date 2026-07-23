import SwiftUI

struct Sidebar: View {
    @Binding var selectedID: UUID?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 3) {
                Text("P CORP OS")
                    .font(PCorpFont.display(15))
                    .trackedLabel(1.8)
                Text("EXECUTIVE INTELLIGENCE")
                    .font(PCorpFont.label(9.5))
                    .trackedLabel(1.8)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 22)
            .padding(.top, 28)
            .padding(.bottom, 28)

            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(PlaceholderData.navItems) { item in
                        NavRow(item: item, isSelected: item.id == selectedID)
                            .onTapGesture { selectedID = item.id }
                    }
                }
                .padding(.horizontal, 14)
            }

            Spacer(minLength: 24)

            Divider()
            VStack(alignment: .leading, spacing: 6) {
                Text("SYSTEM STATUS")
                    .font(PCorpFont.label(9.5))
                    .trackedLabel(1.8)
                    .foregroundStyle(.secondary)
                HStack(spacing: 7) {
                    Circle().fill(Color.black).frame(width: 7, height: 7)
                    Text("All Systems Operational")
                        .font(PCorpFont.body(12.5))
                }
            }
            .padding(.horizontal, 22)
            .padding(.vertical, 24)
        }
        .frame(minWidth: 220, idealWidth: 240)
        .background(Color(white: 0.98))
    }
}

private struct NavRow: View {
    let item: NavItem
    let isSelected: Bool

    /// Alpha Mode Media's real brand mark, bundled from its actual brand
    /// assets (`Resources/alpha_mode_logo.png`) rather than a generic system
    /// icon. `.template` rendering mode treats it as an alpha mask, so it
    /// tints the same way the SF Symbol icons do (black when selected,
    /// muted otherwise) instead of showing a fixed color.
    private static let alphaModeLogo: Image? = {
        guard let url = Bundle.module.url(forResource: "alpha_mode_logo", withExtension: "png"),
              let nsImage = NSImage(contentsOf: url)
        else { return nil }
        return Image(nsImage: nsImage)
    }()

    var body: some View {
        HStack(spacing: 12) {
            if item.title == "Alpha Mode Media", let logo = Self.alphaModeLogo {
                logo
                    .resizable()
                    .renderingMode(.template)
                    .scaledToFit()
                    .frame(width: 15, height: 15)
                    .frame(width: 20)
                    .foregroundStyle(isSelected ? Color.black : Color.black.opacity(0.55))
            } else {
                Image(systemName: item.systemImage)
                    .font(.system(size: 15))
                    .frame(width: 20)
                    .foregroundStyle(isSelected ? Color.black : Color.black.opacity(0.55))
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(item.title)
                    .font(PCorpFont.body(13, weight: .semibold))
                    .foregroundStyle(Color.black)
                Text(item.subtitle)
                    .font(PCorpFont.body(11))
                    .foregroundStyle(Color.black.opacity(0.45))
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 11)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(isSelected ? Color.black.opacity(0.06) : Color.clear)
        )
        .contentShape(Rectangle())
    }
}
