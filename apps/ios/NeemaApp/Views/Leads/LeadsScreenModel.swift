import Foundation
import SwiftUI
import NeemaCore

/// The leads screen's state as SwiftUI reads it.
@MainActor
final class LeadsScreenModel: ObservableObject {
    let vm: LeadsViewModel
    @Published private(set) var ui: LeadsUi
    private var sub: Subscription?

    init(vm: LeadsViewModel) {
        self.vm = vm
        ui = vm.ui
        sub = vm.state.observe { [weak self] v in onMainActor { self?.ui = v } }
    }

    func close() { vm.close() }
}
