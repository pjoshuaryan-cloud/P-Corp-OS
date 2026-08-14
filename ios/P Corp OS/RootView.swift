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
    // Live drag delta, added on top of isDrawerOpen's base position while a
    // swipe is in progress -- see dragProgress/currentOffsetX below. Reset
    // to 0 once the gesture ends and isDrawerOpen has settled.
    @State private var dragOffset: CGFloat = 0
    @Environment(\.appTheme) private var theme

    private let drawerWidth: CGFloat = 280
    // Opening swipes only count from near the left bezel -- matches the
    // standard iOS drawer convention (Mail, Gmail, Slack) and, just as
    // importantly, keeps a normal vertical scroll anywhere else in the
    // chat from ever being mistaken for a horizontal drawer drag. Closing
    // swipes aren't edge-gated: once the drawer's open, everything under
    // it is already non-interactive (see .allowsHitTesting below), so a
    // drag anywhere on the dimmed content/drawer itself is unambiguous.
    private let edgeSwipeActivationWidth: CGFloat = 32
    private let openCloseThreshold: CGFloat = 80

    private var selectedItem: NavItem {
        NavItem.items.first { $0.id == selectedID } ?? NavItem.items[0]
    }

    /// 0 = fully closed, 1 = fully open, combining the committed
    /// isDrawerOpen state with whatever the in-progress drag has added.
    private var dragProgress: CGFloat {
        let base: CGFloat = isDrawerOpen ? drawerWidth : 0
        return min(max(base + dragOffset, 0), drawerWidth) / drawerWidth
    }

    private var drawerOffsetX: CGFloat {
        -drawerWidth + dragProgress * drawerWidth
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
                    case "Settings":
                        SettingsView()
                    case "Automations":
                        AutomationsView()
                    case "Agents":
                        AgentsView()
                    case "Knowledge":
                        KnowledgeView()
                    case "Alpha Mode Media":
                        AlphaModeDashboardView()
                    default:
                        SectionPlaceholderView(item: selectedItem)
                    }
                }
                .id(selectedItem.id)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .background(theme.background)
            .allowsHitTesting(!isDrawerOpen)

            Color.black.opacity(0.35 * dragProgress)
                .ignoresSafeArea()
                .allowsHitTesting(isDrawerOpen)
                .onTapGesture { setDrawer(open: false) }

            Sidebar(selectedID: $selectedID, isOpen: $isDrawerOpen)
                .frame(width: drawerWidth)
                .ignoresSafeArea()
                .offset(x: drawerOffsetX)

            // Real bug found live (2026-08-13): closing worked, opening
            // didn't. Root cause -- both directions shared one DragGesture
            // attached to the whole ZStack, but WarRoomView's chat is a
            // ScrollView, and SwiftUI/UIKit gesture arbitration generally
            // lets a child view's own gesture recognizer (the ScrollView's
            // pan) win over a plain .gesture() on a parent, for touches
            // that start inside it. Closing was never affected by this --
            // once open, the main content's hit-testing is off (below),
            // so there's no ScrollView underneath to compete with. Opening
            // was, since the closed-state content (and its ScrollView) is
            // still fully interactive. Fixed by giving the open-swipe its
            // own dedicated hot zone: a thin, otherwise-invisible strip
            // hugging the true left bezel with no ScrollView inside it to
            // lose the arbitration to -- same ~20-32pt edge convention
            // Mail/Gmail/Slack all use, not an arbitrary choice.
            if !isDrawerOpen {
                Color.clear
                    .contentShape(Rectangle())
                    .frame(width: edgeSwipeActivationWidth)
                    .frame(maxHeight: .infinity)
                    .ignoresSafeArea()
                    .gesture(edgeOpenGesture)
            }
        }
        .gesture(closeDragGesture)
    }

    private var edgeOpenGesture: some Gesture {
        DragGesture(minimumDistance: 10)
            .onChanged { value in
                guard abs(value.translation.width) > abs(value.translation.height) else { return }
                dragOffset = max(0, value.translation.width)
            }
            .onEnded { value in
                setDrawer(open: value.translation.width > openCloseThreshold)
            }
    }

    /// Handles closing only -- see edgeOpenGesture above for why opening
    /// needed its own separate, edge-scoped gesture instead of sharing
    /// this one.
    private var closeDragGesture: some Gesture {
        DragGesture(minimumDistance: 10)
            .onChanged { value in
                guard isDrawerOpen else { return }
                guard abs(value.translation.width) > abs(value.translation.height) else { return }
                dragOffset = value.translation.width
            }
            .onEnded { value in
                guard isDrawerOpen else { return }
                setDrawer(open: value.translation.width > -openCloseThreshold)
            }
    }

    private func setDrawer(open: Bool) {
        withAnimation(.easeOut(duration: 0.22)) {
            isDrawerOpen = open
            dragOffset = 0
        }
    }

    private var topBar: some View {
        HStack {
            Button {
                setDrawer(open: true)
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
