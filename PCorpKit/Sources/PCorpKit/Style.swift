import SwiftUI

/// Shared type and button styling so the whole shell reads as one designed
/// system rather than per-view font tweaks. Rounded system-font design reads
/// noticeably less "default SwiftUI" than the plain SF Pro used in the first
/// pass, and generous tracking on labels matches the wide-letter-spacing look
/// Joshua pointed to in his reference mockups.
public enum PCorpFont {
    public static func display(_ size: CGFloat, weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight, design: .rounded)
    }

    public static func body(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .rounded)
    }

    /// Small all-caps section labels ("MISSION STATUS", "TODAY'S AGENDA", …) —
    /// always paired with wide tracking via `.trackedLabel()`.
    public static func label(_ size: CGFloat = 10.5) -> Font {
        .system(size: size, weight: .semibold, design: .rounded)
    }

    /// "Machine information" typographic register (2026-08-20) — system
    /// telemetry, status text, counts. Deliberately distinct from the
    /// rounded design used everywhere else: the Face-Lift brief's own
    /// distinction between "human information" (large, rounded, warm) and
    /// "machine information" (technical, monospaced). Only the new
    /// system-status header uses this so far — not retrofitted elsewhere.
    public static func mono(_ size: CGFloat, weight: Font.Weight = .medium) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}

extension View {
    /// Wide letter-spacing for all-caps labels, matching the reference look.
    public func trackedLabel(_ amount: CGFloat = 1.4) -> some View {
        self.tracking(amount)
    }
}

/// A primary/secondary action button — filled for primary actions, tinted
/// for secondary ones. Replaces the default `.borderedProminent` style,
/// which only rounds corners slightly on macOS.
/// `.onHover` is a real no-op on touch-only iOS (no pointer, no crash) --
/// harmless there, not desktop-only code that needed splitting out.
///
/// Renamed from `PillButtonStyle` (2026-08-31, UI cleanup) -- was a
/// `Capsule()`, which reads as a status/tag chip shape (Linear/Raycast
/// reserve true capsules for exactly that, using small-radius rects for
/// real actions), and this app's own status chips (STANDBY, project/lead
/// status badges) are already plain Capsule-shaped `Text`, not buttons --
/// keeping this style capsule-shaped too meant two visually-identical
/// shapes meaning different things. A "Pill" name on a non-pill shape
/// would just be a new confusion in the other direction.
public struct ActionButtonStyle: ButtonStyle {
    var filled: Bool = true
    @Environment(\.appTheme) private var theme
    @State private var isHovering = false

    public init(filled: Bool = true) {
        self.filled = filled
    }

    public func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(PCorpFont.body(12.5, weight: .semibold))
            .padding(.horizontal, 16)
            .padding(.vertical, 9)
            .background(
                RoundedRectangle(cornerRadius: Radius.md).fill(fillColor(pressed: configuration.isPressed))
            )
            .foregroundStyle(filled ? theme.accentText : theme.textPrimary)
            .opacity(configuration.isPressed ? 0.9 : 1)
            .scaleEffect(configuration.isPressed ? 0.97 : (isHovering ? 1.015 : 1))
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
            .animation(.easeOut(duration: 0.12), value: isHovering)
            .onHover { isHovering = $0 }
    }

    private func fillColor(pressed: Bool) -> Color {
        if filled {
            return pressed ? theme.accentFill.opacity(0.85) : theme.accentFill
        }
        if pressed { return theme.textPrimary.opacity(0.11) }
        if isHovering { return theme.textPrimary.opacity(0.09) }
        return theme.textPrimary.opacity(0.055)
    }
}

extension ButtonStyle where Self == ActionButtonStyle {
    public static var actionFilled: ActionButtonStyle { ActionButtonStyle(filled: true) }
    public static var actionTinted: ActionButtonStyle { ActionButtonStyle(filled: false) }
}

/// Flat, opaque "floating card" surface (2026-08-31, UI cleanup) --
/// replaces the material-blur + doubled-background hack independently
/// reimplemented in 14+ view files, none of which used the
/// `surfaceElevated` token `AppTheme` already defines for exactly this
/// purpose. Radius is a caller-supplied parameter, not remapped onto
/// `Radius.*` tokens here -- that's a separate, later cleanup once these
/// values are settled, not bundled into a glassmorphism removal pass.
public extension View {
    func cardSurface(radius: CGFloat) -> some View {
        modifier(CardSurfaceModifier(radius: radius))
    }
}

private struct CardSurfaceModifier: ViewModifier {
    let radius: CGFloat
    @Environment(\.appTheme) private var theme

    func body(content: Content) -> some View {
        content
            .background(RoundedRectangle(cornerRadius: radius).fill(theme.surfaceElevated))
            .overlay(RoundedRectangle(cornerRadius: radius).strokeBorder(theme.surfaceBorder))
    }
}

/// A circular icon-only button with real hover/press feedback — replaces
/// bare `Image(systemName:)` glyphs sitting unstyled in toolbars (the top
/// bar's search/mic icons had none of this before).
public struct IconButtonStyle: ButtonStyle {
    @Environment(\.appTheme) private var theme
    @State private var isHovering = false

    public init() {}

    public func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 15))
            .foregroundStyle(theme.textPrimary)
            .frame(width: 34, height: 34)
            .background(
                Circle().fill(
                    configuration.isPressed
                        ? theme.textPrimary.opacity(0.10)
                        : (isHovering ? theme.textPrimary.opacity(0.06) : Color.clear)
                )
            )
            .scaleEffect(configuration.isPressed ? 0.94 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
            .animation(.easeOut(duration: 0.12), value: isHovering)
            .onHover { isHovering = $0 }
    }
}

extension ButtonStyle where Self == IconButtonStyle {
    public static var icon: IconButtonStyle { IconButtonStyle() }
}

/// Tap a value to edit it in place, commit on Return or on losing focus —
/// the one shared primitive behind Editability Pass 1 (2026-09-17). An
/// audit found only two real inline writes anywhere in this app (Joshx's
/// status pickers, Triggers/Automations' toggles); everything else --
/// People's contact fields, Finance's manual balances -- rendered as
/// static `Text` with no way to fix a wrong number without going through
/// Frank in chat. This is the one edit-affordance (a small trailing
/// `pencil`, always the same glyph) reused everywhere that changes, so
/// "this is editable" reads as one consistent visual language across
/// screens rather than a different treatment per view.
///
/// Deliberately generic on `String` only, not typed per field -- a caller
/// editing a number (Finance's balances) converts to/from `Double` itself
/// in its own `onCommit`, same "the primitive stays reusable, type-
/// specific handling stays at the call site" reasoning as `cardSurface`'s
/// caller-supplied radius above.
///
/// Commit is explicit, never a silent autosave: `.onSubmit` (Return, both
/// platforms) and losing focus (tapping away) are the only two triggers --
/// there's deliberately no `onChange(of:)` on the draft text watching
/// every keystroke. Doesn't need `GrowingChatInput.swift`'s platform-
/// specific key handling (a `TextEditor` there has to tell a Return-to-
/// send apart from a literal newline); a single-line `TextField` has no
/// such ambiguity to resolve, so plain `.onSubmit` already does the right
/// thing on both macOS and iOS.
///
/// Optimistic like Triggers' own toggle -- exits edit mode immediately
/// on commit rather than waiting on the network; the caller's `onCommit`
/// is responsible for surfacing a failure through its own client's
/// existing `errorMessage`, same as every other write in this app already
/// does, not a new error-handling path invented here.
public struct InlineEditableText: View {
    let value: String
    let placeholder: String
    let onCommit: (String) async -> Void

    @State private var isEditing = false
    @State private var draft = ""
    @FocusState private var isFocused: Bool
    @Environment(\.appTheme) private var theme

    public init(value: String, placeholder: String = "", onCommit: @escaping (String) async -> Void) {
        self.value = value
        self.placeholder = placeholder
        self.onCommit = onCommit
    }

    public var body: some View {
        if isEditing {
            TextField(placeholder, text: $draft)
                .textFieldStyle(.plain)
                .focused($isFocused)
                .onSubmit { commit() }
                .onChange(of: isFocused) { _, focused in
                    if !focused { commit() }
                }
                .onAppear { isFocused = true }
        } else {
            HStack(spacing: 4) {
                Text(value.isEmpty ? placeholder : value)
                    .foregroundStyle(value.isEmpty ? theme.textTertiary : theme.textPrimary)
                Image(systemName: "pencil")
                    .font(.system(size: 10))
                    .foregroundStyle(theme.textTertiary.opacity(0.6))
            }
            .contentShape(Rectangle())
            .onTapGesture {
                draft = value
                isEditing = true
            }
        }
    }

    private func commit() {
        isEditing = false
        let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed != value else { return }
        Task { await onCommit(trimmed) }
    }
}
