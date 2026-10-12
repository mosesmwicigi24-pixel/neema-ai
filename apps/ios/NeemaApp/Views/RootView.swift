import SwiftUI
import NeemaCore

/// Signed out: the login screen. Signed in: the shell, with the
/// session-expired card over it when the server stopped accepting us.
struct RootView: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        ZStack {
            if app.session == nil {
                LoginView()
                    .transition(.opacity)
            } else {
                DashboardShell()
                    .id(app.session?.agentId ?? "")
                if app.sessionExpired {
                    SessionExpiredView()
                        .transition(.opacity)
                        .zIndex(2)
                }
            }
        }
        .animation(.easeInOut(duration: 0.2), value: app.session == nil)
    }
}
