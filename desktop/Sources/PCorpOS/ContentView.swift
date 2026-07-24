import AppKit
import SwiftUI

/// Root layout: sidebar, center content, right rail — a plain HStack rather
/// than NavigationSplitView, since the layout is a fixed three-column design,
/// not a collapsible/adaptive one. Selection now lives here (not inside
/// Sidebar) so it can drive what the center pane shows — real navigation,
/// still no backend, no data, no wired-up actions beyond switching views.
struct ContentView: View {
    @State private var selectedID: UUID? = PlaceholderData.navItems.first?.id
    // Launch fade-in: FOUNDER_BRIEF.md's own description of opening the app
    // is explicit — "no loading spinner... the screen fades in." Starts
    // transparent, fades to full opacity right on appear.
    @State private var hasAppeared = false
    @State private var keyMonitor: Any?

    private var selectedItem: NavItem {
        PlaceholderData.navItems.first { $0.id == selectedID } ?? PlaceholderData.navItems[0]
    }

    var body: some View {
        HStack(spacing: 0) {
            Sidebar(selectedID: $selectedID)

            Group {
                switch selectedItem.title {
                case "War Room":
                    WarRoomView()
                case "Settings":
                    SettingsView()
                default:
                    SectionPlaceholderView(item: selectedItem)
                }
            }
            .id(selectedItem.id) // forces a fresh view per section, so the transition below actually triggers
            .transition(.opacity.combined(with: .scale(scale: 0.99, anchor: .center)))
            .animation(.easeOut(duration: 0.18), value: selectedID)
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            RightRail(selectedID: $selectedID)
        }
        .frame(minWidth: 1100, minHeight: 700)
        .opacity(hasAppeared ? 1 : 0)
        .onAppear {
            withAnimation(.easeOut(duration: 1.1)) {
                hasAppeared = true
            }
            installKeyboardShortcutsIfNeeded()

            // This is a raw, unbundled executable (built via `swift build`,
            // not a proper Xcode-built .app) — diagnosed and confirmed that
            // such processes don't automatically get normal foreground/key-
            // window status the way a real .app does (activationPolicy came
            // back .prohibited, isActive=false, keyWindow=false on launch),
            // even though mouse/click events already worked fine throughout
            // this shell (they route differently and don't require "key"
            // status). Without this, the keyboard shortcut monitor below
            // never received a single key event. Forcing it explicitly is
            // the actual fix, confirmed working — not a workaround.
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                NSApp.setActivationPolicy(.regular)
                NSApp.activate(ignoringOtherApps: true)
                NSApp.windows.first?.makeKeyAndOrderFront(nil)

                // The Dock icon set in PCorpOSApp.init() likely had no
                // effect: at that point the app was still .prohibited with
                // no real Dock presence, so there was no Dock tile yet to
                // carry the custom icon. Re-applying it here, after forcing
                // .regular + activate above, targets the point where a real
                // Dock tile actually exists.
                if let url = Bundle.module.url(forResource: "AppIcon", withExtension: "icns"),
                   let icon = NSImage(contentsOf: url) {
                    NSApp.applicationIconImage = icon
                }
            }
        }
        .onDisappear {
            if let monitor = keyMonitor {
                NSEvent.removeMonitor(monitor)
                keyMonitor = nil
            }
        }
    }

    /// Real, functional keyboard shortcuts — Cmd+1...Cmd+9 jump to the first
    /// nine sidebar sections by position, Cmd+, jumps straight to Settings
    /// (standard macOS convention for a preferences pane).
    ///
    /// First attempt used invisible SwiftUI Buttons with .keyboardShortcut,
    /// which didn't actually work in practice (SwiftUI's shortcut-to-Button
    /// plumbing on a plain WindowGroup, with no App-level Commands, turned
    /// out not to be reliable here). Replaced with a direct AppKit local
    /// event monitor instead — lower-level, but unambiguous about whether
    /// it's actually receiving key events, and this is the same mechanism
    /// real macOS apps use under the hood.
    private func installKeyboardShortcutsIfNeeded() {
        guard keyMonitor == nil else { return }
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            guard event.modifierFlags.contains(.command),
                  let characters = event.charactersIgnoringModifiers
            else { return event }

            if characters == ",",
               let settings = PlaceholderData.navItems.first(where: { $0.title == "Settings" }) {
                withAnimation(.easeOut(duration: 0.22)) { selectedID = settings.id }
                return nil // consume the event
            }

            if let number = Int(characters), (1...9).contains(number),
               PlaceholderData.navItems.indices.contains(number - 1) {
                withAnimation(.easeOut(duration: 0.22)) {
                    selectedID = PlaceholderData.navItems[number - 1].id
                }
                return nil
            }

            return event
        }
    }
}

/// What every non-War-Room, non-Settings nav item shows right now — still
/// an honest "not built yet," not invented content, but designed to the
/// same bar as the rest of the shell instead of a bare icon and gray text.
/// A section that isn't built yet is a real, permanent state for a while
/// (there are 9 of them), so it earns real design attention, not an
/// afterthought.
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

// No #Preview here: the Xcode Canvas preview macro needs the PreviewsMacros
// plugin that ships with full Xcode, which isn't installed on this machine
// (command-line tools only). Use `swift run` to see the actual window instead.
