import SwiftUI
import NeemaCore

@main
struct NeemaApp: App {
    @StateObject private var app = AppModel(container: AppContainer())
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(app)
                .environment(\.neema, app.dark ? NeemaColors.dark : NeemaColors.light)
                .preferredColorScheme(app.session == nil ? .dark : (app.dark ? .dark : .light))
                .onOpenURL { url in app.open(url) }
                .onChange(of: scenePhase) { phase in app.setForeground(phase == .active) }
                .onAppear { app.setForeground(scenePhase == .active) }
        }
    }
}
