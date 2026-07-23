import SwiftUI

struct WarRoomView: View {
    @State private var inputText: String = ""
    @Environment(\.appTheme) private var theme
    @FocusState private var isInputFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            topBar

            Spacer(minLength: 0)

            VStack(alignment: .leading, spacing: 12) {
                Text("Good morning, Joshx.")
                    .font(PCorpFont.display(38, weight: .bold))
                    .foregroundStyle(theme.textPrimary)
                Text("I'm Frank. How can I help you today?")
                    .font(PCorpFont.body(17))
                    .foregroundStyle(theme.textSecondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 48)

            Spacer(minLength: 20)

            // Hand-particle effect (HandParticles.swift) parked for now —
            // built, but pulled from the layout per direct feedback. Revisit
            // as its own session rather than tuning it inside other work.
            FrankOrb()
                .frame(width: 150, height: 150)
                .frame(maxWidth: .infinity)

            Spacer(minLength: 20)

            inputBar
                .padding(.horizontal, 48)
                .padding(.bottom, 32)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
    }

    private var topBar: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Good morning, Joshx.")
                    .font(PCorpFont.body(13, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(Date.now.formatted(date: .complete, time: .omitted))
                    .font(PCorpFont.body(11))
                    .foregroundStyle(theme.textSecondary)
            }

            Spacer()

            PLogoMark()

            Spacer()

            HStack(spacing: 4) {
                Button {
                    // no-op: shell only, not wired up yet
                } label: {
                    Image(systemName: "magnifyingglass")
                }
                .buttonStyle(.icon)

                Button {
                    // no-op: shell only, not wired up yet
                } label: {
                    Image(systemName: "waveform.circle.fill")
                }
                .buttonStyle(.icon)

                Button {
                    // no-op: shell only, not wired up yet
                } label: {
                    Label("Mission", systemImage: "plus")
                }
                .buttonStyle(.pillFilled)
                .padding(.leading, 8)
            }
        }
        .padding(.horizontal, 32)
        .padding(.vertical, 20)
    }

    private var inputBar: some View {
        HStack(spacing: 12) {
            Image(systemName: "waveform")
                .foregroundStyle(theme.textSecondary)
            TextField("Talk to Frank...", text: $inputText)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(14))
                .foregroundStyle(theme.textPrimary)
                .focused($isInputFocused)

            Button {
                // no-op: shell only, not wired up yet
            } label: {
                Image(systemName: "arrow.up")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(theme.accentText)
                    .frame(width: 32, height: 32)
                    .background(Circle().fill(theme.accentFill))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 24)
                .fill(theme.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 24)
                .strokeBorder(isInputFocused ? theme.textPrimary : theme.surfaceBorder, lineWidth: isInputFocused ? 2 : 1)
        )
        .shadow(color: theme.cardShadow, radius: isInputFocused ? 20 : 16, x: 0, y: isInputFocused ? 8 : 6)
        .animation(.easeOut(duration: 0.15), value: isInputFocused)
    }
}

/// A restrained stand-in for Frank's presence — now a cluster of individual
/// particles rather than one solid shape, per direct feedback ("a blob of
/// particles floating" instead of a continuous liquid form). No mascot
/// features (no face, no eyes) — presence still comes from motion and
/// texture only, per FOUNDER_BRIEF.md/UI_GUIDELINES.md's anti-mascot
/// direction. Unlike the earlier hand-particle attempt, this doesn't sample
/// a bitmap — particle positions are generated directly from a deterministic
/// seeded random sequence, which is simple and reliable enough to trust
/// without a visual preview (the risk there was in reading pixels back out
/// of a rendered image; there's no such step here).
private struct FrankOrb: View {
    @State private var floatUp = false
    @Environment(\.appTheme) private var theme

    private struct Particle {
        let angle: Double
        let radiusFactor: Double // 0...1, distance from center as a fraction of the cluster's radius
        let size: CGFloat
        let phaseOffset: Double
    }

    /// Deterministic (fixed seed), not true randomness — same layout every
    /// launch, matching the rest of the shell's "reproducible, not jittery
    /// between runs" pattern.
    private static let particles: [Particle] = {
        var rng = SeededGenerator(seed: 7)
        return (0..<120).map { _ in
            let angle = Double.random(in: 0..<(2 * .pi), using: &rng)
            // Squaring biases points toward the center for a denser core that
            // thins out toward the edge, rather than a uniform-density disc.
            let radiusFactor = pow(Double.random(in: 0...1, using: &rng), 1.7)
            let size = CGFloat.random(in: 2.0...5.0, using: &rng)
            let phaseOffset = Double.random(in: 0..<(2 * .pi), using: &rng)
            return Particle(angle: angle, radiusFactor: radiusFactor, size: size, phaseOffset: phaseOffset)
        }
    }()

    var body: some View {
        ZStack {
            // Soft contact shadow — grounds the cluster so the float reads
            // as floating rather than just sliding up and down in place.
            Ellipse()
                .fill(theme.textPrimary.opacity(floatUp ? 0.08 : 0.16))
                .frame(width: floatUp ? 100 : 72, height: floatUp ? 14 : 10)
                .blur(radius: 8)
                .offset(y: 74)

            TimelineView(.animation) { timeline in
                Canvas { context, size in
                    let center = CGPoint(x: size.width / 2, y: size.height / 2)
                    let maxRadius = min(size.width, size.height) / 2
                    let t = timeline.date.timeIntervalSinceReferenceDate

                    for particle in Self.particles {
                        let r = maxRadius * particle.radiusFactor
                        let x = center.x + r * cos(particle.angle)
                        let y = center.y + r * sin(particle.angle)

                        // Per-particle shimmer, out of phase with its
                        // neighbors, so the cluster reads as alive rather
                        // than a static scatter of dots.
                        let shimmer = (sin(t * 0.9 + particle.phaseOffset) + 1) / 2 // 0...1
                        let baseOpacity = 0.18 + (1 - particle.radiusFactor) * 0.62
                        let opacity = baseOpacity * (0.55 + shimmer * 0.45)
                        let dotSize = particle.size * (0.85 + shimmer * 0.15)

                        let rect = CGRect(x: x - dotSize / 2, y: y - dotSize / 2, width: dotSize, height: dotSize)
                        context.fill(Path(ellipseIn: rect), with: .color(theme.textPrimary.opacity(opacity)))
                    }
                }
            }
            .offset(y: floatUp ? -10 : 10)
        }
        .animation(.easeInOut(duration: 3.4).repeatForever(autoreverses: true), value: floatUp)
        .onAppear { floatUp = true }
    }
}

/// A minimal deterministic random generator (linear congruential) — used
/// wherever this shell needs "random-looking but reproducible every launch"
/// placement, since Swift's default generator is intentionally
/// non-reproducible between runs.
private struct SeededGenerator: RandomNumberGenerator {
    private var state: UInt64
    init(seed: UInt64) { self.state = seed }
    mutating func next() -> UInt64 {
        state = state &* 6364136223846793005 &+ 1442695040888963407
        return state
    }
}

/// Placeholder P mark — a plain styled glyph, deliberately not the real
/// logo. Three rendering attempts at the actual mark (a hand-built rounded
/// stem+bowl path, a hand-built angular folded-ribbon path, and rendering
/// Joshua's real P_logo.pdf via PDFKit) all fell short on direct feedback.
/// Rather than keep tuning something not working, Joshua asked to park it —
/// the real source file still lives at `Resources/P_logo.pdf` and is still
/// bundled in `Package.swift` for whenever the logo work picks back up.
private struct PLogoMark: View {
    var body: some View {
        Text("P")
            .font(.system(size: 22, weight: .bold, design: .rounded))
            .foregroundStyle(Color.black)
            .frame(width: 20, height: 24, alignment: .center)
    }
}
