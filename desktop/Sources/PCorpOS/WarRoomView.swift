import SwiftUI

struct WarRoomView: View {
    @State private var inputText: String = ""

    var body: some View {
        VStack(spacing: 0) {
            topBar

            Spacer(minLength: 0)

            VStack(alignment: .leading, spacing: 12) {
                Text("Good morning, Joshx.")
                    .font(PCorpFont.display(38, weight: .bold))
                Text("I'm Frank. How can I help you today?")
                    .font(PCorpFont.body(17))
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 48)

            Spacer(minLength: 20)

            FrankOrb()
                .frame(width: 150, height: 150)
                .frame(maxWidth: .infinity)

            Spacer(minLength: 20)

            inputBar
                .padding(.horizontal, 48)
                .padding(.bottom, 32)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.white)
    }

    private var topBar: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Good morning, Joshx.")
                    .font(PCorpFont.body(13, weight: .semibold))
                Text(Date.now.formatted(date: .complete, time: .omitted))
                    .font(PCorpFont.body(11))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            PLogoMark()

            Spacer()

            HStack(spacing: 16) {
                Image(systemName: "magnifyingglass")
                Image(systemName: "waveform.circle.fill")
                Button {
                    // no-op: shell only, not wired up yet
                } label: {
                    Label("Mission", systemImage: "plus")
                }
                .buttonStyle(.pillFilled)
            }
            .font(.system(size: 15))
            .foregroundStyle(.primary)
        }
        .padding(.horizontal, 32)
        .padding(.vertical, 20)
    }

    private var inputBar: some View {
        HStack(spacing: 12) {
            Image(systemName: "waveform")
                .foregroundStyle(.secondary)
            TextField("Talk to Frank...", text: $inputText)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(14))

            Button {
                // no-op: shell only, not wired up yet
            } label: {
                Image(systemName: "arrow.up")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 32, height: 32)
                    .background(Circle().fill(Color.black))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 24)
                .fill(Color(white: 0.97))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 24)
                .strokeBorder(Color.black.opacity(0.08))
        )
    }
}

/// A restrained stand-in for Frank's presence — organic, floating,
/// continuously and slowly changing shape, no mascot features (no face, no
/// eyes). FOUNDER_BRIEF.md and UI_GUIDELINES.md are explicit that Frank's
/// presence should come from behavior, not a character on screen; this is
/// deliberately just texture and motion, nothing more. The continuous
/// morph (rather than a static shape that only floats) is what pushes it
/// from "liquid" toward "surreal" — it never settles into a fixed form.
private struct FrankOrb: View {
    @State private var floatUp = false
    @State private var morphPhase: CGFloat = 0

    var body: some View {
        ZStack {
            // Soft contact shadow — grounds the shape so the float reads as
            // floating rather than just sliding up and down in empty space.
            Ellipse()
                .fill(Color.black.opacity(floatUp ? 0.10 : 0.22))
                .frame(width: floatUp ? 100 : 72, height: floatUp ? 14 : 10)
                .blur(radius: 8)
                .offset(y: 74)

            BlobShape(phase: morphPhase)
                .fill(
                    RadialGradient(
                        colors: [Color(white: 0.32), Color(white: 0.05), Color.black],
                        center: UnitPoint(x: 0.32, y: 0.28),
                        startRadius: 3,
                        endRadius: 110
                    )
                )
                .overlay(
                    // Tight, bright specular highlight — glossy/liquid surfaces
                    // catch light in a small defined spot, not a broad soft glow.
                    BlobShape(phase: morphPhase)
                        .fill(Color.white.opacity(0.6))
                        .blur(radius: 5)
                        .frame(width: 32, height: 20)
                        .offset(x: -22, y: -30)
                        .mask(BlobShape(phase: morphPhase))
                )
                .overlay(
                    // Faint rim light along the lower edge, as if reflecting
                    // ambient light from the surface below — reinforces volume.
                    BlobShape(phase: morphPhase)
                        .fill(Color.white.opacity(0.08))
                        .blur(radius: 8)
                        .offset(x: 14, y: 26)
                        .mask(BlobShape(phase: morphPhase))
                )
                .offset(y: floatUp ? -10 : 10)
        }
        .animation(.easeInOut(duration: 3.4).repeatForever(autoreverses: true), value: floatUp)
        .onAppear {
            floatUp = true
            withAnimation(.linear(duration: 9).repeatForever(autoreverses: false)) {
                morphPhase = 2 * .pi
            }
        }
    }
}

/// An irregular closed shape — not a perfect circle, not fixed. Points are
/// spaced around a circle with per-point base variance, then perturbed by a
/// slow sine wave driven by `phase`; smoothing through midpoints keeps the
/// outline organic rather than polygonal. Because `phase` is animatable,
/// SwiftUI interpolates the actual path continuously as it changes, so the
/// silhouette itself keeps drifting — not just its position — for a more
/// surreal, alive quality rather than a static shape that only floats.
private struct BlobShape: Shape {
    var phase: CGFloat

    var animatableData: CGFloat {
        get { phase }
        set { phase = newValue }
    }

    private let baseVariance: [CGFloat] = [
        1.00, 1.04, 1.02, 1.07, 0.97, 1.03, 0.94, 1.05,
        0.98, 1.06, 0.95, 1.02, 0.99, 1.05, 0.96, 1.01,
    ]
    private let wobbleAmplitude: CGFloat = 0.05

    func path(in rect: CGRect) -> Path {
        let center = CGPoint(x: rect.midX, y: rect.midY)
        let baseRadius = min(rect.width, rect.height) / 2
        let count = baseVariance.count

        let points: [CGPoint] = (0..<count).map { i in
            let angle = (CGFloat(i) / CGFloat(count)) * 2 * .pi
            let wobble = sin(phase + CGFloat(i) * 0.9) * wobbleAmplitude
            let r = baseRadius * (baseVariance[i] + wobble)
            return CGPoint(x: center.x + r * cos(angle), y: center.y + r * sin(angle))
        }

        var path = Path()
        path.move(to: midpoint(points[count - 1], points[0]))
        for i in 0..<count {
            let p1 = points[i]
            let p2 = points[(i + 1) % count]
            path.addQuadCurve(to: midpoint(p1, p2), control: p1)
        }
        path.closeSubpath()
        return path
    }

    private func midpoint(_ a: CGPoint, _ b: CGPoint) -> CGPoint {
        CGPoint(x: (a.x + b.x) / 2, y: (a.y + b.y) / 2)
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
