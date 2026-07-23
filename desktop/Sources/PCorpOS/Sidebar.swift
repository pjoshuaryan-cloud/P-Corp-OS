import SwiftUI

struct Sidebar: View {
    @State private var selected: UUID? = PlaceholderData.navItems.first?.id

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 2) {
                Text("P CORP OS")
                    .font(.system(size: 15, weight: .semibold))
                Text("EXECUTIVE INTELLIGENCE")
                    .font(.system(size: 10, weight: .medium))
                    .tracking(1.0)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 20)
            .padding(.top, 24)
            .padding(.bottom, 20)

            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(PlaceholderData.navItems) { item in
                        NavRow(item: item, isSelected: item.id == selected)
                            .onTapGesture { selected = item.id }
                    }
                }
                .padding(.horizontal, 12)
            }

            Spacer(minLength: 0)

            Divider()
            VStack(alignment: .leading, spacing: 2) {
                Text("SYSTEM STATUS")
                    .font(.system(size: 10, weight: .medium))
                    .tracking(1.0)
                    .foregroundStyle(.secondary)
                HStack(spacing: 6) {
                    Circle().fill(Color.black).frame(width: 6, height: 6)
                    Text("All Systems Operational")
                        .font(.system(size: 12, weight: .regular))
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
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Color.black)
                Text(item.subtitle)
                    .font(.system(size: 11))
                    .foregroundStyle(Color.black.opacity(0.45))
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(isSelected ? Color.black.opacity(0.06) : Color.clear)
        )
        .contentShape(Rectangle())
    }
}
