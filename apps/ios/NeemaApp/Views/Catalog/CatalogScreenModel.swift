import Foundation
import SwiftUI
import NeemaCore

/// The catalog screen's state as SwiftUI reads it: the core model's watched
/// values, the host's live catalogue and the grid derived from both.
@MainActor
final class CatalogScreenModel: ObservableObject {
    let vm: CatalogViewModel
    @Published private(set) var ui: CatalogUi
    @Published private(set) var catalog: [CatalogItem]
    @Published private(set) var view: CatalogView
    private var subs: [Subscription] = []
    private var lastFilter = ""
    private var lastSearch = ""

    init(vm: CatalogViewModel) {
        self.vm = vm
        ui = vm.ui
        catalog = vm.host.catalog.value
        view = vm.view
        lastFilter = ui.filter; lastSearch = ui.search
        subs.append(vm.state.observe { [weak self] v in
            onMainActor {
                guard let self = self else { return }
                self.ui = v
                // Only a change of the filter or the search re-derives the grid (not a spinner or the audit).
                if v.filter != self.lastFilter || v.search != self.lastSearch {
                    self.lastFilter = v.filter; self.lastSearch = v.search
                    self.view = self.vm.view
                }
            }
        })
        subs.append(vm.host.catalog.observe { [weak self] v in
            onMainActor {
                guard let self = self else { return }
                self.catalog = v
                self.view = self.vm.view
            }
        })
    }

    func close() { vm.close() }
}
