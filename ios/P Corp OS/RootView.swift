import PCorpKit
import SwiftUI

/// Replaces WarRoomView as ContentView's post-token destination
/// (2026-08-12). Desktop's ContentView.swift is a fixed HStack of
/// Sidebar/content/RightRail; there's no room for a permanent column on a
/// phone, so this is the mobile translation -- a hamburger button opens
/// Sidebar as a slide-in drawer over the content instead. Same selection
/// model as desktop (selectedID drives which section shows), same honest
/// "not built yet" placeholder for every section besides War Room, which
/// is the only one with a real iOS screen so far -- mirrors desktop's own
/// SectionPlaceholderView pattern rather than hiding unbuilt sections.
struct RootView: View {
    @State private var selectedID: UUID? = NavItem.items.first?.id
    @State private var isDrawerOpen = false
    @Environment(\.appTheme) private var theme

    private var selectedItem: NavItem {
        NavItem.items.first { $0.id == selectedID } ?? NavItem.items[0]
    }

    var body: some View {
        ZStack(alignment: .leading) {
            VStack(spacing: 0) {
                topBar
                Group {
                    switch selectedItem.title {
                    case "War Room":
                        WarRoomView()
                    case "Frank":
                        FrankView()
                    default:
                        SectionPlaceholderView(item: selectedItem)
                    }
                }
                .id(selectedItem.id)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .background(theme.background)
            .allowsHitTesting(!isDrawerOpen)

            if isDrawerOpen {
                Color.black.opacity(0.35)
                    .ignoresSafeArea()
                    .onTapGesture { withAnimation(.easeOut(duration: 0.2)) { isDrawerOpen = false } }
                    .transition(.opacity)

                Sidebar(selectedID: $selectedID, isOpen: $isDrawerOpen)
                    .frame(width: 280)
                    .ignoresSafeArea()
                    .transition(.move(edge: .leading))
            }
        }
        .animation(.easeOut(duration: 0.22), value: isDrawerOpen)
    }

    private var topBar: some View {
        HStack {
            Button {
                withAnimation(.easeOut(duration: 0.22)) { isDrawerOpen = true }
            } label: {
                Image(systemName: "line.3.horizontal")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                    .frame(width: 36, height: 36)
                    .contentShape(Rectangle())
            }
            Spacer()
            Image("p_logo_black")
                .resizable()
                .renderingMode(.template)
                .scaledToFit()
                .foregroundStyle(theme.textPrimary)
                .frame(width: 18, height: 22)
            Spacer()
            Color.clear.frame(width: 36, height: 36)
        }
        .padding(.horizontal, 8)
        .padding(.top, 4)
        .padding(.bottom, 4)
    }
}

/// Exact match for desktop's own private SectionPlaceholderView
/// (ContentView.swift there) -- same "STANDBY" capsule, same honest
/// "not built yet" copy, ported since this is now a real reachable state
/// on iOS too (10 of 11 sidebar sections) rather than only on desktop.
private struct SectionPlaceholderView: View {
    let item: NavItem
    @Environment(\.appTheme) private var theme
    @State private var hasAppeared = false

    var body: some View {
        VStack(spacing: 18) {
            ZStack {
                Circle()
                    .fill(.regularMaterial)
                    .frame(width: 72, height: 72)
                Circle()
                    .strokeBorder(theme.surfaceBorder, lineWidth: 1)
                    .frame(width: 72, height: 72)
                Image(systemName: item.systemImage)
                    .font(.system(size: 28, weight: .regular))
                    .foregroundStyle(theme.textPrimary.opacity(0.7))
            }

            VStack(spacing: 4) {
                Text(item.title)
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text(item.subtitle)
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
            }

            HStack(spacing: 6) {
                Circle().fill(theme.textSecondary).frame(width: 6, height: 6)
                Text("STANDBY")
                    .font(PCorpFont.label(9.5))
                    .trackedLabel(1.4)
                    .foregroundStyle(theme.textSecondary)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(Capsule().fill(theme.textPrimary.opacity(0.05)))

            Text("Not built yet — this is an honest placeholder, not a preview.")
                .font(PCorpFont.body(11.5))
                .foregroundStyle(theme.textSecondary.opacity(0.7))
        }
        .opacity(hasAppeared ? 1 : 0)
        .scaleEffect(hasAppeared ? 1 : 0.97)
        .onAppear {
            withAnimation(.easeOut(duration: 0.3)) { hasAppeared = true }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
    }
}

#Preview {
    RootView()
}
