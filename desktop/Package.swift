// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "PCorpOS",
    platforms: [
        .macOS(.v14)
    ],
    dependencies: [
        .package(path: "../PCorpKit")
    ],
    targets: [
        .executableTarget(
            name: "PCorpOS",
            dependencies: ["PCorpKit"],
            path: "Sources/PCorpOS",
            resources: [
                .copy("Resources/P_logo.pdf"),
                .copy("Resources/alpha_mode_logo.png"),
                .copy("Resources/p_logo_black.png"),
                .copy("Resources/app_icon.png"),
                .copy("Resources/AppIcon.icns")
            ]
        )
    ]
)
