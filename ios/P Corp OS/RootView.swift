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
    // Lifted here from WarRoomView (2026-08-20, SystemStatusHeader parity
    // pass) so the new status strip can read real connection/streaming/
    // alert state across all sections, not just while War Room is
    // selected -- same move already made on desktop's ContentView.swift.
    // The scenePhase-based reconnect-on-foreground fix (2026-08-13's real
    // "sent a message no response" bug) moves here too, since it's tied
    // to who owns `backend`.
    @StateObject private var backend = BackendClient()
    @StateObject private var situationRoomClient = SituationRoomClient()
    @State private var situationRoomPollTask: Task<Void, Never>?
    @State private var showTheBrief = false
    @State private var showConversationHistory = false
    @Environment(\.scenePhase) private var scenePhase
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
                SystemStatusHeader(backend: backend, situationRoom: situationRoomClient)
                Group {
                    switch selectedItem.title {
                    case "War Room":
                        WarRoomView(backend: backend, situationRoomClient: situationRoomClient)
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
                    case "Joshx":
                        JoshxView()
                    case "Trading Division":
                        TradingDivisionView()
                    case "Personal":
                        PersonalView()
                    case "Finance":
                        FinanceView()
                    case "Triggers":
                        TriggersView()
                    case "Calendar":
                        CalendarView()
                    default:
                        SectionPlaceholderView(item: selectedItem)
                    }
                }
                .id(selectedItem.id)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                // Real bug found live (2026-08-26): the edge-swipe hot
                // zone below used to be a ZStack-level sibling spanning
                // the FULL screen height, which put its leading 32pt
                // strip directly on top of topBar's hamburger button (also
                // in that same leading area) -- silently swallowing every
                // tap on the button itself, not just swipes on the
                // content. Scoping it to an overlay on just this Group
                // (the switched content, below topBar/SystemStatusHeader)
                // keeps the edge-swipe-to-open gesture working exactly as
                // before while leaving the hamburger button's own tap
                // target untouched.
                .overlay(alignment: .leading) {
                    if !isDrawerOpen {
                        Color.clear
                            .contentShape(Rectangle())
                            .frame(width: edgeSwipeActivationWidth)
                            .frame(maxHeight: .infinity)
                            .gesture(edgeOpenGesture)
                    }
                }
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

            // Edge-swipe-to-open's hot zone (2026-08-13's real fix for
            // "closing worked, opening didn't" -- ScrollView content wins
            // gesture arbitration over a plain parent .gesture() for
            // touches starting inside it) now lives as an overlay on the
            // content Group above, not here -- see the real bug fixed
            // live 2026-08-26: a full-ZStack-height zone at this level
            // covered topBar's hamburger button too, silently swallowing
            // taps on it.
        }
        .gesture(closeDragGesture)
        .task {
            backend.connect()
            startSituationRoomPolling()
        }
        .onChange(of: scenePhase) { _, newPhase in
            guard newPhase == .active else { return }
            backend.disconnect()
            backend.connect()
        }
        .onDisappear {
            situationRoomPollTask?.cancel()
            situationRoomPollTask = nil
        }
    }

    /// Moved here from WarRoomView's own `.task` (2026-08-20) -- same 30s-
    /// poll reasoning as desktop's ContentView.swift: this view persists
    /// across the whole session now, so a one-shot fetch would only ever
    /// reflect whatever was true at launch.
    private func startSituationRoomPolling() {
        guard situationRoomPollTask == nil else { return }
        situationRoomPollTask = Task {
            while !Task.isCancelled {
                await situationRoomClient.fetch()
                try? await Task.sleep(nanoseconds: 30_000_000_000)
            }
        }
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

    // iOS parity port (2026-08-27) of desktop's own topBar toolbar
    // cluster (WarRoomView.swift there) -- New Chat, Chat History, The
    // Brief, Search, and Mission were desktop-only until now. Search and
    // Mission are ported as-is including their current state: both are
    // no-op shells on desktop too ("not wired up yet"), not a regression
    // introduced here -- real search already exists, just inside Chat
    // History's own conversation-content search, not this standalone
    // icon. Mission renders as an icon-only button here rather than
    // desktop's text+icon pill -- the top bar has six buttons plus the
    // hamburger and logo already competing for a phone-width row, and a
    // labeled pill would crowd it more than the icon-only treatment
    // every other button here already uses.
    private var topBar: some View {
        HStack(spacing: 2) {
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

            Button {
                Task { await backend.startNewConversation() }
            } label: {
                Image(systemName: "square.and.pencil")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                    .frame(width: 32, height: 36)
                    .contentShape(Rectangle())
            }
            .disabled(backend.messages.isEmpty)

            Button {
                showConversationHistory = true
            } label: {
                Image(systemName: "clock.arrow.circlepath")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                    .frame(width: 32, height: 36)
                    .contentShape(Rectangle())
            }
            .sheet(isPresented: $showConversationHistory) {
                ConversationHistorySheet(backend: backend) { conversationID in
                    Task { await backend.switchToConversation(conversationID) }
                }
            }

            Button {
                showTheBrief = true
            } label: {
                Image(systemName: "doc.text")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                    .frame(width: 32, height: 36)
                    .contentShape(Rectangle())
            }
            .sheet(isPresented: $showTheBrief) {
                TheBriefSheet()
            }

            Button {
                // no-op: shell only, not wired up yet -- matches
                // desktop's own current state for this same button.
            } label: {
                Image(systemName: "magnifyingglass")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                    .frame(width: 32, height: 36)
                    .contentShape(Rectangle())
            }

            Button {
                // no-op: shell only, not wired up yet -- matches
                // desktop's own current state for this same button.
            } label: {
                Image(systemName: "plus")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                    .frame(width: 32, height: 36)
                    .contentShape(Rectangle())
            }
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
