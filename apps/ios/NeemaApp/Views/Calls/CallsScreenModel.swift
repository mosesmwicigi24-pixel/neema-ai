import Foundation
import SwiftUI
import NeemaCore

/// The calls screen's state as SwiftUI reads it: the console model's watched
/// values and the softphone's restriction banner, republished on the main actor.
@MainActor
final class CallsScreenModel: ObservableObject {
    let vm: CallsViewModel
    let calls: CallManager
    @Published private(set) var list: [Call]?
    @Published private(set) var refreshing = false
    @Published private(set) var loadError: String?
    @Published private(set) var followUpsOnly = false
    @Published private(set) var channelFilter = "all"
    @Published private(set) var channels: CallChannels?
    @Published private(set) var doneBusy: Set<String> = []
    @Published private(set) var selected: Call?
    @Published private(set) var transcript: TranscriptUi?
    @Published private(set) var restriction: CallingRestriction?
    private var subs: [Subscription] = []

    init(vm: CallsViewModel, calls: CallManager) {
        self.vm = vm
        self.calls = calls
        list = vm.calls.value
        refreshing = vm.refreshing.value
        loadError = vm.loadError.value
        followUpsOnly = vm.followUpsOnly.value
        channelFilter = vm.channelFilter.value
        channels = calls.channels.value
        doneBusy = vm.doneBusy.value
        selected = vm.selected.value
        transcript = vm.transcript.value
        restriction = calls.restriction.value
        subs.append(vm.calls.observe { [weak self] v in onMainActor { self?.list = v } })
        subs.append(vm.refreshing.observe { [weak self] v in onMainActor { self?.refreshing = v } })
        subs.append(vm.loadError.observe { [weak self] v in onMainActor { self?.loadError = v } })
        subs.append(vm.followUpsOnly.observe { [weak self] v in onMainActor { self?.followUpsOnly = v } })
        subs.append(vm.channelFilter.observe { [weak self] v in onMainActor { self?.channelFilter = v } })
        subs.append(calls.channels.observe { [weak self] v in onMainActor { self?.channels = v } })
        subs.append(vm.doneBusy.observe { [weak self] v in onMainActor { self?.doneBusy = v } })
        subs.append(vm.selected.observe { [weak self] v in onMainActor { self?.selected = v } })
        subs.append(vm.transcript.observe { [weak self] v in onMainActor { self?.transcript = v } })
        subs.append(calls.restriction.observe { [weak self] v in onMainActor { self?.restriction = v } })
    }

    func setFollowUpsOnly(_ v: Bool) { vm.followUpsOnly.value = v }
    func setChannelFilter(_ v: String) { vm.channelFilter.value = v }

    func close() {
        subs.forEach { $0.cancel() }
        subs = []
        vm.close()
    }
}

/// A day header, then its rows (the log is newest first, so days come in order).
enum LogItem: Identifiable {
    case day(label: String, key: String)
    case row(call: Call, key: String)
    var id: String {
        switch self {
        case .day(_, let k): return k
        case .row(_, let k): return k
        }
    }
}

/// `key` is unique even if a day shows twice (rows out of order): a repeated list key breaks the list.
func logItems(_ rows: [Call]) -> [LogItem] {
    let keys = rowKeys(rows)
    var out: [LogItem] = []
    out.reserveCapacity(rows.count + 8)
    var day: String?
    var seen: [String: Int] = [:]
    for (i, c) in rows.enumerated() {
        var d = Fmt.dayLabel(c.startedAt)
        if d.isEmpty { d = "Earlier" }
        if d != day {
            let n = (seen[d] ?? 0) + 1
            seen[d] = n
            out.append(.day(label: d, key: n == 1 ? "day:\(d)" : "day:\(d)#\(n)"))
            day = d
        }
        out.append(.row(call: c, key: keys[i]))
    }
    return out
}
