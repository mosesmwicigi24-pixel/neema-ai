import Foundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers
import NeemaCore

/// The shell as the inbox's logic sees it (Android's `DashboardViewModel`
/// for `ConversationsViewModel`): the session, the socket, the badges and
/// the cross-view requests, as watched values the app model keeps in step.
final class ShellInboxHost: InboxHost, CustomerHost, OrdersHost, CatalogHost, DealsHost, LeadsHost, OverviewHost, @unchecked Sendable {
    let session: Watched<Session?>
    let foreground: Watched<Bool>
    let sessionExpired = Watched<Bool>(false)
    let socketConnected: Watched<Bool>
    let socketEvents: Signal<JSONValue>
    let inboxRefresh = Signal<Void>(buffer: 8)
    let inboxSummary = Watched<InboxSummary?>(nil)
    let openConvKey = Watched<String?>(nil)
    let composerPrefill = Watched<ComposerPrefill?>(nil)
    let api: NeemaApi
    let snapshots: SnapshotCache
    /// The shell's toast presenter, called on the main actor.
    var onToast: (@MainActor (String, ToastType) -> Void)?
    // CustomerHost / OrdersHost: every order the dashboard knows, the calling channels and the settings permission.
    let ordersFeed: OrdersFeed
    var orders: Watched<[Order]> { ordersFeed.orders }
    let catalogFeed: CatalogFeed
    var catalog: Watched<[CatalogItem]> { catalogFeed.catalog }
    let callChannels = Watched<CallChannels?>(nil)
    var canManageSettings = false
    // OverviewHost: the team list as the app model holds it, and its refresh.
    let agents = Watched<[Agent]>([])
    var onRefreshAgents: (() async throws -> Void)?

    init(container: AppContainer, ordersFeed: OrdersFeed, catalogFeed: CatalogFeed, snapshots: SnapshotCache) {
        session = container.sessionStore.session
        foreground = container.foreground
        socketConnected = container.socket.connected
        socketEvents = container.socket.events
        api = container.api
        self.ordersFeed = ordersFeed
        self.catalogFeed = catalogFeed
        self.snapshots = snapshots
    }

    func refreshOrders() async throws { try await ordersFeed.refreshOrders() }
    func refetchOrders() { ordersFeed.refetchOrders() }
    func refreshCatalog() async throws { try await catalogFeed.refreshCatalog() }
    func refreshAgents() async throws { try await onRefreshAgents?() }

    func toast(_ message: String, _ type: ToastType) {
        guard let cb = onToast else { return }
        Task { @MainActor in cb(message, type) }
    }

    /// The softphone lands with the calls screen (cycle 5); until then the thread says so.
    func placeCall(waId: String, name: String?, convId: String?) async -> CallOutcome {
        .failed("Calling from the app arrives with the calls screen — call from WhatsApp for now.")
    }

    func placeMessengerCall(psid: String, name: String?, convId: String?) async -> CallOutcome {
        .failed("Calling from the app arrives with the calls screen — call from Messenger for now.")
    }

    /// POST /admin/calls/request-permission (or Messenger's): only on the agent's tap.
    func requestCallPermission(to: String, name: String?, channel: String) async throws -> PermissionRequestResponse {
        channel == CallWords.MESSENGER ? try await api.calls.requestMessengerPermission(psid: to) : try await api.calls.requestPermission(to: to, name: name)
    }
}

/// Files and photos through Foundation and UIKit (Android's ContentResolver + BitmapFactory).
final class AppleMediaAccess: MediaAccess, @unchecked Sendable {
    func meta(of url: URL) -> (name: String, size: Int64) {
        let values = try? url.resourceValues(forKeys: [.nameKey, .fileSizeKey])
        let name = values?.name ?? url.lastPathComponent
        return (name.isEmpty ? "file" : name, Int64(values?.fileSize ?? 0))
    }

    func mimeType(of url: URL) -> String? {
        if let t = try? url.resourceValues(forKeys: [.contentTypeKey]).contentType, let m = t.preferredMIMEType { return m }
        return UTType(filenameExtension: url.pathExtension)?.preferredMIMEType
    }

    /// Max 2048 px on the long side, JPEG, stepping the quality down until it fits the 5 MB cap.
    func compressImage(at url: URL) async -> Data? {
        guard let data = try? Data(contentsOf: url), let img = UIImage(data: data) else { return nil }
        let maxSide: CGFloat = 2048
        let longest = max(img.size.width, img.size.height)
        let scale = longest > maxSide ? maxSide / longest : 1
        let drawn: UIImage
        if scale < 1 {
            let target = CGSize(width: floor(img.size.width * scale), height: floor(img.size.height * scale))
            let format = UIGraphicsImageRendererFormat.default()
            format.scale = 1
            drawn = UIGraphicsImageRenderer(size: target, format: format).image { _ in img.draw(in: CGRect(origin: .zero, size: target)) }
        } else {
            drawn = img
        }
        var quality: CGFloat = 0.9
        while quality >= 0.3 {
            if let d = drawn.jpegData(compressionQuality: quality), Int64(d.count) <= InboxViewModel.MAX_IMAGE { return d }
            quality -= 0.15
        }
        return nil
    }

    func readable(_ url: URL) -> Bool { FileManager.default.isReadableFile(atPath: url.path) }
}

/// Runs `body` on the main actor: at once when already there, else on the next turn.
func onMainActor(_ body: @escaping @MainActor () -> Void) {
    if Thread.isMainThread { MainActor.assumeIsolated { body() } } else { Task { @MainActor in body() } }
}

/// The customer panel's state as SwiftUI reads it (Android's `collectAsState` over the view model).
@MainActor
final class CustomerPanelModel: ObservableObject {
    let vm: CustomerViewModel
    @Published private(set) var ui: CustomerUi
    private var sub: Subscription?

    init(vm: CustomerViewModel) {
        self.vm = vm
        ui = vm.ui
        sub = vm.state.observe { [weak self] s in onMainActor { self?.ui = s } }
    }
}

/// The inbox's state as SwiftUI reads it: the core's watched values republished.
@MainActor
final class InboxScreenModel: ObservableObject {
    /// Customer panels keep their typed drafts while another thread is open: one per conversation, the eight most recent.
    static let MAX_CUSTOMER_PANELS = 8

    let vm: InboxViewModel
    let customerHost: CustomerHost
    @Published private(set) var inbox: InboxUi
    @Published private(set) var list: ListUi
    @Published private(set) var thread: ThreadUi
    @Published private(set) var composer: ComposerUi
    @Published private(set) var dialogs: DialogUi
    @Published private(set) var rows: [RowGroup]
    private var subs: [Subscription] = []
    private var customers: [String: CustomerPanelModel] = [:]
    private var customerOrder: [String] = []

    /// The panel model for a conversation (Android's `viewModel(key = "customer:${id}")`).
    func customer(for conversation: Conversation) -> CustomerPanelModel {
        if let m = customers[conversation.id] {
            customerOrder.removeAll { $0 == conversation.id }
            customerOrder.append(conversation.id)
            return m
        }
        let m = CustomerPanelModel(vm: CustomerViewModel(host: customerHost, conversation: conversation))
        customers[conversation.id] = m
        customerOrder.append(conversation.id)
        while customerOrder.count > Self.MAX_CUSTOMER_PANELS, let old = customerOrder.first {
            customerOrder.removeFirst()
            customers[old]?.vm.close()
            customers[old] = nil
        }
        return m
    }

    func close() {
        vm.close()
        for m in customers.values { m.vm.close() }
        customers = [:]
        customerOrder = []
    }

    init(vm: InboxViewModel, customerHost: CustomerHost) {
        self.vm = vm
        self.customerHost = customerHost
        inbox = vm.inbox.value
        list = vm.list.value
        thread = vm.thread.value
        composer = vm.composer.value
        dialogs = vm.dialogs.value
        rows = vm.rows
        subs.append(vm.inbox.observe { [weak self] v in onMainActor { self?.inbox = v } })
        subs.append(vm.list.observe { [weak self] v in onMainActor { self?.list = v } })
        subs.append(vm.thread.observe { [weak self] v in onMainActor { self?.thread = v } })
        subs.append(vm.composer.observe { [weak self] v in onMainActor { self?.composer = v } })
        subs.append(vm.dialogs.observe { [weak self] v in onMainActor { self?.dialogs = v } })
        subs.append(vm.rowsChanged.observe { [weak self] _ in
            onMainActor {
                guard let self = self else { return }
                self.rows = self.vm.rows
            }
        })
    }
}
