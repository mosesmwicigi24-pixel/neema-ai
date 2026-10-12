import Foundation
import SwiftUI
import NeemaCore

/// The profile screen's state as SwiftUI reads it: the model's forms and
/// flags, the signed-in agent and the team (the row with the custom role),
/// and how the device sounds.
@MainActor
final class ProfileScreenModel: ObservableObject {
    let vm: ProfileViewModel
    let prefs: AppPrefs
    @Published private(set) var ui: ProfileUi
    @Published private(set) var me: Agent?
    @Published private(set) var agents: [Agent]
    @Published private(set) var alerts: AlertSettings
    /// A form whose save landed ("edit", "password"): the screen on display folds it away.
    @Published private(set) var closed: ClosedDialog?
    private var subs: [Subscription] = []
    private var closedSeq = 0

    init(vm: ProfileViewModel, prefs: AppPrefs) {
        self.vm = vm
        self.prefs = prefs
        ui = vm.ui
        me = vm.host.me.value
        agents = vm.host.agents.value
        alerts = prefs.alerts.value
        subs.append(vm.state.observe { [weak self] v in onMainActor { self?.ui = v } })
        subs.append(vm.host.me.observe { [weak self] v in onMainActor { self?.me = v } })
        subs.append(vm.host.agents.observe { [weak self] v in onMainActor { self?.agents = v } })
        subs.append(prefs.alerts.observe { [weak self] v in onMainActor { self?.alerts = v } })
        subs.append(vm.closedForms.observe { [weak self] f in
            onMainActor {
                guard let self = self else { return }
                self.closedSeq += 1
                self.closed = ClosedDialog(name: f, seq: self.closedSeq)
            }
        })
    }

    /// A two-way binding onto one typed field of the forms.
    func bind<T>(_ kp: WritableKeyPath<ProfileForm, T>) -> Binding<T> {
        Binding(get: { self.ui.form[keyPath: kp] }, set: { v in self.vm.editForm { $0[keyPath: kp] = v } })
    }

    func close() {
        subs.forEach { $0.cancel() }
        subs = []
        vm.close()
    }
}
