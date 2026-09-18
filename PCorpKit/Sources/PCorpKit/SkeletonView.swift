import SwiftUI

/// A placeholder "bar" shape for loading content (2026-09-18, interaction
/// polish pass) -- replaces bare `Text("Loading…")`, which every single
/// dashboard in the app used identically. Hand-built rather than SwiftUI's
/// own `.redacted(reason: .placeholder)` -- that needs a real view already
/// populated with (dummy) data to redact, and standing up ~10 different
/// row types with fake data just to blur them out is more machinery than
/// a purpose-built shape. `cardSurface` reused directly so a skeleton
/// occupies the same visual footprint real rows already do, avoiding a
/// layout jump when real data arrives.
public struct SkeletonView: View {
    let height: CGFloat
    @Environment(\.appTheme) private var theme
    @State private var isPulsing = false

    public init(height: CGFloat = 56) {
        self.height = height
    }

    public var body: some View {
        RoundedRectangle(cornerRadius: Radius.md)
            .fill(theme.textPrimary.opacity(isPulsing ? 0.05 : 0.09))
            .frame(height: height)
            .cardSurface(radius: Radius.md)
            .onAppear { isPulsing = true }
            .animation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true), value: isPulsing)
    }
}

/// Stacks `count` `SkeletonView`s at a given spacing -- the actual
/// drop-in for a dashboard's `if isLoading && data == nil` branch.
public struct SkeletonList: View {
    let count: Int
    let height: CGFloat
    let spacing: CGFloat

    public init(count: Int = 3, height: CGFloat = 56, spacing: CGFloat = Spacing.sm) {
        self.count = count
        self.height = height
        self.spacing = spacing
    }

    public var body: some View {
        VStack(spacing: spacing) {
            ForEach(0..<count, id: \.self) { _ in
                SkeletonView(height: height)
            }
        }
    }
}
