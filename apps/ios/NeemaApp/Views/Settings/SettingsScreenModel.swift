import Foundation
import SwiftUI
import NeemaCore

/// The settings screen's state as SwiftUI reads it: the core model's cards,
/// the calling card's state and the live catalogue (for the offer's
/// category chips and product picker).
@MainActor
final class SettingsScreenModel: ObservableObject {
    let vm: SettingsViewModel
    @Published private(set) var ui: SettingsUi
    @Published private(set) var calling: CallingSettingsUi
    @Published private(set) var catalog: [CatalogItem]
    private var subs: [Subscription] = []

    init(vm: SettingsViewModel, catalog: Watched<[CatalogItem]>) {
        self.vm = vm
        ui = vm.ui
        calling = vm.calling.ui
        self.catalog = catalog.value
        subs.append(vm.state.observe { [weak self] v in onMainActor { self?.ui = v } })
        subs.append(vm.calling.state.observe { [weak self] v in onMainActor { self?.calling = v } })
        subs.append(catalog.observe { [weak self] v in onMainActor { self?.catalog = v } })
    }

    /// Two-way bindings onto the model-held forms (the typed input outlives a rotation and a reclaim).
    func draft<T>(_ kp: WritableKeyPath<Campaign, T>) -> Binding<T> {
        Binding(get: { self.ui.draft[keyPath: kp] }, set: { v in self.vm.editDraft { $0[keyPath: kp] = v } })
    }

    func biz<T>(_ kp: WritableKeyPath<BizSettings, T>) -> Binding<T> {
        Binding(get: { self.ui.biz[keyPath: kp] }, set: { v in self.vm.editBiz { $0[keyPath: kp] = v } })
    }

    func ai<T>(_ kp: WritableKeyPath<AiSettings, T>) -> Binding<T> {
        Binding(get: { self.ui.ai[keyPath: kp] }, set: { v in self.vm.editAi { $0[keyPath: kp] = v } })
    }

    var directives: Binding<String> { Binding(get: { self.ui.directives }, set: { self.vm.setDirectives($0) }) }
    var newStage: Binding<String> { Binding(get: { self.ui.newStage }, set: { self.vm.setNewStage($0) }) }

    func config(_ integ: String, _ field: String) -> Binding<String> {
        Binding(get: { self.ui.integConfig[integ]?[field] ?? "" }, set: { self.vm.setConfig(integ, field, $0) })
    }

    func close() {
        subs.forEach { $0.cancel() }
        subs = []
        vm.close()
    }
}
