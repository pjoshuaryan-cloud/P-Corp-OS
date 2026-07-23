import SwiftUI

struct WarRoomView: View {
    @State private var inputText: String = ""

    var body: some View {
        VStack(spacing: 0) {
            topBar

            Spacer(minLength: 0)

            VStack(alignment: .leading, spacing: 12) {
                Text("Good morning, Joshua.")
                    .font(.system(size: 34, weight: .semibold))
                Text("I'm Frank. How can I help you today?")
                    .font(.system(size: 17))
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 48)

            Spacer(minLength: 24)

            FrankOrb()
                .frame(width: 220, height: 220)

            Spacer(minLength: 32)

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
                Text("Good morning, Joshua.")
                    .font(.system(size: 13, weight: .medium))
                Text(Date.now.formatted(date: .complete, time: .omitted))
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Image(systemName: "p.square")
                .font(.system(size: 16))
                .foregroundStyle(.secondary)

            Spacer()

            HStack(spacing: 16) {
                Image(systemName: "magnifyingglass")
                Image(systemName: "waveform.circle.fill")
                Button {
                    // no-op: shell only, not wired up yet
                } label: {
                    Label("New Task", systemImage: "plus")
                        .font(.system(size: 12, weight: .medium))
                }
                .buttonStyle(.borderedProminent)
                .tint(.black)
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
                .font(.system(size: 14))

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

/// A restrained stand-in for Frank's presence — organic, floating, no mascot
/// features (no face, no eyes). FOUNDER_BRIEF.md and UI_GUIDELINES.md are
/// explicit that Frank's presence should come from behavior, not a character
/// on screen; this shape is deliberately just texture and motion, nothing more.
private struct FrankOrb: View {
    @State private var floatUp = false

    var body: some View {
        ZStack {
            // Soft contact shadow — grounds the shape so the float reads as
            // floating rather than just sliding up and down in empty space.
            Ellipse()
                .fill(Color.black.opacity(floatUp ? 0.08 : 0.14))
                .frame(width: floatUp ? 120 : 150, height: 18)
                .blur(radius: 8)
                .offset(y: 100)

            BlobShape()
                .fill(
                    LinearGradient(
                        colors: [Color(white: 0.16), Color.black],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .overlay(
                    BlobShape()
                        .fill(Color.white.opacity(0.10))
                        .blur(radius: 14)
                        .offset(x: -28, y: -32)
                        .mask(BlobShape())
                )
                .offset(y: floatUp ? -12 : 12)
        }
        .animation(.easeInOut(duration: 3.2).repeatForever(autoreverses: true), value: floatUp)
        .onAppear { floatUp = true }
    }
}

/// A fixed, irregular closed shape — not a perfect circle. Built by taking
/// points around a circle with per-point radius variance, then smoothing
/// through their midpoints so the outline reads as organic rather than
/// polygonal. Deterministic (no randomness) so it looks the same every launch.
private struct BlobShape: Shape {
    private let radiusVariance: [CGFloat] = [1.0, 1.1, 0.92, 1.05, 0.88, 1.12, 0.95, 1.02, 0.90, 1.06]

    func path(in rect: CGRect) -> Path {
        let center = CGPoint(x: rect.midX, y: rect.midY)
        let baseRadius = min(rect.width, rect.height) / 2
        let count = radiusVariance.count

        let points: [CGPoint] = (0..<count).map { i in
            let angle = (CGFloat(i) / CGFloat(count)) * 2 * .pi
            let r = baseRadius * radiusVariance[i]
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
