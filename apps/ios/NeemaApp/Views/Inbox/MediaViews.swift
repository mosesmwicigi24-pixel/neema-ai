import SwiftUI
import Combine
import AVKit
import AVFoundation
import NeemaCore

// Bubble palette (the web's literal hex values).
func inboundTint(_ c: NeemaColors) -> Color { ink(Palette.willow600, dark: c.isDark) }
func inboundTintBg(_ c: NeemaColors) -> Color { c.isDark ? Palette.willow600.opacity(0.16) : Palette.mossTint }
/// The revealed transcript / analysis text inside an inbound bubble (light or dark page).
private func revealInk(_ c: NeemaColors) -> Color { c.isDark ? Color.white.opacity(0.7) : Palette.forestInk.opacity(0.7) }

/// A remote image that reports a failed load (AsyncImage with an error hook).
struct RemoteImage: View {
    let url: String
    var contentMode: ContentMode = .fill
    var onError: () -> Void = {}

    var body: some View {
        if let u = URL(string: url) {
            AsyncImage(url: u) { phase in
                switch phase {
                case .success(let img):
                    img.resizable().aspectRatio(contentMode: contentMode)
                case .failure:
                    Color.clear.onAppear(perform: onError)
                default:
                    ZStack { Color.black.opacity(0.05); ProgressView().scaleEffect(0.7) }
                }
            }
        } else {
            Color.clear.onAppear(perform: onError)
        }
    }
}

/// "Show transcript" / "Show image analysis" pill toggle.
struct RevealToggle: View {
    let open: Bool
    let showLabel: String
    let hideLabel: String
    let inbound: Bool
    let action: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let col = inbound ? inboundTint(c) : Color.white.opacity(0.8)
        Button(action: action) {
            HStack(spacing: 2) {
                Text(open ? hideLabel : showLabel).font(NeemaFont.manrope(10, .medium)).foregroundColor(col)
                Image(systemName: "chevron.down").font(.system(size: 9, weight: .semibold)).foregroundColor(col).rotationEffect(.degrees(open ? 180 : 0))
            }
            .padding(.horizontal, 8).padding(.vertical, 3)
            .background(Capsule().fill(inbound ? inboundTintBg(c) : Color.white.opacity(0.15)))
        }
        .buttonStyle(.plain)
    }
}

/// Unrecoverable / expired media: Meta's signed CDN links expire, so an older
/// photo would render as an empty bubble. Say what was sent, and offer one tap
/// to fetch the original back from Meta.
struct MediaFallback: View {
    let kind: String
    let messageId: String?
    let inbound: Bool
    let onRecover: (String, @escaping @MainActor (Recovery) -> Void) -> Void
    let onRecovered: (String) -> Void
    @Environment(\.neema) private var c
    @State private var state = "idle"
    // A failed attempt (no connection, server trouble) says why and keeps the button.
    @State private var why: String?

    var body: some View {
        let label = kind == "video" ? "Video" : "Photo"
        // An inbound bubble is dark in dark mode: its ink flips to light.
        let dark = inbound && c.isDark
        let light = inbound && !dark
        VStack(alignment: .leading, spacing: 4) {
            Text("\(kind == "video" ? "🎬" : "📷") \(label) sent").font(NeemaFont.manrope(12, .medium))
            Text(state == "gone" ? "Meta no longer has this file — ask the customer to resend." : why.map { "Couldn't fetch it — \($0)" } ?? "Preview link expired.")
                .font(NeemaFont.manrope(11)).foregroundColor(light ? Color.black.opacity(0.5) : Color.white.opacity(0.7))
            if let id = messageId, state != "gone" {
                Button {
                    state = "loading"; why = nil
                    onRecover(id) { r in
                        switch r {
                        case .found(let url): state = "idle"; onRecovered(url)
                        case .gone: state = "gone"
                        case .failed(let w): state = "idle"; why = w.prefix(1).lowercased() + w.dropFirst()
                        }
                    }
                } label: {
                    Text(state == "loading" ? "Fetching…" : why != nil ? "Try again" : "Recover from Meta")
                        .font(NeemaFont.manrope(10, .medium)).foregroundColor(inbound ? ink(Palette.moss700, dark: c.isDark) : .white)
                        .padding(.horizontal, 8).padding(.vertical, 3)
                        .background(Capsule().fill(inbound ? inboundTintBg(c) : Color.white.opacity(0.2)))
                        .opacity(state == "loading" ? 0.6 : 1)
                }
                .buttonStyle(.plain)
                .disabled(state == "loading")
            }
        }
        .padding(12)
        .frame(width: 224, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(light ? Color.black.opacity(0.03) : Color.white.opacity(0.06)))
        .dashedBorder(light ? Color.black.opacity(0.15) : Color.white.opacity(0.3), radius: 12)
    }
}

/// A customer photo: tap for the in-app viewer; collapsible AI image analysis; the caption.
struct ImageBubble: View {
    let src: String
    let analysis: String?
    let caption: String?
    let inbound: Bool
    let messageId: String?
    let onView: (Viewer) -> Void
    let onRecover: (String, @escaping @MainActor (Recovery) -> Void) -> Void
    @Environment(\.neema) private var c
    @State private var url: String = ""
    @State private var broken = false
    @State private var open = false

    var body: some View {
        let u = url.isEmpty ? src : url
        VStack(alignment: .leading, spacing: 6) {
            if broken {
                MediaFallback(kind: "image", messageId: messageId, inbound: inbound, onRecover: onRecover, onRecovered: { url = $0; broken = false })
            } else {
                RemoteImage(url: u) { broken = true }
                    .frame(maxWidth: 260, maxHeight: 240)
                    .frame(minWidth: 120, minHeight: 90)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .roundedBorder(Color.black.opacity(0.1), radius: 12)
                    .contentShape(Rectangle())
                    .onTapGesture { onView(.image(url: u)) }
                    .accessibilityLabel(caption ?? "image")
                    .accessibilityAddTraits(.isButton)
            }
            if let a = analysis, !a.trimmingCharacters(in: .whitespaces).isEmpty {
                RevealToggle(open: open, showLabel: "Show image analysis", hideLabel: "Hide image analysis", inbound: inbound) { open.toggle() }
                if open {
                    Text(a).font(NeemaFont.manrope(11)).italic(inbound).lineSpacing(3)
                        .foregroundColor(inbound ? revealInk(c) : Color.white.opacity(0.8)).padding(.horizontal, 4)
                }
            }
            if let cap = caption, !cap.trimmingCharacters(in: .whitespaces).isEmpty, !cap.hasPrefix("[") {
                Text(cap).font(NeemaFont.manrope(12)).lineSpacing(3).padding(.horizontal, 4)
                    .foregroundColor(inbound ? (c.isDark ? c.text : Palette.forestText) : Color.white.opacity(0.9))
            }
        }
        .onChange(of: src) { _ in url = ""; broken = false }
    }
}

/// A video's first frame, drawn once per URL.
struct VideoPoster: View {
    let url: String
    @State private var image: UIImage?

    var body: some View {
        ZStack {
            if let img = image { Image(uiImage: img).resizable().scaledToFill() } else { Color.black.opacity(0.2) }
        }
        .task(id: url) {
            guard let u = URL(string: url) else { return }
            let asset = AVURLAsset(url: u)
            let gen = AVAssetImageGenerator(asset: asset)
            gen.appliesPreferredTrackTransform = true
            gen.maximumSize = CGSize(width: 640, height: 640)
            let time = CMTime(seconds: 1, preferredTimescale: 600)
            let cg: CGImage? = await withCheckedContinuation { cont in
                gen.generateCGImagesAsynchronously(forTimes: [NSValue(time: time)]) { _, img, _, _, _ in cont.resume(returning: img) }
            }
            if let cg = cg { image = UIImage(cgImage: cg) }
        }
    }
}

/// A video: a poster frame with a play button; plays full-screen.
struct VideoBubble: View {
    let src: String
    let caption: String?
    let inbound: Bool
    let messageId: String?
    let brokenIds: Set<String>
    let fg: Color
    let onView: (Viewer) -> Void
    let onRecover: (String, @escaping @MainActor (Recovery) -> Void) -> Void
    @Environment(\.neema) private var c
    @State private var url: String = ""

    var body: some View {
        let u = url.isEmpty ? src : url
        VStack(alignment: .leading, spacing: 4) {
            if let id = messageId, brokenIds.contains(id), url.isEmpty {
                MediaFallback(kind: "video", messageId: messageId, inbound: inbound, onRecover: onRecover, onRecovered: { url = $0 })
            } else {
                ZStack {
                    VideoPoster(url: u)
                    PlayBadge(loading: false, video: true)
                }
                .frame(width: 240, height: 180)
                .background(Palette.ink)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .contentShape(Rectangle())
                .onTapGesture { onView(.video(url: u, messageId: messageId)) }
                .accessibilityLabel("Play video")
                .accessibilityAddTraits(.isButton)
            }
            if let cap = caption, !cap.trimmingCharacters(in: .whitespaces).isEmpty {
                WaTextView(text: cap, color: fg, link: inbound ? Palette.blue600 : Palette.blue300).padding(.horizontal, 4)
            }
        }
    }
}

struct PlayBadge: View {
    let loading: Bool
    let video: Bool
    var body: some View {
        ZStack {
            Circle().fill(Color.white.opacity(0.9)).frame(width: 40, height: 40)
            if loading { ProgressView().tint(Palette.moss700).scaleEffect(0.7) }
            else if video { Image(systemName: "play.fill").foregroundColor(Palette.ink) }
            else { Image(systemName: "arrow.up.left.and.arrow.down.right").font(.system(size: 15)).foregroundColor(Palette.ink) }
        }
    }
}

/// An audio clip's player state, outside the view so a redraw never restarts it.
@MainActor
final class AudioClip: ObservableObject {
    @Published var playing = false
    @Published var position: Double = 0
    @Published var duration: Double = 0
    @Published var failed = false
    private var player: AVPlayer?
    private var ticker: Any?
    private var endObserver: Any?

    func toggle(_ src: String) {
        if player == nil {
            guard let u = URL(string: src) else { failed = true; return }
            let item = AVPlayerItem(url: u)
            let p = AVPlayer(playerItem: item)
            player = p
            try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
            try? AVAudioSession.sharedInstance().setActive(true)
            ticker = p.addPeriodicTimeObserver(forInterval: CMTime(seconds: 0.25, preferredTimescale: 600), queue: .main) { [weak self] t in
                guard let self = self else { return }
                self.position = t.seconds
                let d = item.duration.seconds
                if d.isFinite && d > 0 { self.duration = d }
                if item.status == .failed { self.failed = true; self.playing = false }
            }
            endObserver = NotificationCenter.default.addObserver(forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: .main) { [weak self] _ in
                guard let self = self else { return }
                self.player?.pause(); self.player?.seek(to: .zero); self.position = 0; self.playing = false
            }
        }
        guard let p = player else { return }
        if playing { p.pause(); playing = false } else { p.play(); playing = true }
    }

    func seek(_ fraction: Double) {
        guard let p = player, duration > 0 else { return }
        let t = fraction * duration
        p.seek(to: CMTime(seconds: t, preferredTimescale: 600))
        position = t
    }

    func stop() {
        player?.pause()
        if let t = ticker { player?.removeTimeObserver(t) }
        if let e = endObserver { NotificationCenter.default.removeObserver(e) }
        player = nil; ticker = nil; endObserver = nil
        playing = false
    }
}

/// Voice note / audio: an in-bubble player plus the collapsible transcript (and the AI's cart text).
struct AudioBubble: View {
    let src: String
    let transcription: String?
    let cartText: String?
    let inbound: Bool
    @Environment(\.neema) private var c
    @StateObject private var clip = AudioClip()
    @State private var open = false

    var body: some View {
        let fg: Color = inbound ? (c.isDark ? c.textMid : Palette.moss700) : .white
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Button { clip.toggle(src) } label: {
                    Image(systemName: clip.playing ? "pause.fill" : "play.fill").font(.system(size: 16)).foregroundColor(fg).frame(width: 36, height: 36)
                }
                .accessibilityLabel(clip.playing ? "Pause" : "Play")
                Slider(value: Binding(get: { clip.duration > 0 ? min(1, max(0, clip.position / clip.duration)) : 0 }, set: { clip.seek($0) }))
                    .tint(fg)
                    .frame(height: 24)
                Text(Fmt.duration(Int((clip.playing || clip.position > 0) ? clip.position : clip.duration)))
                    .font(NeemaFont.manrope(10)).foregroundColor(fg.opacity(0.8)).padding(.leading, 6)
            }
            .frame(minWidth: 220)
            if clip.failed { Text("Couldn't play this audio.").font(NeemaFont.manrope(10)).foregroundColor(fg.opacity(0.7)) }
            if let t = transcription, !t.trimmingCharacters(in: .whitespaces).isEmpty {
                RevealToggle(open: open, showLabel: "Show transcript", hideLabel: "Hide transcript", inbound: inbound) { open.toggle() }
                if open {
                    Text(t).font(NeemaFont.manrope(11)).italic(inbound).lineSpacing(3)
                        .foregroundColor(inbound ? revealInk(c) : Color.white.opacity(0.8)).padding(.horizontal, 4)
                }
            }
            if !inbound, let cart = cartText, !cart.trimmingCharacters(in: .whitespaces).isEmpty {
                Text(cart).font(NeemaFont.manrope(11, .medium)).lineSpacing(3).foregroundColor(.white)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 8).padding(.vertical, 6)
                    .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Color.white.opacity(0.2)))
            }
        }
        .onDisappear { clip.stop() }
    }
}

/// Documents open through the system (the URL), like the web's download link.
struct DocumentTile: View {
    let url: String
    let name: String
    let inbound: Bool
    @Environment(\.neema) private var c
    @Environment(\.openURL) private var openURL

    var body: some View {
        let col: Color = inbound ? c.text : .white
        Button { if let u = URL(string: url) { openURL(u) } } label: {
            HStack(spacing: 8) {
                Image(systemName: "doc.text").font(.system(size: 18)).foregroundColor(col.opacity(0.7))
                Text(name).font(NeemaFont.manrope(12, .medium)).foregroundColor(col).lineLimit(1).frame(maxWidth: 160)
                Image(systemName: "arrow.down.circle").font(.system(size: 14)).foregroundColor(col.opacity(0.6))
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(inbound ? (c.isDark ? c.bg3 : .white) : Color.white.opacity(0.2)))
            .roundedBorder(inbound ? (c.isDark ? c.border : Palette.hairline2) : Color.white.opacity(0.3), radius: 12)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Open \(name)")
    }
}

/// WhatsApp-style album: ≥2 consecutive photos from one side in one collage bubble.
struct AlbumGrid: View {
    let items: [AlbumItem]
    let onOpen: (Int) -> Void

    var body: some View {
        let n = items.count
        let shown = Array(items.prefix(4))
        let extra = n - 4
        VStack(spacing: 4) {
            if n == 3 {
                // 3 photos: the big one on top.
                AlbumCell(item: shown[0], index: 0, more: false, extra: extra, onOpen: onOpen).frame(height: 160)
                HStack(spacing: 4) {
                    ForEach(1..<3, id: \.self) { j in AlbumCell(item: shown[j], index: j, more: false, extra: extra, onOpen: onOpen).frame(height: 128) }
                }
            } else {
                ForEach(Array(stride(from: 0, to: shown.count, by: 2)), id: \.self) { i in
                    HStack(spacing: 4) {
                        ForEach(i..<min(i + 2, shown.count), id: \.self) { j in
                            AlbumCell(item: shown[j], index: j, more: j == 3 && extra > 0, extra: extra, onOpen: onOpen).frame(height: 128)
                        }
                    }
                }
            }
        }
        .frame(width: 256)
    }
}

private struct AlbumCell: View {
    let item: AlbumItem
    let index: Int
    let more: Bool
    let extra: Int
    let onOpen: (Int) -> Void
    var body: some View {
        ZStack {
            RemoteImage(url: item.src)
            if more {
                Color.black.opacity(0.55)
                Text("+\(extra)").font(NeemaFont.manrope(20, .semibold)).foregroundColor(.white)
            }
        }
        .frame(maxWidth: .infinity)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .contentShape(Rectangle())
        .onTapGesture { onOpen(index) }
        .accessibilityLabel(item.caption ?? "photo \(index + 1)")
        .accessibilityAddTraits(.isButton)
    }
}

/// A Facebook/Instagram comment is meaningless without the post it is on.
/// This shows the post/reel: tapping PLAYS it in-app (fresh video URL fetched
/// on demand via postVideo), or opens the photo, or falls back to the permalink.
struct CommentContextCard: View {
    let ctx: PostContext
    let inbound: Bool
    let channel: String?
    let heading: String?
    let onView: (Viewer) -> Void
    let fetchVideo: (String, String?) async -> String?
    @Environment(\.neema) private var c
    @Environment(\.openURL) private var openURL
    @State private var loading = false
    @State private var thumbOk = true

    var body: some View {
        let title = (ctx.title ?? "").trimmingCharacters(in: .whitespaces)
        let permalink = ctx.permalink ?? ""
        let thumb = ctx.thumb ?? ""
        let postId = ctx.postId ?? ""
        // Unknown media_type (old rows) → still try to play; the endpoint 404s for a photo.
        let maybeVideo = ctx.hasVideo == true || ctx.mediaType == "video" || ctx.mediaType == nil
        let dark = inbound && c.isDark
        let open = {
            guard !loading else { return }
            Task {
                if !postId.isEmpty && maybeVideo {
                    loading = true
                    let v = await fetchVideo(postId, channel)
                    loading = false
                    if let v = v, !v.isEmpty { onView(.video(url: v, messageId: nil)); return }
                }
                if !thumb.isEmpty { onView(.image(url: thumb)) }
                else if let u = URL(string: permalink), !permalink.isEmpty { openURL(u) }
            }
        }
        VStack(alignment: .leading, spacing: 0) {
            Text((heading ?? "Commented on your post").uppercased()).font(NeemaFont.manrope(9, .semibold)).tracking(0.4)
                .foregroundColor(inbound ? inboundTint(c) : Color.white.opacity(0.7))
            Spacer().frame(height: 4)
            Text(title.isEmpty ? "a post" : title).font(NeemaFont.manrope(11)).lineLimit(2).lineSpacing(2)
                .foregroundColor(dark ? c.text : inbound ? Palette.forestInk : Color.white.opacity(0.9))
            Spacer().frame(height: 6)
            if !thumb.isEmpty && thumbOk {
                ZStack {
                    RemoteImage(url: thumb) { thumbOk = false }
                    Color.black.opacity(0.2)
                    PlayBadge(loading: loading, video: maybeVideo)
                }
                .frame(maxWidth: 260).aspectRatio(16 / 9, contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .contentShape(Rectangle())
                .onTapGesture(perform: open)
                .accessibilityLabel(maybeVideo ? "Play" : "View")
            } else if !postId.isEmpty && maybeVideo {
                Button(action: open) {
                    HStack(spacing: 4) {
                        if loading { ProgressView().scaleEffect(0.6) } else { Image(systemName: "play.fill").font(.system(size: 12)) }
                        Text("Play reel").font(NeemaFont.manrope(11))
                    }
                    .padding(.horizontal, 4).padding(.vertical, 6)
                }
                .foregroundColor(inbound ? inboundTint(c) : .white)
            }
            if !permalink.isEmpty, let u = URL(string: permalink) {
                Button { openURL(u) } label: {
                    HStack(spacing: 3) {
                        Text("View on Facebook").font(NeemaFont.manrope(10, .medium))
                        Image(systemName: "arrow.up.right.square").font(.system(size: 9))
                    }
                    .foregroundColor(inbound ? inboundTint(c) : Color.white.opacity(0.7))
                }
                .padding(.top, 6)
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(dark ? Palette.moss600.opacity(0.10) : inbound ? Palette.leaf : Color.white.opacity(0.15)))
        .roundedBorder(dark ? c.border : inbound ? Palette.sageRing : Color.white.opacity(0.2), radius: 8)
    }
}

// ═══════════════════════════ Full-screen viewers ═══════════════════════════

/// In-app viewer: photos (pinch to zoom), videos and albums (swipe ‹ ›).
struct ViewerScreen: View {
    let viewer: Viewer
    let onClose: () -> Void
    let onVideoError: (String?) -> Void
    @State private var page = 0

    var body: some View {
        ZStack(alignment: .topTrailing) {
            // The web's overlay: the Lightbox bg-black/85, the album viewer bg-black/90.
            Color.black.opacity({ if case .album = viewer { return 0.9 } else { return 0.85 } }()).ignoresSafeArea()
            switch viewer {
            case .image(let url):
                ZoomableImage(url: url, onBackdrop: onClose)
            case .video(let url, let messageId):
                VideoPlayerView(url: url) { onVideoError(messageId); onClose() }
                    .padding(.vertical, 48)
            case .album(let items, let start):
                TabView(selection: $page) {
                    ForEach(Array(items.enumerated()), id: \.offset) { i, it in
                        VStack {
                            ZoomableImage(url: it.src, onBackdrop: onClose)
                            if let cap = it.caption {
                                Text(cap).font(NeemaFont.manrope(14)).foregroundColor(Color.white.opacity(0.9)).multilineTextAlignment(.center).padding(16)
                            }
                        }
                        .tag(i)
                    }
                }
                .tabViewStyle(.page(indexDisplayMode: .never))
                .onAppear { page = min(max(start, 0), max(items.count - 1, 0)) }
                Text("\(page + 1) / \(items.count)").font(NeemaFont.manrope(14)).foregroundColor(Color.white.opacity(0.7))
                    .frame(maxWidth: .infinity).padding(.top, 16)
                if items.count > 1 {
                    HStack {
                        Button { withAnimation { page = (page + items.count - 1) % items.count } } label: {
                            Image(systemName: "chevron.left").font(.system(size: 28)).foregroundColor(Color.white.opacity(0.8)).frame(width: 56, height: 56)
                        }
                        .accessibilityLabel("Previous")
                        Spacer()
                        Button { withAnimation { page = (page + 1) % items.count } } label: {
                            Image(systemName: "chevron.right").font(.system(size: 28)).foregroundColor(Color.white.opacity(0.8)).frame(width: 56, height: 56)
                        }
                        .accessibilityLabel("Next")
                    }
                    .frame(maxHeight: .infinity)
                }
            }
            Button(action: onClose) {
                Image(systemName: "xmark").font(.system(size: 22, weight: .semibold)).foregroundColor(Color.white.opacity(0.9)).frame(width: 48, height: 48)
            }
            .padding(8)
            .accessibilityLabel("Close")
        }
    }
}

private struct ZoomableImage: View {
    let url: String
    let onBackdrop: () -> Void
    @State private var scale: CGFloat = 1
    @State private var lastScale: CGFloat = 1
    @State private var offset: CGSize = .zero
    @State private var lastOffset: CGSize = .zero

    var body: some View {
        ZStack {
            if let u = URL(string: url) {
                AsyncImage(url: u) { phase in
                    switch phase {
                    case .success(let img): img.resizable().scaledToFit()
                    case .failure: Text("Couldn't load this image.").foregroundColor(.white)
                    default: ProgressView().tint(.white)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .scaleEffect(scale)
        .offset(offset)
        .gesture(
            MagnificationGesture()
                .onChanged { v in scale = min(5, max(1, lastScale * v)) }
                .onEnded { _ in lastScale = scale; if scale == 1 { offset = .zero; lastOffset = .zero } }
        )
        .simultaneousGesture(
            DragGesture()
                .onChanged { v in if scale > 1 { offset = CGSize(width: lastOffset.width + v.translation.width, height: lastOffset.height + v.translation.height) } }
                .onEnded { _ in lastOffset = offset }
        )
        .onTapGesture(count: 2) {
            withAnimation { if scale > 1 { scale = 1; lastScale = 1; offset = .zero; lastOffset = .zero } else { scale = 2.5; lastScale = 2.5 } }
        }
        .onTapGesture { if scale == 1 { onBackdrop() } }
    }
}

/// AVKit's player; a failed item reports back (the bubble then offers a recovery).
struct VideoPlayerView: View {
    let url: String
    let onError: () -> Void
    @State private var player: AVPlayer?

    var body: some View {
        Group {
            if let p = player { VideoPlayer(player: p) } else { ProgressView().tint(.white) }
        }
        .onAppear {
            guard let u = URL(string: url) else { onError(); return }
            let item = AVPlayerItem(url: u)
            let p = AVPlayer(playerItem: item)
            player = p
            p.play()
        }
        .onDisappear { player?.pause(); player = nil }
        .onReceive(NotificationCenter.default.publisher(for: .AVPlayerItemFailedToPlayToEndTime)) { _ in onError() }
        .onReceive(player?.currentItem?.publisher(for: \.status).eraseToAnyPublisher() ?? Empty().eraseToAnyPublisher()) { s in
            if s == .failed { onError() }
        }
    }
}
