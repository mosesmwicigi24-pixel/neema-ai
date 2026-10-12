import Foundation
import SwiftUI
import NeemaCore

/// The orders screen's state as SwiftUI reads it: the core model's watched
/// values and the host's live list, republished on the main actor.
@MainActor
final class OrdersScreenModel: ObservableObject {
    let vm: OrdersViewModel
    @Published private(set) var ui: OrdersUi
    @Published private(set) var orders: [Order]
    private var subs: [Subscription] = []

    init(vm: OrdersViewModel) {
        self.vm = vm
        ui = vm.ui
        orders = vm.host.orders.value
        subs.append(vm.state.observe { [weak self] v in onMainActor { self?.ui = v } })
        subs.append(vm.host.orders.observe { [weak self] v in onMainActor { self?.orders = v } })
    }

    /// The open order's live row (a refetch shows through the sheet), if it is still listed.
    var selected: Order? { ui.selectedId.flatMap { id in orders.first { $0.id == id } } }

    /// Read at least once: only then is an open order missing from the list really gone.
    var loaded: Bool { !orders.isEmpty || (!ui.initialLoading && ui.loadError == nil) }

    /// Never loaded: no counts — "0 total" would be a claim.
    var unknown: Bool { orders.isEmpty && (ui.initialLoading || ui.loadError != nil) }

    func close() { vm.close() }
}
