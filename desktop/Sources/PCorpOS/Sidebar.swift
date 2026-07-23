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
            .padding(.horizontal, 20)
            .padding(.top, 24)
            .padding(.bottom, 20)

            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(PlaceholderData.navItems) { item in
                        NavRow(item: item, isSelected: item.id == selectedID)
                            .onTapGesture { selectedID = item.id }
                    }
                }
                .padding(.horizontal, 12)
            }

            Spacer(minLength: 0)

            Divider()
            VStack(alignment: .leading, spacing: 4) {
                Text("SYSTEM STATUS")
                    .font(PCorpFont.label(9.5))
                    .trackedLabel(1.8)
                    .foregroundStyle(.secondary)
                HStack(spacing: 6) {
                    Circle().fill(Color.black).frame(width: 6, height: 6)
                    Text("All Systems Operational")
                        .font(PCorpFont.body(12))
                }
            }
            .padding(20)
        }
        .frame(minWidth: 220, idealWidth: 240)
        .background(Color(white: 0.98))
    }
}

private struct NavRow: View {
    let item: NavItem
    let isSelected: Bool

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: item.systemImage)
                .font(.system(size: 15))
                .frame(width: 20)
                .foregroundStyle(isSelected ? Color.black : Color.black.opacity(0.55))
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
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(isSelected ? Color.black.opacity(0.06) : Color.clear)
        )
        .contentShape(Rectangle())
    }
}
