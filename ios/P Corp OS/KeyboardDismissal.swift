import SwiftUI
import UIKit

/// App-wide keyboard dismissal (2026-09-22, reworked same day) -- Josh's
/// own ask: "throughout the app if I want to pull down the keyboard it
/// should let me regardless of where I am." Before this, only
/// WarRoomView had any dismiss handling at all (.scrollDismissesKeyboard).
///
/// First attempt used a plain SwiftUI `.simultaneousGesture` on
/// ContentView's own root -- confirmed live it did nothing, anywhere.
/// Root cause: a `.sheet`/`.popover` (how Trade Intelligence and every
/// other popup in this app opens) presents an entirely separate SwiftUI
/// view hierarchy. Gesture modifiers on a parent view never propagate
/// into that presented content, no matter where in the parent tree
/// they're attached -- there is no SwiftUI-level modifier that reaches
/// "everywhere, including every sheet."
///
/// This installs a real UIKit UITapGestureRecognizer directly on the
/// app's key UIWindow instead. A window-level gesture recognizer sits
/// UNDER all of SwiftUI's own view-hierarchy/presentation machinery --
/// sheets and popovers render as subviews of that same UIWindow (SwiftUI
/// doesn't create a new UIWindow per sheet), so this actually does reach
/// everywhere, regardless of how deep or how presented the current
/// screen is. `cancelsTouchesInView = false` plus the delegate below are
/// both required -- without them this would swallow every tap in the
/// app and silently break every button/row/nav link.
private final class GlobalKeyboardDismissInstaller: NSObject, UIGestureRecognizerDelegate {
    static let shared = GlobalKeyboardDismissInstaller()
    private var installedWindows = Set<ObjectIdentifier>()

    func installIfNeeded() {
        for scene in UIApplication.shared.connectedScenes {
            guard let windowScene = scene as? UIWindowScene else { continue }
            for window in windowScene.windows {
                let id = ObjectIdentifier(window)
                guard !installedWindows.contains(id) else { continue }
                let tap = UITapGestureRecognizer(target: self, action: #selector(handleTap))
                tap.cancelsTouchesInView = false
                tap.delegate = self
                window.addGestureRecognizer(tap)
                installedWindows.insert(id)
            }
        }
    }

    @objc private func handleTap() {
        for scene in UIApplication.shared.connectedScenes {
            guard let windowScene = scene as? UIWindowScene else { continue }
            for window in windowScene.windows {
                window.endEditing(true)
            }
        }
    }

    // Required so this recognizes ALONGSIDE every other gesture/button in
    // the app (SwiftUI buttons, list row taps, nav links) instead of
    // stealing the touch from them -- returning true here is what makes
    // "tap anywhere dismisses keyboard" coexist with normal taps still
    // doing their own thing.
    func gestureRecognizer(
        _ gestureRecognizer: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer
    ) -> Bool {
        true
    }

    // Real bug found live (2026-09-29): recognizing simultaneously with
    // EVERY gesture (above) also meant firing on a tap that landed
    // INSIDE the currently-focused chat input itself -- tapping to
    // reposition the cursor before pasting, or tapping a selection to
    // bring up the Copy/Paste edit menu, is itself a qualifying tap.
    // handleTap()'s unconditional endEditing(true) force-resigned first
    // responder (dismissing the keyboard and any edit menu tied to it)
    // before the paste could complete -- Josh's own reported "closes
    // the keyboard without being able to paste." A tap inside a text
    // input was never "somewhere else" in the "tap anywhere ELSE to
    // dismiss" sense this feature exists for, so it's excluded at the
    // touch level here rather than acted on and undone. UITextInput is
    // the real, documented protocol both UITextField and UITextView
    // (including GrowingChatInput's own UIKit-backed iOS implementation)
    // conform to, so this covers the chat input and any future text
    // control without needing a per-view opt-out list.
    func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldReceive touch: UITouch) -> Bool {
        var view: UIView? = touch.view
        while let v = view {
            if v is UITextInput { return false }
            view = v.superview
        }
        return true
    }
}

extension View {
    /// Call once, from the app's actual root (ContentView) -- re-runs
    /// safely on every appearance since installIfNeeded() tracks which
    /// windows already have the recognizer attached.
    func installsGlobalKeyboardDismiss() -> some View {
        onAppear { GlobalKeyboardDismissInstaller.shared.installIfNeeded() }
    }
}
