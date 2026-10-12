// swift-tools-version: 5.9
// NeemaCore — the iOS app's platform-independent core: wire models, the HTTP
// client with the session rules, sign-in and silent refresh, and the live
// WebSocket feed. It mirrors apps/android/.../core (model, net, auth, ws)
// one type for one type, so it builds and tests on Linux (CI, this
// workstation) as well as on macOS/iOS. The SwiftUI app in NeemaApp/ is the
// only Apple-platform-specific layer.
import PackageDescription

let package = Package(
    name: "NeemaCore",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [
        .library(name: "NeemaCore", targets: ["NeemaCore"]),
    ],
    targets: [
        .target(name: "NeemaCore", path: "Sources/NeemaCore"),
        .testTarget(name: "NeemaCoreTests", dependencies: ["NeemaCore"], path: "Tests/NeemaCoreTests"),
    ],
    swiftLanguageVersions: [.v5]
)
