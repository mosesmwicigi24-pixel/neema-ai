import Foundation

/// What the customer panel needs from the shell (Android's `DashboardViewModel`
/// as `CustomerViewModel` sees it). The app model conforms; tests use a fake.
public protocol CustomerHost: AnyObject {
    var foreground: Watched<Bool> { get }
    var socketConnected: Watched<Bool> { get }
    var socketEvents: Signal<JSONValue> { get }
    /// Every order the dashboard knows (the Orders view keeps it fresh): the panel reloads when this customer's change.
    var orders: Watched<[Order]> { get }
    var api: NeemaApi { get }
    /// Words another view wants in a thread's composer (never sent by themselves).
    var composerPrefill: Watched<ComposerPrefill?> { get }
    /// GET /admin/calls/channels as last read (nil until read): the Messenger Call button shows only while Messenger can call.
    var callChannels: Watched<CallChannels?> { get }
    /// `can(PERMS.MANAGE_SETTINGS)`: a `template_required` refusal can be fixed by this agent.
    var canManageSettings: Bool { get }
    func toast(_ message: String, _ type: ToastType)
    /// A WhatsApp voice call to `waId` (the call screen carries what happens next).
    func placeCall(waId: String, name: String?, convId: String?) async -> CallOutcome
    /// A Messenger voice call to a PSID.
    func placeMessengerCall(psid: String, name: String?, convId: String?) async -> CallOutcome
    /// POST /admin/calls/request-permission (or Messenger's): only on the agent's tap.
    func requestCallPermission(to: String, name: String?, channel: String) async throws -> PermissionRequestResponse
}

extension CustomerHost {
    /// Messenger calling is on, as the server last said.
    public var messengerCallsOn: Bool { callChannels.value?.messenger.outbound == true }
}
