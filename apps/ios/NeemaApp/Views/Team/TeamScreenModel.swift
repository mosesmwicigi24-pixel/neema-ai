import Foundation
import SwiftUI
import NeemaCore

/// A dialog whose save landed: the screen on display folds it away (`seq`
/// makes a repeat of the same name a new event).
struct ClosedDialog: Equatable {
    let name: String
    let seq: Int
}

/// The team screen's state as SwiftUI reads it: the model's roles, forms and
/// flags, the dashboard's team and the signed-in agent.
@MainActor
final class TeamScreenModel: ObservableObject {
    let vm: TeamViewModel
    @Published private(set) var ui: TeamUi
    @Published private(set) var agents: [Agent]
    @Published private(set) var me: Agent?
    @Published private(set) var closed: ClosedDialog?
    private var subs: [Subscription] = []
    private var closedSeq = 0

    init(vm: TeamViewModel) {
        self.vm = vm
        ui = vm.ui
        agents = vm.host.agents.value
        me = vm.host.me.value
        subs.append(vm.state.observe { [weak self] v in onMainActor { self?.ui = v } })
        subs.append(vm.host.agents.observe { [weak self] v in onMainActor { self?.agents = v } })
        subs.append(vm.host.me.observe { [weak self] v in onMainActor { self?.me = v } })
        subs.append(vm.closedDialogs.observe { [weak self] d in
            onMainActor {
                guard let self = self else { return }
                self.closedSeq += 1
                self.closed = ClosedDialog(name: d, seq: self.closedSeq)
            }
        })
    }

    /// A two-way binding onto one typed field of the dialogs' forms.
    func bind<T>(_ kp: WritableKeyPath<TeamForms, T>) -> Binding<T> {
        Binding(get: { self.ui.forms[keyPath: kp] }, set: { v in self.vm.editForms { $0[keyPath: kp] = v } })
    }

    func close() {
        subs.forEach { $0.cancel() }
        subs = []
        vm.close()
    }
}
