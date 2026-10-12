import Foundation
import SwiftUI
import NeemaCore

/// The deals screen's state as SwiftUI reads it.
@MainActor
final class DealsScreenModel: ObservableObject {
    let vm: DealsViewModel
    @Published private(set) var ui: DealsUi
    private var sub: Subscription?

    init(vm: DealsViewModel) {
        self.vm = vm
        ui = vm.ui
        sub = vm.state.observe { [weak self] v in onMainActor { self?.ui = v } }
    }

    func close() { vm.close() }
}
