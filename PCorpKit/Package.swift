// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "PCorpKit",
    platforms: [
        .macOS(.v14),
        .iOS(.v17)
    ],
    products: [
        .library(name: "PCorpKit", targets: ["PCorpKit"])
    ],
    targets: [
        .target(
            name: "PCorpKit",
            path: "Sources/PCorpKit"
        )
    ]
)
