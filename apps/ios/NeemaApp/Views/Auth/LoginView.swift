import SwiftUI
import NeemaCore

/// The sign-in screen: always the night palette, Android's copy word for word.
struct LoginView: View {
    @EnvironmentObject private var app: AppModel
    @State private var email = ""
    @State private var password = ""
    @State private var showPassword = false
    @State private var error: String?
    @State private var busy = false
    @FocusState private var focus: Field?

    private enum Field { case email, password }

    static let night = Color(hex: 0x070D1C)
    static let panel = Color(hex: 0x0A1229)
    static let lines = Color(hex: 0x152451)
    static let moss = Color(hex: 0x589B31)
    static let willow = Color(hex: 0x699A32)
    static let parchment = Color(hex: 0xF3F9EC)

    var body: some View {
        GeometryReader { geo in
            let wide = geo.size.width >= 1024
            HStack(spacing: 0) {
                if wide {
                    brandPanel
                        .frame(width: geo.size.width >= 1280 ? 480 : 420)
                        .frame(maxHeight: .infinity)
                        .background(Self.panel)
                }
                ScrollView {
                    VStack(spacing: 0) {
                        if !wide { phoneHeader.frame(maxWidth: 384, alignment: .leading).padding(.horizontal, 24).padding(.bottom, 32) }
                        form
                            .frame(maxWidth: 384)
                            .padding(.horizontal, 24)
                    }
                    .padding(.vertical, 24)
                    // The form sits in the middle of the window, as LoginScreen.kt centres it.
                    .frame(maxWidth: .infinity, minHeight: geo.size.height)
                }
                .scrollDismissesKeyboard(.interactively)
            }
        }
        .background(Self.night.ignoresSafeArea())
        .onAppear {
            if email.isEmpty, let last = app.container.sessionStore.lastEmail { email = last }
        }
    }

    private var logo: some View {
        RoundedRectangle(cornerRadius: 10, style: .continuous)
            .fill(Self.moss)
            .overlay(WebIcon(glyph: WebIcons.logo, size: 18).foregroundColor(.white))
    }

    private var phoneHeader: some View {
        HStack(spacing: 10) {
            logo.frame(width: 36, height: 36)
            VStack(alignment: .leading, spacing: 2) {
                Text("Neema").font(NeemaFont.manrope(16, .bold)).foregroundColor(.white)
                Text("ADMIN").font(NeemaFont.fixed(10)).tracking(1).foregroundColor(Self.willow)
            }
        }
    }

    private var brandPanel: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 12) {
                logo.frame(width: 40, height: 40)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Neema").font(NeemaFont.manrope(18, .extrabold)).foregroundColor(Self.parchment)
                    Text("BETHANY HOUSE · ADMIN").font(NeemaFont.fixed(10, .semibold)).tracking(1.2).foregroundColor(Self.willow)
                }
            }
            Spacer()
            Text("Manage conversations,").font(NeemaFont.manrope(30, .extrabold)).foregroundColor(Self.parchment)
            Text("grow your business.").font(NeemaFont.manrope(30, .extrabold)).foregroundColor(Color(hex: 0x9CCD65))
            Text("AI-powered WhatsApp assistant for Bethany House — handling orders, queries, and sales around the clock.")
                .font(NeemaFont.bodyMedium).foregroundColor(Brand.textMuted).padding(.top, 16)
            Spacer()
            Text("© \(Calendar.current.component(.year, from: Date())) Bethany House · Nairobi, Kenya")
                .font(NeemaFont.bodySmall).foregroundColor(Brand.textMuted)
        }
        .padding(40)
        .background(
            RadialGradient(colors: [Self.moss.opacity(0.25), .clear], center: .topLeading, startRadius: 0, endRadius: 520)
        )
    }

    private var form: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Sign in").font(NeemaFont.manrope(24, .bold)).foregroundColor(Self.parchment)
            Text("Enter your credentials to access the dashboard")
                .font(NeemaFont.bodyMedium).foregroundColor(Self.willow).padding(.top, 4)

            label("EMAIL ADDRESS").padding(.top, 28)
            field {
                TextField("", text: $email, prompt: Text("admin@bethanyhouse.com").foregroundColor(Self.willow))
                    .accessibilityIdentifier("login.email")
                    .textContentType(.username)
                    .keyboardType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.next)
                    .focused($focus, equals: .email)
                    .onSubmit { focus = .password }
            }

            label("PASSWORD").padding(.top, 16)
            field {
                HStack {
                    Group {
                        if showPassword {
                            TextField("", text: $password, prompt: Text("••••••••").foregroundColor(Self.parchment.opacity(0.5)))
                        } else {
                            SecureField("", text: $password, prompt: Text("••••••••").foregroundColor(Self.parchment.opacity(0.5)))
                        }
                    }
                    .accessibilityIdentifier("login.password")
                    .textContentType(.password)
                    .submitLabel(.go)
                    .focused($focus, equals: .password)
                    .onSubmit { submit() }
                    Button {
                        showPassword.toggle()
                    } label: {
                        WebIcon(glyph: showPassword ? WebIcons.eyeOff : WebIcons.eye, size: 18).foregroundColor(Brand.textMuted)
                    }
                    .accessibilityLabel(showPassword ? "Hide password" : "Show password")
                }
            }

            if let e = error {
                HStack(alignment: .top, spacing: 8) {
                    WebIcon(glyph: WebIcons.alertCircle, size: 16).foregroundColor(Palette.red500)
                    Text(e).font(NeemaFont.bodySmall).foregroundColor(Color(hex: 0xFCA5A5))
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(hex: 0x450A0A, alpha: 0.6)))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(hex: 0x991B1B)))
                .padding(.top, 14)
                .accessibilityAddTraits(.updatesFrequently)
            }

            Button(action: submit) {
                HStack(spacing: 10) {
                    if busy { ProgressView().tint(.white) }
                    Text(busy ? "Signing in…" : "Sign in").font(NeemaFont.manrope(15, .bold))
                }
                .frame(maxWidth: .infinity)
                .frame(height: 48)
                .foregroundColor(.white)
                .background(RoundedRectangle(cornerRadius: 12).fill(Self.moss))
                .shadow(color: Self.moss.opacity(0.45), radius: 14, y: 6)
            }
            .disabled(busy)
            .accessibilityIdentifier("login.submit")
            .padding(.top, 22)

            Rectangle().fill(Self.lines).frame(height: 1).padding(.top, 28)
            Text("Access restricted to Bethany House staff.\nContact your administrator if you need access.")
                .font(NeemaFont.bodySmall).foregroundColor(Self.willow)
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity)
                .padding(.top, 18)
        }
    }

    private func label(_ t: String) -> some View {
        Text(t).font(NeemaFont.fixed(12, .semibold)).tracking(0.6).foregroundColor(Self.willow).padding(.bottom, 6)
    }

    private func field<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        content()
            .font(NeemaFont.bodyLarge)
            .foregroundColor(Self.parchment)
            .padding(.horizontal, 14)
            .frame(height: 48)
            .background(RoundedRectangle(cornerRadius: 12).fill(Self.panel))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Self.lines))
    }

    private func submit() {
        let e = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !e.isEmpty, !password.isEmpty else {
            error = "Please enter your email and password."
            return
        }
        guard !busy else { return }
        busy = true
        error = nil
        Task {
            do {
                try await app.login(email: e, password: password)
                password = ""
            } catch let err as AuthError {
                error = err.message
            } catch {
                self.error = "Something went wrong. Please try again."
            }
            busy = false
        }
    }
}
