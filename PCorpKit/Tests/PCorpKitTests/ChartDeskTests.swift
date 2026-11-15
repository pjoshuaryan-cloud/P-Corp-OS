import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers
import XCTest
@testable import PCorpKit

// The simplified Trading tab (2026-11-15): screenshots are shrunk before upload, analyses are kept on the device (newest 5
// can be continued, older ones read-only), deleting works, and a failed analysis says why. The backend is faked: no network.
//   cd PCorpKit && swift test

private func pngImage(width: Int, height: Int) -> Data {
    let ctx = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
                        space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    ctx.setFillColor(CGColor(red: 0.1, green: 0.6, blue: 0.3, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: width, height: height / 2))
    let out = NSMutableData()
    let dest = CGImageDestinationCreateWithData(out, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(dest, ctx.makeImage()!, nil)
    CGImageDestinationFinalize(dest)
    return out as Data
}

private func pixelSize(_ data: Data) -> (Int, Int) {
    let src = CGImageSourceCreateWithData(data as CFData, nil)!
    let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as! [CFString: Any]
    return (props[kCGImagePropertyPixelWidth] as! Int, props[kCGImagePropertyPixelHeight] as! Int)
}

final class ChartDeskTests: XCTestCase {
    var storeURL: URL!

    override func setUp() {
        storeURL = FileManager.default.temporaryDirectory.appendingPathComponent("chartdesk-\(UUID()).json")
    }

    override func tearDown() { try? FileManager.default.removeItem(at: storeURL) }

    func testScreenshotsAreShrunkToJPEG() throws {
        let shot = try XCTUnwrap(ChartScreenshot(imageData: pngImage(width: 5120, height: 2880)))
        let (w, h) = pixelSize(shot.data)
        XCTAssertEqual(shot.mediaType, "image/jpeg")
        XCTAssertEqual(max(w, h), ChartScreenshot.maxPixels, "the long side is scaled to the limit")
        XCTAssertEqual(Double(w) / Double(h), 5120.0 / 2880.0, accuracy: 0.01, "keeps its shape")
        let small = try XCTUnwrap(ChartScreenshot(imageData: pngImage(width: 800, height: 600)))
        XCTAssertEqual(pixelSize(small.data).0, 800, "a small screenshot isn't blown up")
        XCTAssertNil(ChartScreenshot(imageData: Data("not an image".utf8)), "a non-image is refused")
    }

    @MainActor
    func testAnalyzeKeepFollowUpReopenDelete() async throws {
        var posts: [(String, [String: Any])] = []
        let fake: (String, [String: Any]) async -> Result<[String: Any], ChartDeskClient.ChartDeskError> = { path, body in
            posts.append((path, body))
            if let message = body["message"] as? String {
                return .success(["reply": "Answer to \(message)", "history": [["role": "user", "content": "x"], ["role": "assistant", "content": "y"], ["role": "user", "content": message]]])
            }
            return .success(["reply": "**Lean:** bullish -- higher lows.\n**Buy area:** 18,200", "history": [["role": "user", "content": "x"]]])
        }
        let shot = try XCTUnwrap(ChartScreenshot(imageData: pngImage(width: 1200, height: 800)))
        let desk = ChartDeskClient(store: ChartAnalysisStore(url: storeURL), post: fake)
        await desk.analyze([shot, shot], note: "  thinking of a long ")
        XCTAssertEqual(posts.first?.0, "/trade-intelligence/chart-zones")
        XCTAssertEqual((posts.first?.1["images"] as? [Any])?.count, 2, "both screenshots are sent")
        XCTAssertEqual(posts.first?.1["note"] as? String, "thinking of a long", "the note is trimmed")
        XCTAssertEqual(desk.messages.count, 2)
        XCTAssertTrue(desk.canFollowUp)
        XCTAssertEqual(desk.recent.first?.headline, "bullish -- higher lows.", "the list shows the Lean line")

        await desk.followUp("what about the 1-hour?")
        XCTAssertEqual(posts.last?.1["message"] as? String, "what about the 1-hour?")
        XCTAssertEqual(desk.messages.last?.text, "Answer to what about the 1-hour?")

        // A relaunch: the analysis and its follow-up come back from the device, and can still be continued.
        let again = ChartDeskClient(store: ChartAnalysisStore(url: storeURL), post: fake)
        XCTAssertEqual(again.recent.count, 1)
        XCTAssertEqual(again.recent.first?.lines.count, 4, "the follow-up was saved too")
        again.open(try XCTUnwrap(again.recent.first))
        XCTAssertTrue(again.canFollowUp)
        XCTAssertEqual(again.messages.count, 4)

        // Only the newest 5 keep their conversation; older ones can be read but not continued.
        for i in 0..<6 { await again.analyze([shot], note: "chart \(i)") }
        let oldest = try XCTUnwrap(again.recent.last)
        again.open(oldest)
        XCTAssertFalse(again.canFollowUp, "an older analysis is read-only")
        await again.followUp("ignored?")
        XCTAssertEqual(again.messages.count, 4, "no follow-up is sent for a read-only one")
        XCTAssertEqual(ChartAnalysisStore(url: storeURL).load().filter { $0.serverHistory != nil }.count, ChartAnalysisStore.keepConversation)

        again.delete(oldest)
        XCTAssertFalse(again.recent.contains(oldest))
        XCTAssertTrue(again.messages.isEmpty, "deleting the open one clears the screen")
        XCTAssertFalse(ChartAnalysisStore(url: storeURL).load().contains { $0.id == oldest.id }, "and it's gone after a relaunch")
    }

    @MainActor
    func testFailureSaysWhyAndKeepsNothing() async throws {
        let desk = ChartDeskClient(store: ChartAnalysisStore(url: storeURL), post: { _, _ in .failure(.init(message: "Up to 4 screenshots at a time.")) })
        await desk.analyze([try XCTUnwrap(ChartScreenshot(imageData: pngImage(width: 400, height: 300)))], note: "")
        XCTAssertEqual(desk.errorMessage, "Up to 4 screenshots at a time.")
        XCTAssertTrue(desk.messages.isEmpty)
        XCTAssertTrue(desk.recent.isEmpty, "a failed analysis isn't saved")
        XCTAssertFalse(desk.isWorking)
    }
}
