import Foundation

/// Spacing/Radius/AnimationTiming design tokens (2026-08-20, Face-Lift
/// brief's "Design Tokens" section) — named constants for new/touched code
/// going forward, not a retrofit of the ~40+ existing padding/cornerRadius
/// call sites elsewhere in the app. Radius values are deliberately
/// calibrated to the app's own existing dominant radii (12 and 18, the
/// most common values already in real use) rather than the brief's literal
/// suggested 4–16 range, so new elements don't read as visually foreign
/// next to everything untouched around them. AnimationTiming values are
/// likewise named after timings already used throughout the app today
/// (button hover/press, nav-selection slide, launch fade-in), not invented.
public enum Spacing {
    public static let xs: CGFloat = 8
    public static let sm: CGFloat = 12
    public static let md: CGFloat = 16
    public static let lg: CGFloat = 24
    public static let xl: CGFloat = 32
    public static let xxl: CGFloat = 48
    public static let xxxl: CGFloat = 64
}

public enum Radius {
    public static let xs: CGFloat = 6
    public static let sm: CGFloat = 10
    public static let md: CGFloat = 12
    public static let lg: CGFloat = 16
    public static let xl: CGFloat = 18
    public static let xxl: CGFloat = 24
}

public enum AnimationTiming {
    public static let instant: Double = 0.12
    public static let quick: Double = 0.18
    public static let standard: Double = 0.22
    public static let entrance: Double = 1.1
}
