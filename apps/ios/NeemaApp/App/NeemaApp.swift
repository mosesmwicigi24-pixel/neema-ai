import SwiftUI
import NeemaCore

@main
struct NeemaApp: App {
    // `-neema-canned` (the UI tests): the app on the recorded backend instead of the server.
    @StateObject private var app = AppModel(container: CannedBackend.container() ?? AppContainer())
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(app)
                .environment(\.neema, app.dark ? NeemaColors.dark : NeemaColors.light)
                .preferredColorScheme(app.session == nil ? .dark : (app.dark ? .dark : .light))
                .onOpenURL { url in app.open(url) }
                .onChange(of: scenePhase) { _, phase in app.setForeground(phase == .active) }
                .onAppear {
                    app.setForeground(scenePhase == .active)
                    // `-neema-open <key>` with `-neema-canned`: a deep link at launch, as a notification tap or
                    // `neema://?open=<key>` would deliver one (the UI tests cannot open a custom scheme themselves).
                    if CannedBackend.requested, let key = CannedBackend.openKey { app.applyDeepLink(DeepLink(open: key)) }
                }
        }
    }
}
