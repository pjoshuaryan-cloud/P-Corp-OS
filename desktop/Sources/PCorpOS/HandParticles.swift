import SwiftUI
import AppKit

/// Renders an SF Symbol (a hand shape) to an off-screen bitmap, then samples
/// its alpha on a grid to draw a halftone/dot-matrix version of it — the
/// "particle hand" effect from Joshua's reference image. Deliberately uses
/// `ImageRenderer` (a well-documented SwiftUI API) to do the actual
/// rendering, and `NSBitmapImageRep.colorAt(x:y:)` (a safe, documented
/// pixel-reading API) rather than manually parsing raw CGImage bytes —
/// hand-parsing pixel formats is exactly the kind of thing that's easy to
/// get subtly wrong (byte order, premultiplied alpha) in ways that are hard
/// to catch without visually previewing the result, which Claude can't do
/// for a native window. Expect this to need a look-and-correct pass.
struct HandParticles: View {
    let systemName: String
    var columns: Int = 26
    var rows: Int = 34
    var dotColor: Color = .black
    var mirrored: Bool = false

    @State private var samples: [[Double]] = []

    var body: some View {
        Canvas { context, size in
            guard !samples.isEmpty else { return }
            let cellW = size.width / CGFloat(columns)
            let cellH = size.height / CGFloat(rows)

            for row in 0..<rows {
                for col in 0..<columns {
                    let alpha = samples[row][col]
                    guard alpha > 0.1 else { continue }

                    let sampleCol = mirrored ? (columns - 1 - col) : col
                    let dotDiameter = cellW * 0.55 * CGFloat(min(alpha * 1.5, 1.0))
                    guard dotDiameter > 0.4 else { continue }

                    let cx = (CGFloat(sampleCol) + 0.5) * cellW
                    let cy = (CGFloat(row) + 0.5) * cellH
                    let rect = CGRect(
                        x: cx - dotDiameter / 2,
                        y: cy - dotDiameter / 2,
                        width: dotDiameter,
                        height: dotDiameter
                    )
                    context.fill(Path(ellipseIn: rect), with: .color(dotColor.opacity(min(alpha * 1.7, 0.85))))
                }
            }
        }
        .onAppear(perform: generateSamples)
    }

    private func generateSamples() {
        let scale = 6 // supersample so small grids still get smooth alpha gradients, not just 0/1
        let pixelWidth = columns * scale
        let pixelHeight = rows * scale

        let renderer = ImageRenderer(
            content:
                Image(systemName: systemName)
                    .resizable()
                    .scaledToFit()
                    .foregroundStyle(.black)
                    .frame(width: CGFloat(pixelWidth), height: CGFloat(pixelHeight))
        )
        renderer.scale = 1

        guard let cgImage = renderer.cgImage else { return }
        let bitmap = NSBitmapImageRep(cgImage: cgImage)

        var result: [[Double]] = []
        for row in 0..<rows {
            var rowSamples: [Double] = []
            for col in 0..<columns {
                let px = min(bitmap.pixelsWide - 1, Int((CGFloat(col) + 0.5) / CGFloat(columns) * CGFloat(bitmap.pixelsWide)))
                let py = min(bitmap.pixelsHigh - 1, Int((CGFloat(row) + 0.5) / CGFloat(rows) * CGFloat(bitmap.pixelsHigh)))
                let alpha = bitmap.colorAt(x: px, y: py)?.alphaComponent ?? 0
                rowSamples.append(Double(alpha))
            }
            result.append(rowSamples)
        }
        samples = result
    }
}
