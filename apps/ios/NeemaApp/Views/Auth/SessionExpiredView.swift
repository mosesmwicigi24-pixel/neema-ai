import SwiftUI
import NeemaCore

/// Not dismissable: the server stopped accepting the session, so the agent
/// enters their password to continue where they left off, or signs out.
struct SessionExpiredView: View {
    @EnvironmentObject private var app: AppModel
    @State private var password = ""
    @State private var error: String?
    @State private var busy = false
    @FocusState private var focused: Bool

    var body: some View {
        GeometryReader { geo in
            ZStack {
                Color.black.opacity(0.4).ignoresSafeArea()
                card
                    .frame(maxWidth: 384)
                    .padding(.horizontal, geo.size.width < 380 ? 24 : 32)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .onAppear { focused = true }
    }

    private var card: some View {
        VStack(spacing: 0) {
            LinearGradient(colors: [Palette.green500, Palette.emerald500], startPoint: .leading, endPoint: .trailing)
                .frame(height: 4)
            VStack(spacing: 14) {
                ZStack {
                    Circle().fill(Palette.amber50).frame(width: 48, height: 48)
                    Image(systemName: "exclamationmark.triangle.fill").foregroundColor(Palette.amber500)
                }
                Text("Session expired").font(NeemaFont.manrope(18, .bold)).foregroundColor(Palette.stone900)
                Text("Please enter your password to continue where you left off.")
                    .font(NeemaFont.bodyMedium).foregroundColor(Palette.stone500).multilineTextAlignment(.center)

                VStack(alignment: .leading, spacing: 4) {
                    Text("Signed in as").font(NeemaFont.fixed(11, .semibold)).foregroundColor(Palette.stone500)
                    Text(app.session?.email ?? app.container.sessionStore.lastEmail ?? "")
                        .font(NeemaFont.bodyMedium).foregroundColor(Palette.stone900)
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(RoundedRectangle(cornerRadius: 8).fill(Palette.stone100))
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                VStack(alignment: .leading, spacing: 4) {
                    Text("Password").font(NeemaFont.fixed(11, .semibold)).foregroundColor(Palette.stone500)
                    SecureField("", text: $password)
                        .textContentType(.password)
                        .submitLabel(.done)
                        .focused($focused)
                        .onSubmit(submit)
                        .padding(10)
                        .background(RoundedRectangle(cornerRadius: 8).fill(Color.white))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Palette.stone200))
                }

                if let e = error {
                    Text(e).font(NeemaFont.bodySmall).foregroundColor(Palette.red700)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                Button(action: submit) {
                    HStack(spacing: 8) {
                        if busy { ProgressView().tint(.white) }
                        Text(busy ? "Signing in…" : "Continue").font(NeemaFont.manrope(14, .bold))
                    }
                    .frame(maxWidth: .infinity).frame(height: 44)
                    .foregroundColor(.white)
                    .background(RoundedRectangle(cornerRadius: 10).fill(Palette.stone900.opacity(password.isEmpty || busy ? 0.5 : 1)))
                }
                .disabled(password.isEmpty || busy)

                Button("Sign out") { app.logout() }
                    .font(NeemaFont.manrope(13, .semibold))
                    .foregroundColor(Palette.stone500)
            }
            .padding(24)
        }
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Color.white))
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .shadow(color: .black.opacity(0.25), radius: 24, y: 12)
    }

    private func submit() {
        guard !password.isEmpty, !busy else { return }
        busy = true
        error = nil
        Task {
            do {
                try await app.reauthenticate(password: password)
                password = ""
            } catch let e as AuthError {
                error = e.message.hasPrefix("Invalid") ? "Incorrect password. Please try again." : e.message
            } catch {
                self.error = "Something went wrong. Please try again."
            }
            busy = false
        }
    }
}
