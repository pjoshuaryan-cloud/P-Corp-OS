import Foundation
import Quartz
let args = CommandLine.arguments
let doc = CGPDFDocument(URL(fileURLWithPath: args[1]) as CFURL)!
print("pages", doc.numberOfPages)
for i in 1...doc.numberOfPages {
    let page = doc.page(at: i)!
    let box = page.getBoxRect(.mediaBox)
    let scale: CGFloat = 1.5
    let w = Int(box.width * scale), h = Int(box.height * scale)
    let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1)); ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.scaleBy(x: scale, y: scale); ctx.drawPDFPage(page)
    let img = NSBitmapImageRep(cgImage: ctx.makeImage()!)
    let data = img.representation(using: .png, properties: [:])!
    try! data.write(to: URL(fileURLWithPath: "\(args[2])/p\(i).png"))
}
