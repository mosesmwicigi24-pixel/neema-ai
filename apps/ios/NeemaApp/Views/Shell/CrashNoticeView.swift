import SwiftUI
import NeemaCore

/// After the app closed on someone (Android `CrashNotice`): what happened,
/// with Share (WhatsApp, Mail, anything) and Copy — the exact trace reaches
/// the people who fix it, whoever was using the app, admin or not, online
/// or not. Shown once per crash.
struct CrashNoticeView: View {
    let vault: CrashVault
    @State private var report: CrashReport?
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c

    var body: some View {
        Color.clear.frame(width: 0, height: 0)
            .onAppear { report = vault.unseenFatal() }
            .sheet(item: Binding(get: { report.map { Shown(report: $0) } }, set: { if $0 == nil { done() } })) { shown in
                let r = shown.report
                let text = CrashVault.asText(r)
                VStack(alignment: .leading, spacing: 12) {
                    Text("Neema closed unexpectedly").font(NeemaFont.manrope(18, .bold)).foregroundColor(c.text)
                    Text("Last time, the app closed because of a problem. Share this report so it can be fixed — it says exactly what went wrong.")
                        .font(NeemaFont.manrope(14)).foregroundColor(c.textMid)
                    ScrollView {
                        Text(r.summary.trimmingCharacters(in: .whitespaces).isEmpty ? r.kind : r.summary)
                            .font(NeemaFont.mono(12)).foregroundColor(c.textDim).textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 200)
                    HStack(spacing: 8) {
                        ShareLink(item: text, subject: Text("Neema crash report")) {
                            Text("Share report").font(NeemaFont.manrope(14, .semibold)).foregroundColor(.white)
                                .padding(.horizontal, 16).frame(minHeight: 44).background(Capsule().fill(c.gold))
                        }
                        .simultaneousGesture(TapGesture().onEnded { _ in Task { @MainActor in try? await Task.sleep(nanoseconds: 500_000_000); done() } })
                        Button("Copy") { UIPasteboard.general.string = text; app.toast("Crash report copied"); done() }
                            .font(NeemaFont.manrope(14, .medium)).foregroundColor(c.text).padding(.horizontal, 12).frame(minHeight: 44)
                        Spacer()
                        Button("Close") { done() }.font(NeemaFont.manrope(14, .medium)).foregroundColor(c.textMid).frame(minHeight: 44)
                    }
                }
                .padding(20)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .background(c.bg2)
                .environment(\.neema, c)
                .presentationDetents([.medium])
            }
    }

    private func done() { vault.seen(); report = nil }

    private struct Shown: Identifiable, Equatable { let report: CrashReport; var id: String { report.id } }
}
