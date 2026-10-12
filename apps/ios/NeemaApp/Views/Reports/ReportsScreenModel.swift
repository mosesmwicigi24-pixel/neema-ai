import Foundation
import SwiftUI
import NeemaCore

/// The reports screen's state as SwiftUI reads it: the model's report and the dashboard's team (the tables' agent names).
@MainActor
final class ReportsScreenModel: ObservableObject {
    let vm: ReportsViewModel
    @Published private(set) var ui: ReportsUi
    @Published private(set) var agents: [Agent]
    private var subs: [Subscription] = []

    init(vm: ReportsViewModel) {
        self.vm = vm
        ui = vm.ui
        agents = vm.host.agents.value
        subs.append(vm.state.observe { [weak self] v in onMainActor { self?.ui = v } })
        subs.append(vm.host.agents.observe { [weak self] v in onMainActor { self?.agents = v } })
    }

    func close() {
        subs.forEach { $0.cancel() }
        subs = []
        vm.close()
    }
}
