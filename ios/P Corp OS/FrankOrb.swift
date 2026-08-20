import PCorpKit
import SwiftUI

/// Port of desktop's own FrankOrb (2026-08-20, Face-Lift iOS parity pass)
/// -- pure SwiftUI (Canvas/TimelineView), no AppKit dependency, so this is
/// a faithful port, not an approximation. Same OrbState enum, same real
/// per-state motion (listening contracts inward, error mutes to orange),
/// same Reduce Motion support.
///
/// One real state NOT ported: `.speaking`. Desktop has it because desktop
/// has real text-to-speech (VoiceOutput.swift) -- iOS never got that (see
/// this repo's own history: voice INPUT was ported to iOS, voice OUTPUT
/// wasn't), so there's no real audio signal for a speaking state to react
/// to on iOS today. Not fabricated with a fake/silent placeholder --
/// simply not built until iOS gets real TTS, the same "no honest signal,
/// don't build it" discipline already applied to desktop's own Thinking/
/// Executing states.
///
/// Also, unlike desktop (where this only ever appears during an idle/
/// empty-thread moment or push-to-talk), iOS's WarRoomView has a
/// different layout -- dashboard cards + chat thread are always visible,
/// there's no separate "idle, no thread yet" screen state to put an idle
/// orb into without a bigger structural change to that layout. So this
/// pass wires the orb into the one moment iOS already has a real, distinct
/// full-screen-ish state for: push-to-talk listening (and its error
/// case) -- replacing "the mic button just turns red" with the same real
/// visual feedback desktop has. An idle-state placement is deliberately
/// left for a separate, later decision about iOS's WarRoomView layout
/// itself, not bundled into this pass.
struct FrankOrb: View {
    enum OrbState: Equatable {
        case idle
        case listening(audioLevel: Double)
        case error
    }

    var state: OrbState = .idle

    @State private var floatUp = false
    @Environment(\.appTheme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var audioLevel: Double? {
        switch state {
        case .idle, .error: nil
        case .listening(let level): level
        }
    }

    private var radiusScale: Double {
        switch state {
        case .idle, .error: 1.0
        case .listening: 0.78
        }
    }

    private var particleColor: Color {
        state == .error ? .orange : theme.textPrimary
    }

    private struct Particle {
        let angle: Double
        let radiusFactor: Double
        let size: CGFloat
        let phaseOffset: Double
    }

    private static let particles: [Particle] = {
        var rng = SeededGenerator(seed: 7)
        return (0..<450).map { _ in
            let angle = Double.random(in: 0..<(2 * .pi), using: &rng)
            let radiusFactor = pow(Double.random(in: 0...1, using: &rng), 1.7)
            let size = CGFloat.random(in: 2.2...5.8, using: &rng)
            let phaseOffset = Double.random(in: 0..<(2 * .pi), using: &rng)
            return Particle(angle: angle, radiusFactor: radiusFactor, size: size, phaseOffset: phaseOffset)
        }
    }()

    var body: some View {
        ZStack {
            Ellipse()
                .fill(theme.textPrimary.opacity(floatUp ? 0.08 : 0.16))
                .frame(width: floatUp ? 100 : 72, height: floatUp ? 14 : 10)
                .blur(radius: 8)
                .offset(y: 74)

            TimelineView(.animation(paused: reduceMotion)) { timeline in
                Canvas { context, size in
                    let center = CGPoint(x: size.width / 2, y: size.height / 2)
                    let maxRadius = min(size.width, size.height) / 2
                    let t = timeline.date.timeIntervalSinceReferenceDate
                    let scale = radiusScale
                    let color = particleColor

                    for particle in Self.particles {
                        let r = maxRadius * particle.radiusFactor * scale
                        let x = center.x + r * cos(particle.angle)
                        let y = center.y + r * sin(particle.angle)

                        // Exact match for desktop's own current shimmer
                        // logic (WarRoomView.swift there) -- idle: slow,
                        // low-amplitude synthetic wave ("almost
                        // imperceptibly"). Error: flat, no shimmer,
                        // restrained rather than alarming. Listening:
                        // real mic level dominates, a small synthetic
                        // component still blended in so it keeps reading
                        // as organic per-particle motion.
                        let syntheticShimmer = (sin(t * 0.5 + particle.phaseOffset) + 1) / 2
                        let shimmer: Double
                        switch state {
                        case .error:
                            shimmer = 0.4
                        case .idle:
                            shimmer = reduceMotion ? 0.5 : 0.35 + syntheticShimmer * 0.3
                        case .listening:
                            let level = audioLevel ?? 0
                            shimmer = reduceMotion ? level : min(1.0, syntheticShimmer * 0.2 + level * 0.9)
                        }
                        let baseOpacity = 0.32 + (1 - particle.radiusFactor) * 0.68
                        let opacity = min(baseOpacity * (0.7 + shimmer * 0.3), 1.0)
                        let dotSize = particle.size * (0.85 + shimmer * 0.15)

                        let rect = CGRect(x: x - dotSize / 2, y: y - dotSize / 2, width: dotSize, height: dotSize)
                        context.fill(Path(ellipseIn: rect), with: .color(color.opacity(opacity)))
                    }
                }
            }
            .offset(y: (floatUp && !reduceMotion) ? -10 : (reduceMotion ? 0 : 10))
        }
        .animation(reduceMotion ? nil : .easeInOut(duration: 3.4).repeatForever(autoreverses: true), value: floatUp)
        .onAppear { if !reduceMotion { floatUp = true } }
    }
}

/// Same minimal deterministic RNG as desktop's own copy -- kept as its
/// own private type here too rather than sharing one via PCorpKit, same
/// "small enough to just duplicate" reasoning already applied to other
/// small pieces (NavItem, SectionPlaceholderView).
private struct SeededGenerator: RandomNumberGenerator {
    private var state: UInt64
    init(seed: UInt64) { self.state = seed }
    mutating func next() -> UInt64 {
        state = state &* 6364136223846793005 &+ 1442695040888963407
        return state
    }
}
