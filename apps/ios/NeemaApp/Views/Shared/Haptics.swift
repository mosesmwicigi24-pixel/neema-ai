import UIKit

/// The app's few haptics — Android's Material ripples have no twin on iOS,
/// where a light tap confirms a send, a move or a switch, and the system's
/// notice marks an error toast.
enum Haptics {
    static func tap() { UIImpactFeedbackGenerator(style: .light).impactOccurred() }
    static func success() { UINotificationFeedbackGenerator().notificationOccurred(.success) }
    static func error() { UINotificationFeedbackGenerator().notificationOccurred(.error) }
}
