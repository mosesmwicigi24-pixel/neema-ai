import Foundation
import AudioToolbox
import UserNotifications
import NeemaCore

/// System notifications through UNUserNotificationCenter (Android's
/// NotificationManager behind `AlertSink`): one row per alert, keyed by the
/// core's id, the group's summary as its own row, and nothing posted when the
/// agent never allowed notifications.
final class SystemAlertSink: AlertSink, @unchecked Sendable {
    private let center = UNUserNotificationCenter.current()
    private var allowed = false
    private var shownIds = Set<Int>()
    private let lock = NSLock()

    init() { refreshPermission() }

    func refreshPermission() {
        center.getNotificationSettings { [weak self] s in
            self?.lock.lock()
            self?.allowed = s.authorizationStatus == .authorized || s.authorizationStatus == .provisional || s.authorizationStatus == .ephemeral
            self?.lock.unlock()
        }
    }

    func canPost() -> Bool { lock.lock(); defer { lock.unlock() }; return allowed }

    func post(_ alert: SystemAlert) {
        let content = UNMutableNotificationContent()
        content.title = alert.title
        content.body = alert.body
        content.sound = alert.priority == .low ? nil : .default
        content.threadIdentifier = alert.channel
        var info: [String: Any] = ["channel": alert.channel]
        if let k = alert.convKey { info["convKey"] = k }
        if let v = alert.view { info["view"] = v }
        if let n = alert.notificationId { info["notificationId"] = n }
        content.userInfo = info
        if #available(iOS 15.0, *) { content.interruptionLevel = alert.priority == .high ? .timeSensitive : (alert.priority == .low ? .passive : .active) }
        lock.lock(); shownIds.insert(alert.id); lock.unlock()
        center.add(UNNotificationRequest(identifier: String(alert.id), content: content, trigger: nil)) { _ in }
    }

    func cancel(_ id: Int) {
        lock.lock(); shownIds.remove(id); lock.unlock()
        center.removeDeliveredNotifications(withIdentifiers: [String(id)])
        center.removePendingNotificationRequests(withIdentifiers: [String(id)])
    }

    func active() -> Set<Int>? { lock.lock(); defer { lock.unlock() }; return shownIds }

    func summary(count: Int, lines: [String]) {
        let content = UNMutableNotificationContent()
        content.title = "\(count) Neema alerts"
        content.body = lines.prefix(3).joined(separator: "\n")
        content.threadIdentifier = Notifier.CH_ALERTS
        center.add(UNNotificationRequest(identifier: String(Notifier.SUMMARY_ID), content: content, trigger: nil)) { _ in }
    }

    func cancelSummary() {
        center.removeDeliveredNotifications(withIdentifiers: [String(Notifier.SUMMARY_ID)])
    }
}

/// The in-app message alert: the system's notification sound and/or a buzz.
final class SystemAlertPlayer: AlertPlayer, @unchecked Sendable {
    func play(sound: Bool, vibrate: Bool) {
        if sound { AudioServicesPlaySystemSound(1007) }
        if vibrate { AudioServicesPlaySystemSound(kSystemSoundID_Vibrate) }
    }
}
