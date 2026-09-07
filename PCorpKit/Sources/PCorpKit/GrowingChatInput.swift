import SwiftUI
#if os(iOS)
import UIKit
#endif

/// Chat input control shared by desktop and iOS WarRoomView (2026-09-03) --
/// replaces the old single-line TextField on both platforms, which could
/// only ever send on Return with no way to insert a newline, no auto-grow,
/// and no foundation for attaching files later without hitting the same
/// ceiling.
///
/// Desktop (macOS) uses plain SwiftUI `TextEditor` + `.onKeyPress` -- gives
/// full, unambiguous ownership of every keystroke without needing
/// TextField(text:axis:.vertical)'s unverified Return-key override
/// behavior. Confirmed working visually; real keyboard-shortcut testing is
/// Joshua's to click through live (no safe way to automate real keystrokes
/// into a native macOS app from here).
///
/// iOS is a DIFFERENT implementation on purpose (2026-09-03, real bug found
/// live): the same pure-SwiftUI TextEditor approach never gained focus on
/// iOS at all -- confirmed directly by Joshua tapping into it on a real
/// build ("keyboard doesn't come up"), not just an automation artifact.
/// Rather than keep guessing at SwiftUI TextEditor's focus quirks, iOS uses
/// a `UIViewRepresentable`-wrapped real `UITextView` instead -- the
/// standard, reliable approach production apps use for exactly this kind
/// of custom-keyboard-behavior text control, since it gives direct control
/// over `becomeFirstResponder()`/delegate callbacks instead of depending on
/// SwiftUI's own focus plumbing for a still-evolving API.
public struct GrowingChatInput: View {
    @Binding var text: String
    let placeholder: String
    let isFocused: FocusState<Bool>.Binding
    let onSend: () -> Void

    @Environment(\.appTheme) private var theme
    @State private var measuredHeight: CGFloat = GrowingChatInput.minHeight

    // One line at PCorpFont.body(14) up to roughly six lines before the
    // editor scrolls internally instead of growing the input bar (and the
    // message list above it) without bound.
    fileprivate static let minHeight: CGFloat = 20
    fileprivate static let maxHeight: CGFloat = 120

    public init(
        text: Binding<String>,
        placeholder: String,
        isFocused: FocusState<Bool>.Binding,
        onSend: @escaping () -> Void
    ) {
        self._text = text
        self.placeholder = placeholder
        self.isFocused = isFocused
        self.onSend = onSend
    }

    public var body: some View {
        ZStack(alignment: .topLeading) {
            if text.isEmpty {
                Text(placeholder)
                    .font(PCorpFont.body(14))
                    .foregroundStyle(theme.textSecondary)
                    .allowsHitTesting(false)
            }

            #if os(iOS)
            ChatTextViewRepresentable(
                text: $text,
                height: $measuredHeight,
                isFocused: isFocused,
                font: PCorpFont.body(14),
                textColor: theme.textPrimary,
                onSend: onSend
            )
            .frame(height: min(max(measuredHeight, Self.minHeight), Self.maxHeight))
            #else
            TextEditor(text: $text)
                .font(PCorpFont.body(14))
                .foregroundStyle(theme.textPrimary)
                .scrollContentBackground(.hidden) // let inputBar's own surfaceElevated show through
                .focused(isFocused)
                .frame(height: min(max(measuredHeight, Self.minHeight), Self.maxHeight))
                // Plain Return sends; Shift+Return is the one case that
                // should fall through to TextEditor's own default (insert
                // a newline). Cmd+Return and Ctrl+Return deliberately need
                // no separate branch -- neither sets .shift, so they land
                // in the same "send" case as plain Return, satisfying
                // "Cmd/Ctrl+Enter = alternative send" for free. Paste
                // (Cmd+V) never dispatches a .return event at all, so
                // multi-line clipboard content always lands safely via
                // TextEditor's normal insertion path, untouched by this.
                .onKeyPress(.return, phases: .down) { keyPress in
                    if keyPress.modifiers.contains(.shift) {
                        return .ignored
                    }
                    onSend()
                    return .handled
                }
                .background(heightMeasurer)
            #endif
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
    }

    #if !os(iOS)
    /// macOS only -- iOS measures height directly from UITextView's own
    /// sizeThatFits instead (see ChatTextViewRepresentable below).
    /// Invisible twin of the real text (same font, same width) whose
    /// natural height drives the visible TextEditor's frame -- the
    /// standard idiom since TextEditor doesn't auto-size on its own.
    private var heightMeasurer: some View {
        Text(text.isEmpty ? " " : text)
            .font(PCorpFont.body(14))
            .frame(maxWidth: .infinity, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
            .background(
                GeometryReader { geo in
                    Color.clear.preference(key: InputHeightKey.self, value: geo.size.height)
                }
            )
            .hidden()
            // .hidden() only removes this from rendering/accessibility --
            // it does NOT disable hit-testing on its own, so this needs
            // its own explicit opt-out too.
            .allowsHitTesting(false)
            .onPreferenceChange(InputHeightKey.self) { measuredHeight = $0 }
    }
    #endif
}

private struct InputHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = GrowingChatInput.minHeight
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

#if os(iOS)
/// Real UITextView wrapper (2026-09-03) -- see GrowingChatInput's own doc
/// comment for why this replaced plain SwiftUI TextEditor on iOS
/// specifically. Owns focus, text sync, height measurement, and Return-key
/// semantics directly against UIKit rather than through SwiftUI's
/// `.focused()`/`.onKeyPress`, which never reliably gained focus here.
private struct ChatTextViewRepresentable: UIViewRepresentable {
    @Binding var text: String
    @Binding var height: CGFloat
    let isFocused: FocusState<Bool>.Binding
    let font: Font
    let textColor: Color
    let onSend: () -> Void

    func makeUIView(context: Context) -> ChatUITextView {
        let view = ChatUITextView()
        view.delegate = context.coordinator
        view.backgroundColor = .clear
        view.isScrollEnabled = true
        view.textContainerInset = .zero
        view.textContainer.lineFragmentPadding = 0
        view.onPlainReturn = onSend
        return view
    }

    func updateUIView(_ uiView: ChatUITextView, context: Context) {
        if uiView.text != text {
            uiView.text = text
        }
        uiView.font = Self.uiFont(from: font)
        uiView.textColor = UIColor(textColor)
        uiView.onPlainReturn = onSend

        // Real bug found live (2026-09-04): the keyboard dismissed itself
        // after every single character typed. Root cause -- this used to
        // also resignFirstResponder() whenever isFocused.wrappedValue read
        // false, but @FocusState is only reliably driven by SwiftUI's own
        // .focused() modifier; nothing here ever calls .focused() on
        // anything (this is a UIViewRepresentable, focus is owned by
        // UIKit), so SwiftUI's own focus engine has no reason to keep this
        // binding true and can silently reset it. Every keystroke mutates
        // `text`, which re-renders this view and re-runs updateUIView --
        // if isFocused.wrappedValue happened to read false on that pass
        // (which it reliably did), this unconditionally kicked the
        // keyboard down, one character at a time. Only ever REQUESTING
        // focus here (for the rare external-trigger case, e.g. focusing
        // the field programmatically from elsewhere) is safe and
        // idempotent; resigning must never be driven reactively off this
        // same unreliable read -- real resignation happens on its own via
        // the user's own native action (tapping away, Done, etc.), not
        // something this view needs to force.
        if isFocused.wrappedValue, !uiView.isFirstResponder {
            DispatchQueue.main.async { uiView.becomeFirstResponder() }
        }

        let fitWidth = uiView.bounds.width > 0 ? uiView.bounds.width : UIScreen.main.bounds.width
        let fitSize = uiView.sizeThatFits(CGSize(width: fitWidth, height: .greatestFiniteMagnitude))
        let clamped = min(max(fitSize.height, GrowingChatInput.minHeight), GrowingChatInput.maxHeight)
        if abs(clamped - height) > 0.5 {
            DispatchQueue.main.async { height = clamped }
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(text: $text, isFocused: isFocused)
    }

    /// PCorpFont only produces a SwiftUI Font -- rebuilt as the matching
    /// UIFont (system, rounded design) since UITextView needs a real
    /// UIFont, not a SwiftUI one.
    private static func uiFont(from font: Font) -> UIFont {
        let base = UIFont.systemFont(ofSize: 14, weight: .regular)
        guard let descriptor = base.fontDescriptor.withDesign(.rounded) else { return base }
        return UIFont(descriptor: descriptor, size: 14)
    }

    final class Coordinator: NSObject, UITextViewDelegate {
        @Binding var text: String
        let isFocused: FocusState<Bool>.Binding

        init(text: Binding<String>, isFocused: FocusState<Bool>.Binding) {
            self._text = text
            self.isFocused = isFocused
        }

        func textViewDidChange(_ textView: UITextView) {
            text = textView.text
        }

        func textViewDidBeginEditing(_ textView: UITextView) {
            isFocused.wrappedValue = true
        }

        func textViewDidEndEditing(_ textView: UITextView) {
            isFocused.wrappedValue = false
        }

        /// Only ever sees the ON-SCREEN keyboard's Return here -- hardware
        /// Return (with or without Shift/Cmd/Ctrl) is claimed first by
        /// ChatUITextView's own keyCommands below, so it never reaches
        /// this delegate method at all. The software keyboard has no
        /// physical Shift key, so treating a bare "\n" here as "always
        /// send" is the correct, honest behavior for that case (see
        /// GrowingChatInput's own doc comment on the iOS limitation this
        /// implies).
        func textView(_ textView: UITextView, shouldChangeTextIn range: NSRange, replacementText text: String) -> Bool {
            guard text == "\n" else { return true }
            (textView as? ChatUITextView)?.onPlainReturn?()
            return false
        }
    }
}

/// Real UITextView subclass so hardware-keyboard Return combinations can be
/// distinguished by modifier flags via keyCommands -- UITextViewDelegate's
/// shouldChangeTextIn has no modifier information at all, which is enough
/// for the on-screen keyboard (no Shift key to distinguish) but not for a
/// paired hardware keyboard, where Shift+Return specifically must insert a
/// newline instead of sending.
private final class ChatUITextView: UITextView {
    var onPlainReturn: (() -> Void)?

    override var keyCommands: [UIKeyCommand]? {
        [
            UIKeyCommand(input: "\r", modifierFlags: [], action: #selector(handleSendCommand)),
            UIKeyCommand(input: "\r", modifierFlags: .command, action: #selector(handleSendCommand)),
            UIKeyCommand(input: "\r", modifierFlags: .control, action: #selector(handleSendCommand)),
            UIKeyCommand(input: "\r", modifierFlags: .shift, action: #selector(handleNewlineCommand)),
        ]
    }

    @objc private func handleSendCommand() {
        onPlainReturn?()
    }

    @objc private func handleNewlineCommand() {
        insertText("\n")
    }
}
#endif
