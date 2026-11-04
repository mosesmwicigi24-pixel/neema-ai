import SwiftUI
import PhotosUI
import GameController
import UniformTypeIdentifiers
import NeemaCore

private let Blue50 = Palette.blue50
private let Blue200 = Palette.blue200
private let Blue700 = Palette.blue700
private let Amber = Palette.amber500

/// The web's ACCEPT_TYPES: what upload-media takes.
let ACCEPT_TYPES: [UTType] = [
    .jpeg, .png, .webP, .gif, .image, .pdf,
    UTType("com.microsoft.word.doc") ?? .data, UTType("org.openxmlformats.wordprocessingml.document") ?? .data,
    UTType("com.microsoft.excel.xls") ?? .data, UTType("org.openxmlformats.spreadsheetml.sheet") ?? .data,
    .mpeg4Movie, UTType("public.3gpp") ?? .movie, .quickTimeMovie, UTType("public.hevc") ?? .movie, UTType("com.apple.m4v-video") ?? .movie,
    UTType("org.xiph.ogg-audio") ?? .audio, UTType("public.aac-audio") ?? .audio, .mp3,
]

/// Picked files are copied into the app's own folder right away: a picker's
/// grant lapses with the process, and the tray may send much later.
enum PickedFiles {
    static var dir: URL {
        let d = FileManager.default.temporaryDirectory.appendingPathComponent("picked", isDirectory: true)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }

    static func copy(_ url: URL) -> URL? {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        let name = url.lastPathComponent.isEmpty ? "file" : url.lastPathComponent
        let dest = dir.appendingPathComponent("\(UUID().uuidString)-\(name)")
        do {
            try FileManager.default.copyItem(at: url, to: dest)
            return dest
        } catch {
            return nil
        }
    }

    static func write(_ data: Data, name: String) -> URL? {
        let dest = dir.appendingPathComponent("\(UUID().uuidString)-\(name)")
        return (try? data.write(to: dest)) == nil ? nil : dest
    }
}

/// The reply box — shown when the agent owns the thread, or is admin: AI
/// drafts, the quoted message, the 24h window, the translate toggle, the
/// text box, and attachments with per-file captions.
struct ComposerView: View {
    @ObservedObject var model: InboxScreenModel
    let window: ConversationWindow?
    let humanMode: Bool
    let threadLang: String?
    let txOn: Bool
    @Environment(\.neema) private var c
    @FocusState private var focused: Bool
    @State private var dropHover = false

    private var vm: InboxViewModel { model.vm }

    var body: some View {
        let state = model.composer
        let blue = tintOf(Blue50, Blue700, Blue200, dark: c.isDark)
        let closed = window?.mode == "closed"
        let canSend = !state.replyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !closed
        VStack(spacing: 0) {
            // Everything above the text box scrolls within whatever height the thread
            // pane leaves the composer (keyboard up, large text): the box never leaves.
            ScrollView {
                VStack(spacing: 0) {
                    // ── AI draft: a pill when collapsed, the panel when expanded ──
                    if state.draftVisible && !state.draftExpanded {
                        Button { vm.expandDraft(true) } label: {
                            HStack(spacing: 8) {
                                Text("🤖").font(.system(size: 14))
                                Text("Neema has a draft ready").font(NeemaFont.manrope(12, .semibold)).foregroundColor(blue.fg)
                                Spacer()
                                Text("Tap to review ↑").font(NeemaFont.manrope(10)).foregroundColor(ink(Palette.blue500, dark: c.isDark))
                            }
                            .padding(.horizontal, 12).padding(.vertical, 8)
                            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(blue.bg))
                            .roundedBorder(blue.border, radius: 12)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Review Neema's draft")
                        .padding(.bottom, 8)
                    }
                    if state.draftVisible && state.draftExpanded { DraftPanel(model: model) }
                    // ── Generate draft — when no draft exists ──
                    if !state.draftVisible && humanMode {
                        HStack {
                            Spacer()
                            Button { vm.generateDraft() } label: {
                                HStack(spacing: 6) {
                                    if state.generatingDraft {
                                        ProgressView().tint(Palette.blue400).scaleEffect(0.6).frame(width: 12, height: 12)
                                        Text("Generating…").font(NeemaFont.manrope(12))
                                    } else {
                                        Text("🤖 Ask Neema for a draft").font(NeemaFont.manrope(12))
                                    }
                                }
                                .foregroundColor(ink(Palette.blue600, dark: c.isDark).opacity(state.generatingDraft ? 0.5 : 1))
                                .padding(.horizontal, 12).padding(.vertical, 4).frame(minHeight: 28)
                                .roundedBorder(state.generatingDraft ? blue.border.opacity(0.5) : blue.border, radius: 8)
                            }
                            .buttonStyle(.plain)
                            .disabled(state.generatingDraft)
                        }
                        .padding(.bottom, 8)
                    }
                    // ── The message being answered ──
                    if let q = state.quoted {
                        HStack(spacing: 0) {
                            Rectangle().fill(Amber).frame(width: 2)
                            VStack(alignment: .leading, spacing: 2) {
                                Text((q.msgId != nil ? "Replying to \(q.sender == "user" ? "Customer" : q.sender == "ai" ? "Neema" : "you")" : "Replying to \(Inbox.channelLabel(q.channel))").uppercased())
                                    .font(NeemaFont.manrope(10, .semibold)).tracking(0.5).foregroundColor(Amber)
                                Text(!q.text.trimmingCharacters(in: .whitespaces).isEmpty && q.text.trimmingCharacters(in: .whitespaces) != "[image]" ? q.text : q.mediaUrl != nil ? "📷 Photo" : q.mediaType.map { "[\($0)]" } ?? q.text)
                                    .font(NeemaFont.manrope(12)).foregroundColor(c.isDark ? c.textMid : Palette.slate600).lineLimit(1)
                            }
                            .padding(.horizontal, 10).padding(.vertical, 6)
                            Spacer(minLength: 0)
                            if let m = q.mediaUrl, let u = URL(string: m) {
                                AsyncImage(url: u) { im in im.resizable().scaledToFill() } placeholder: { Color.clear }
                                    .frame(width: 36, height: 36).clipShape(RoundedRectangle(cornerRadius: 4))
                            }
                            Button { vm.clearQuote() } label: { Image(systemName: "xmark").font(.system(size: 13)).foregroundColor(Palette.slate400).frame(width: 32, height: 32) }
                                .accessibilityLabel("Remove quote")
                        }
                        .frame(minHeight: 44)
                        .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.isDark ? c.bg3 : Palette.slate100))
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                        .padding(.bottom, 8)
                    }
                    // ── Messaging window — said BEFORE a reply is typed that Meta would refuse ──
                    if let w = window, w.mode != "n/a" { WindowStrip(win: w) }
                    // ── Translate-to-their-language toggle ──
                    if threadLang != nil || txOn {
                        HStack(spacing: 8) {
                            let tx = txOn ? tintOf(Palette.willow100, Palette.moss700, Palette.moss700.opacity(0.3), dark: c.isDark) : tintOf(Palette.stone100, Palette.stone500, Palette.stone200, dark: c.isDark)
                            Button { vm.toggleTx() } label: {
                                Text("🌐 " + (txOn ? "Sending in \(state.txPreview?.lang ?? threadLang ?? "their language")" : "Translate: off"))
                                    .font(NeemaFont.manrope(11, .semibold)).foregroundColor(tx.fg)
                                    .padding(.horizontal, 10).padding(.vertical, 4)
                                    .background(Capsule().fill(tx.bg)).overlay(Capsule().stroke(tx.border))
                            }
                            .buttonStyle(.plain)
                            if txOn && state.txBusy { Text("translating…").font(NeemaFont.manrope(10)).foregroundColor(Palette.stone400) }
                            Spacer()
                        }
                        .padding(.bottom, 8)
                    }
                    if txOn, let p = state.txPreview, state.replyText.trimmingCharacters(in: .whitespaces).count > 1 {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(("They will receive" + (p.lang.map { " — \($0)" } ?? "")).uppercased()).font(NeemaFont.manrope(9, .semibold)).tracking(0.5).foregroundColor(Palette.stone400)
                            Text(p.text).font(NeemaFont.manrope(12)).italic().foregroundColor(c.isDark ? c.textMid : Palette.stone600)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 12).padding(.vertical, 8)
                        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.isDark ? c.bg3 : Palette.stone50))
                        .roundedBorder(c.isDark ? c.border : Palette.stone200, radius: 12)
                        .padding(.bottom, 8)
                    }
                    if !state.lostMedia.isEmpty { LostMediaNote(names: state.lostMedia) { vm.dismissLostMedia() } }
                }
            }
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxHeight: .infinity)
            // ── Text box + attach + send ──
            HStack(alignment: .bottom, spacing: 8) {
                AttachButton(model: model)
                // The web's box: 44 tall, rounded-2xl, #f6f7f5 on a #e5e8e2 hairline, an
                // amber ring on focus, stone-400 placeholder; grows to ~6 lines, then scrolls.
                ZStack(alignment: .topLeading) {
                    if state.replyText.isEmpty {
                        Text(window?.mode == "human_agent" ? "Type a reply — goes out under your name (human agent)…" : "Type a reply…")
                            .font(NeemaFont.manrope(14)).foregroundColor(c.isDark ? c.muted : Palette.stone400).lineLimit(1)
                            .padding(.horizontal, 16).padding(.vertical, 12)
                    }
                    TextField("", text: Binding(get: { state.replyText }, set: { vm.setReplyText($0) }), axis: .vertical)
                        .lineLimit(1...6)
                        .font(NeemaFont.manrope(14)).foregroundColor(c.text).tint(Amber)
                        .focused($focused)
                        // A hardware keyboard: Return sends, Shift+Return is a new line (Shortcuts.swift `composerShortcut`).
                        .modifier(HardwareReturnSends(enabled: canSend) { vm.sendReply() })
                        .padding(.horizontal, 16).padding(.vertical, 12)
                        .accessibilityLabel("Reply")
                }
                .frame(minHeight: 44)
                .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(c.isDark ? c.bg3 : Palette.sageFieldBg))
                .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(focused ? Amber.opacity(0.7) : (c.isDark ? c.border : Palette.sageField), lineWidth: focused ? 2 : 1))
                // The box clears the moment a reply is sent, so an empty box is the
                // double-tap guard; the reply's own bubble shows it on its way.
                Button { if canSend { vm.sendReply() } } label: {
                    Image(systemName: "paperplane.fill").font(.system(size: 17)).foregroundColor(.white)
                        .frame(width: 44, height: 44)
                        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(canSend ? Amber : Amber.opacity(0.5)))
                }
                .disabled(!canSend)
                .accessibilityLabel(closed ? (window?.reason ?? "Outside the messaging window") : "Send")
                // A hardware keyboard: ⌘↩ sends.
                .keyboardShortcut(.return, modifiers: .command)
            }
            if !state.media.isEmpty { MediaTray(model: model) }
        }
        .padding(.horizontal, 12).padding(.vertical, 10)
        .background(c.bg2)
        // A drag from another app (Split View, Stage Manager): what Neema can attach lands in the tray
        // (Shortcuts.swift `acceptsDrop`); text and links are left to the field.
        .onDrop(of: [UTType.item], isTargeted: $dropHover) { providers in DroppedFiles.take(providers) { vm.addMedia($0) } }
        .overlay {
            if dropHover {
                ZStack {
                    RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Amber.opacity(0.08))
                    RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(Amber, lineWidth: 2)
                    Text("Drop to attach to your reply").font(NeemaFont.manrope(13, .semibold)).foregroundColor(Palette.amber800)
                }
                .padding(4)
                .allowsHitTesting(false)
            }
        }
    }
}

/// Return on a hardware keyboard sends; Shift+Return stays a new line; the on-screen keyboard's
/// Return is always a new line (iOS 17's key presses; earlier systems keep Cmd+Return only).
private struct HardwareReturnSends: ViewModifier {
    let enabled: Bool
    let send: () -> Void

    func body(content: Content) -> some View {
        if #available(iOS 17.0, *) {
            content.onKeyPress(.return, phases: .down) { press in
                let hardware = GCKeyboard.coalesced != nil
                let shortcut = composerShortcut(key: .enter, down: true, shift: press.modifiers.contains(.shift),
                                                ctrl: press.modifiers.contains(.command) || press.modifiers.contains(.control), hardwareKeyboard: hardware)
                guard shortcut == .send, enabled else { return .ignored }
                send()
                return .handled
            }
        } else {
            content
        }
    }
}

/// Files dropped onto the composer, copied into the picked folder before the system reclaims them.
enum DroppedFiles {
    /// True when something Neema can attach was dropped (the drop is taken); the files land through `attach`.
    static func take(_ providers: [NSItemProvider], attach: @escaping ([URL]) -> Void) -> Bool {
        let wanted = providers.filter { p in
            acceptsDrop(p.registeredTypeIdentifiers.compactMap { UTType($0)?.preferredMIMEType })
        }
        if wanted.isEmpty { return false }
        let group = DispatchGroup()
        let lock = NSLock()
        var urls: [URL] = []
        for p in wanted {
            guard let id = p.registeredTypeIdentifiers.first(where: { UTType($0)?.preferredMIMEType.map { acceptsDrop([$0]) } == true }) else { continue }
            group.enter()
            p.loadFileRepresentation(forTypeIdentifier: id) { url, _ in
                defer { group.leave() }
                guard let url = url, let copy = PickedFiles.copy(url) else { return }
                lock.lock(); urls.append(copy); lock.unlock()
            }
        }
        group.notify(queue: .main) { if !urls.isEmpty { attach(urls) } }
        return true
    }
}

private struct DraftPanel: View {
    @ObservedObject var model: InboxScreenModel
    @Environment(\.neema) private var c

    var body: some View {
        let state = model.composer
        let vm = model.vm
        let blue = tintOf(Blue50, Blue700, Blue200, dark: c.isDark)
        let soft = ink(Palette.blue500, dark: c.isDark)
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 6) {
                Text("🤖").font(.system(size: 14))
                Text("Neema's draft").font(NeemaFont.manrope(12, .semibold)).foregroundColor(blue.fg).lineLimit(1)
                Spacer()
                Button { vm.toggleDraftEditing() } label: {
                    Text(state.draftEditing ? "Preview" : "Edit").font(NeemaFont.manrope(10)).foregroundColor(soft).lineLimit(1)
                        .padding(.horizontal, 8).padding(.vertical, 2).roundedBorder(blue.border, radius: 4)
                }
                .buttonStyle(.plain)
                Button { vm.expandDraft(false) } label: { Image(systemName: "chevron.down").font(.system(size: 13)).foregroundColor(soft).frame(width: 28, height: 28) }
                    .accessibilityLabel("Collapse Neema's draft")
                Button { vm.dismissDraft() } label: { Image(systemName: "xmark").font(.system(size: 12)).foregroundColor(soft).frame(width: 28, height: 28) }
                    .accessibilityLabel("Dismiss Neema's draft")
            }
            .padding(.horizontal, 12).padding(.vertical, 6)
            Hairline(color: c.isDark ? blue.border : Palette.blue100)
            Group {
                if state.draftEditing {
                    TextField("Edit the draft…", text: Binding(get: { state.draftText }, set: { vm.setDraftText($0) }), axis: .vertical)
                        .lineLimit(4...8).font(NeemaFont.manrope(12)).foregroundColor(ink(Palette.blue800, dark: c.isDark))
                        .padding(8)
                        .background(RoundedRectangle(cornerRadius: 8).fill(c.isDark ? c.bg3 : .white))
                        .roundedBorder(blue.border, radius: 8)
                } else {
                    Text(state.draftText.isEmpty ? "Neema has a reply ready." : state.draftText).font(NeemaFont.manrope(12)).lineSpacing(3).foregroundColor(blue.fg)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    // <Btn small> primary (amber) / secondary / ghost, as on the web.
                    WebBtn(label: "✓ Send", variant: .primary) { vm.approveDraft() }
                    WebBtn(label: "Edit & send manually", variant: .secondary) { vm.draftToComposer() }
                    WebBtn(label: "Dismiss", variant: .ghost) { vm.dismissDraft() }
                }
                .padding(.horizontal, 12).padding(.bottom, 10)
            }
        }
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(blue.bg))
        .roundedBorder(blue.border, radius: 12)
        .padding(.bottom, 8)
    }
}

/// Meta and WhatsApp shut free-form replies 24h after the customer's last
/// message. Say so up front — and, on a Meta DM, that a human still has seven
/// days. The countdown ticks each minute.
struct WindowStrip: View {
    let win: ConversationWindow
    @Environment(\.neema) private var c

    private func left(_ iso: String?, now: Int64) -> String {
        guard let t = Fmt.millis(iso) else { return "" }
        let ms = t - now
        if ms <= 0 { return "" }
        let h = ms / 3_600_000
        let m = (ms % 3_600_000) / 60_000
        return h >= 24 ? "\(h / 24)d \(h % 24)h" : h > 0 ? "\(h)h \(m)m" : "\(m)m"
    }

    var body: some View {
        TimelineView(.periodic(from: .now, by: 60)) { context in
            let now = Int64(context.date.timeIntervalSince1970 * 1000)
            let (bg0, bd0, fg0, icon): (Color, Color, Color, String) = {
                switch win.mode {
                case "open": return (Palette.mossTint, Palette.mossRim, Palette.moss700, "🟢")
                case "human_agent": return (Palette.orange50, Palette.orange200, Palette.amber700, "🟠")
                case "closed": return (Palette.red50, Palette.red200, Palette.red700, "🔴")
                default: return (Palette.stoneGreen, Palette.hairline, Palette.sage500, "•")
                }
            }()
            let t = tintOf(bg0, fg0, bd0, dark: c.isDark)
            let text: String = {
                switch win.mode {
                case "open": return "Reply window open — \(left(win.expiresAt, now: now)) left"
                case "human_agent": return "24h window closed — you can still reply as a human agent for \(left(win.humanAgentUntil, now: now)). Neema cannot."
                default: return win.reason ?? "Messaging window closed — only an approved template can reach them now."
                }
            }()
            HStack(spacing: 8) {
                Text(icon).font(.system(size: 11))
                Text(text).font(NeemaFont.manrope(11, .medium)).foregroundColor(t.fg).lineSpacing(2)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 12).padding(.vertical, 6)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(t.bg))
            .roundedBorder(t.border, radius: 8)
            .padding(.bottom, 8)
        }
    }
}

/// The system camera, returning a JPEG written to the picked-files folder.
struct CameraPicker: UIViewControllerRepresentable {
    let onImage: (URL?) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onImage: onImage) }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let p = UIImagePickerController()
        p.sourceType = .camera
        p.delegate = context.coordinator
        return p
    }

    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let onImage: (URL?) -> Void
        init(onImage: @escaping (URL?) -> Void) { self.onImage = onImage }
        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            let img = info[.originalImage] as? UIImage
            let url = img?.jpegData(compressionQuality: 0.92).flatMap { PickedFiles.write($0, name: "photo_\(AppClock.now()).jpg") }
            picker.dismiss(animated: true) { self.onImage(url) }
        }
        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { picker.dismiss(animated: true) { self.onImage(nil) } }
    }
}

/// Camera, photos & videos and documents through the system pickers.
private struct AttachButton: View {
    @ObservedObject var model: InboxScreenModel
    @Environment(\.neema) private var c
    @State private var photos: [PhotosPickerItem] = []
    @State private var showPhotos = false
    @State private var showDocs = false
    @State private var showCamera = false

    var body: some View {
        Menu {
            if UIImagePickerController.isSourceTypeAvailable(.camera) {
                Button { showCamera = true } label: { Label("Camera", systemImage: "camera") }
            }
            Button { showPhotos = true } label: { Label("Photos & videos", systemImage: "photo.on.rectangle") }
            Button { showDocs = true } label: { Label("Document", systemImage: "doc") }
        } label: {
            Image(systemName: "paperclip").font(.system(size: 17)).foregroundColor(Palette.slate500)
                .frame(width: 44, height: 44)
                .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(c.isDark ? c.bg3 : Palette.coolGray))
        }
        .accessibilityLabel("Attach images or files (up to 5 MB each for images)")
        .photosPicker(isPresented: $showPhotos, selection: $photos, maxSelectionCount: 10, matching: .any(of: [.images, .videos]))
        .onChange(of: photos) { _, items in
            guard !items.isEmpty else { return }
            photos = []
            Task { await addPhotos(items) }
        }
        .fileImporter(isPresented: $showDocs, allowedContentTypes: ACCEPT_TYPES, allowsMultipleSelection: true) { result in
            if case .success(let urls) = result { model.vm.addMedia(urls.compactMap { PickedFiles.copy($0) }) }
        }
        .fullScreenCover(isPresented: $showCamera) {
            CameraPicker { url in
                showCamera = false
                if let u = url { model.vm.addMedia([u]) }
            }
            .ignoresSafeArea()
        }
    }

    /// Each picked item is written to the app's folder with its real extension, so the tray can read it later.
    private func addPhotos(_ items: [PhotosPickerItem]) async {
        var urls: [URL] = []
        for item in items {
            guard let data = try? await item.loadTransferable(type: Data.self) else { continue }
            let type = item.supportedContentTypes.first
            let ext = type?.preferredFilenameExtension ?? (type?.conforms(to: .movie) == true ? "mp4" : "jpg")
            if let u = PickedFiles.write(data, name: "picked_\(AppClock.now()).\(ext)") { urls.append(u) }
        }
        if !urls.isEmpty { model.vm.addMedia(urls) }
    }
}

/// Files picked before the system closed the app that it no longer lets the
/// app read: named, so the agent attaches them again instead of wondering where they went.
private struct LostMediaNote: View {
    let names: [String]
    let onDismiss: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let t = tintOf(Palette.amber50, Palette.amber800, Palette.amber200, dark: c.isDark)
        let list = names.prefix(3).joined(separator: ", ") + (names.count > 3 ? " and \(names.count - 3) more" : "")
        HStack(spacing: 8) {
            Text("📎").font(.system(size: 11))
            Text("The app closed before \(names.count == 1 ? "this file was" : "these files were") sent — attach again: \(list)")
                .font(NeemaFont.manrope(11, .medium)).lineSpacing(2).foregroundColor(t.fg)
            Spacer(minLength: 0)
            Button(action: onDismiss) { Image(systemName: "xmark").font(.system(size: 12)).foregroundColor(t.fg).frame(width: 32, height: 32) }
                .accessibilityLabel("Dismiss")
        }
        .padding(.leading, 12).padding(.vertical, 4)
        .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(t.bg))
        .roundedBorder(t.border, radius: 8)
        .padding(.bottom, 8)
    }
}

/// A picked image's thumbnail, decoded once off the main thread.
private struct LocalThumb: View {
    let media: PickedMedia
    @State private var image: UIImage?
    var body: some View {
        ZStack { if let i = image { Image(uiImage: i).resizable().scaledToFill() } else { Color.black.opacity(0.05) } }
            .task(id: media.id) {
                let bytes = media.bytes
                let file = media.file
                let img: UIImage? = await Task.detached(priority: .utility) {
                    if let b = bytes, let i = UIImage(data: b) { return i.preparingThumbnail(of: CGSize(width: 168, height: 168)) ?? i }
                    if let f = file, let i = UIImage(contentsOfFile: f.path) { return i.preparingThumbnail(of: CGSize(width: 168, height: 168)) ?? i }
                    return nil
                }.value
                image = img
            }
    }
}

/// Picked files, each with its OWN caption, then Send N / Cancel.
private struct MediaTray: View {
    @ObservedObject var model: InboxScreenModel
    @Environment(\.neema) private var c
    @State private var showMore = false

    var body: some View {
        let state = model.composer
        let vm = model.vm
        let retry = state.media.contains { $0.error != nil }
        VStack(spacing: 8) {
            // The files scroll when the keyboard leaves little room; Send / Cancel never do.
            ScrollView {
                VStack(spacing: 8) {
                    ForEach(state.media) { m in
                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 10) {
                                ZStack(alignment: .topTrailing) {
                                    Group {
                                        if m.isImage {
                                            LocalThumb(media: m)
                                        } else {
                                            VStack(spacing: 2) {
                                                Image(systemName: m.mime.hasPrefix("video/") ? "film" : "doc.text").font(.system(size: 18)).foregroundColor(Palette.sage400)
                                                Text(m.name).font(NeemaFont.fixed(9)).foregroundColor(c.isDark ? c.textMid : Palette.sageCaption).lineLimit(1)
                                            }
                                            .padding(2)
                                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                                            .background(c.isDark ? c.bg4 : Palette.hairline)
                                        }
                                    }
                                    .frame(width: 56, height: 56)
                                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                                    .roundedBorder(hairline(c), radius: 8)
                                    Button { vm.removeMedia(m.id) } label: {
                                        Image(systemName: "xmark").font(.system(size: 10, weight: .bold)).foregroundColor(.white)
                                            .frame(width: 20, height: 20).background(Circle().fill(Palette.ink))
                                    }
                                    .offset(x: 6, y: -6)
                                    .disabled(state.uploading)
                                    .accessibilityLabel("Remove")
                                }
                                // The web's compact caption input: white, #e8ebe3 hairline, text-xs.
                                TextField("Add a caption (optional)…", text: Binding(get: { m.caption }, set: { vm.setMediaCaption(m.id, $0) }))
                                    .font(NeemaFont.manrope(12)).foregroundColor(c.text).tint(Palette.moss600)
                                    .disabled(state.uploading)
                                    .padding(.horizontal, 8).padding(.vertical, 7)
                                    .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.isDark ? c.bg2 : .white))
                                    .roundedBorder(c.isDark ? c.border : Palette.hairline, radius: 8)
                                    .opacity(state.uploading ? 0.5 : 1)
                            }
                            // A file that didn't go says why, under its own row; it stays for a retry.
                            if let why = m.error {
                                Text("⚠ Not sent — \(why)").font(NeemaFont.manrope(11)).lineSpacing(2).foregroundColor(c.isDark ? Palette.red400 : Palette.red700).padding(.leading, 66)
                            }
                        }
                    }
                    // Add-more tile
                    HStack {
                        Button { showMore = true } label: {
                            Image(systemName: "plus").foregroundColor(Palette.sage400).frame(width: 56, height: 56).dashedBorder(Palette.sageDash, radius: 8)
                        }
                        .disabled(state.uploading)
                        .accessibilityLabel("Add more")
                        Spacer()
                    }
                }
            }
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxHeight: 240)
            HStack(spacing: 6) {
                Button { vm.sendMedia() } label: {
                    HStack(spacing: 4) {
                        if state.uploading {
                            ProgressView().tint(.white).scaleEffect(0.6).frame(width: 12, height: 12)
                            Text("Sending…").font(NeemaFont.manrope(12))
                        } else {
                            Image(systemName: "paperplane.fill").font(.system(size: 11))
                            Text(retry ? (state.media.count > 1 ? "Retry \(state.media.count)" : "Retry") : state.media.count > 1 ? "Send \(state.media.count)" : "Send").font(NeemaFont.manrope(12))
                        }
                    }
                    .foregroundColor(.white)
                    .padding(.horizontal, 12).padding(.vertical, 4).frame(minHeight: 28)
                    .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Palette.moss600.opacity(state.uploading ? 0.5 : 1)))
                }
                .disabled(state.uploading)
                Button { vm.clearMedia() } label: {
                    Text("Cancel").font(NeemaFont.manrope(12)).foregroundColor(Palette.sage400)
                        .padding(.horizontal, 12).padding(.vertical, 4).frame(minHeight: 28)
                        .roundedBorder(c.isDark ? c.border : Palette.hairline, radius: 8)
                }
                .disabled(state.uploading)
                Spacer()
                Text("Images up to 5 MB each").font(NeemaFont.manrope(10)).foregroundColor(Palette.sage400).multilineTextAlignment(.trailing)
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.isDark ? c.bg3 : Palette.mist))
        .roundedBorder(c.isDark ? c.border : Palette.hairline, radius: 12)
        .padding(.top, 8)
        .fileImporter(isPresented: $showMore, allowedContentTypes: ACCEPT_TYPES, allowsMultipleSelection: true) { result in
            if case .success(let urls) = result { vm.addMedia(urls.compactMap { PickedFiles.copy($0) }) }
        }
    }
}
