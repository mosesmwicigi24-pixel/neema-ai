import Foundation
import SwiftUI
import NeemaCore

/// The analytics screen's state as SwiftUI reads it: the model's figures and
/// the dashboard's orders, team and catalogue the cards fall back on.
@MainActor
final class OverviewScreenModel: ObservableObject {
    let vm: OverviewViewModel
    @Published private(set) var ui: OverviewUi
    @Published private(set) var orders: [Order]
    @Published private(set) var agents: [Agent]
    @Published private(set) var catalog: [CatalogItem]
    private var subs: [Subscription] = []

    init(vm: OverviewViewModel) {
        self.vm = vm
        ui = vm.ui
        orders = vm.host.orders.value
        agents = vm.host.agents.value
        catalog = vm.host.catalog.value
        subs.append(vm.state.observe { [weak self] v in onMainActor { self?.ui = v } })
        subs.append(vm.host.orders.observe { [weak self] v in onMainActor { self?.orders = v } })
        subs.append(vm.host.agents.observe { [weak self] v in onMainActor { self?.agents = v } })
        subs.append(vm.host.catalog.observe { [weak self] v in onMainActor { self?.catalog = v } })
    }

    func close() {
        subs.forEach { $0.cancel() }
        subs = []
        vm.close()
    }
}
