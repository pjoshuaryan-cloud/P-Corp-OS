// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "PCorpOS",
    platforms: [
        .macOS(.v14)
    ],
    targets: [
        .executableTarget(
            name: "PCorpOS",
            path: "Sources/PCorpOS"
        )
    ]
)
