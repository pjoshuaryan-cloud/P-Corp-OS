import SwiftUI

/// Three pulsing dots shown while Frank is composing a reply -- extracted
/// (2026-09-18, Interaction Polish Pass) from desktop and iOS WarRoomView.swift,
/// which each carried a byte-for-byte-identical private copy.
public struct TypingIndicatorDots: View {
    @Environment(\.appTheme) private var theme
    @State private var animate = false

    public init() {}

    public var body: some View {
        HStack(spacing: 4) {
            ForEach(0..<3, id: \.self) { index in
                Circle()
                    .fill(theme.textSecondary)
                    .frame(width: 5, height: 5)
                    .scaleEffect(animate ? 1 : 0.5)
                    .opacity(animate ? 1 : 0.4)
                    .animation(
                        .easeInOut(duration: 0.55)
                            .repeatForever(autoreverses: true)
                            .delay(Double(index) * 0.15),
                        value: animate
                    )
            }
        }
        .onAppear { animate = true }
    }
}
