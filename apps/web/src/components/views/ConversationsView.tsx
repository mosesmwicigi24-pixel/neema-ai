import React, { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { Avatar } from "@/components/ui/Avatar";
import {
    InterceptBadge,
    ChannelBadge,
    RoleBadge,
} from "@/components/ui/Badges";
import { Btn } from "@/components/ui/Btn";
import { Modal } from "@/components/ui/Modal";
import { TextareaField, InputField } from "@/components/ui/FormFields";
import { Toggle } from "@/components/ui/Layout";
import { timeAgo, formatPhone, displayName, countryName } from "@/lib/utils";
import { formatWa } from "@/lib/waText";
import { CHANNEL_CONFIG, ALL_CHANNELS } from "@/lib/channels";
import { conversationsApi, profileApi, type ApiActivityEvent } from "@/lib/api";
import { useConversationEvents, buildSystemEventFromWs } from "@/lib/websocket";
import { CustomerSidebar } from "@/components/ui/CustomerSidebar";
import type {
    Conversation,
    Message,
    MessagesMap,
    Agent,
    Order,
    Channel,
    SharedViewProps,
} from "@/types";
import { useSession } from "next-auth/react";

// ── AudioBubble ───────────────────────────────────────────────────────────────
// Renders an audio player with a collapsible transcription toggle.
// The transcript is hidden by default; agents expand it on demand.
function AudioBubble({
    src,
    transcription,
    cartText,
    isInbound,
}: {
    src: string;
    transcription: string | null;
    cartText: string | null;
    isInbound: boolean;
}) {
    const [open, setOpen] = React.useState(false);
    const hasTranscript   = !!transcription;

    return (
        <div className="flex flex-col gap-1 w-full min-w-[220px]">
            <audio src={src} controls className="w-full" style={{ minWidth: 220 }} />

            {hasTranscript && (
                <button
                    onClick={() => setOpen((o) => !o)}
                    className={[
                        "flex items-center gap-1.5 text-[10px] font-medium",
                        "transition-colors w-fit rounded-full px-2 py-0.5",
                        isInbound
                            ? "text-[#699a32] hover:text-[#427425] bg-[#f0f9e8]"
                            : "text-white/70 hover:text-white bg-white/15",
                    ].join(" ")}
                >
                    <svg className="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414A1 1 0 0119 9.414V19a2 2 0 01-2 2z" />
                    </svg>
                    {open ? "Hide transcript" : "Show transcript"}
                    <span style={{ display: "inline-block", transform: open ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.15s" }}>▾</span>
                </button>
            )}

            {open && transcription && (
                <p className={[
                    "text-[11px] leading-relaxed px-1 whitespace-pre-wrap",
                    isInbound ? "italic text-[#3a5c28]/70" : "text-white/80",
                ].join(" ")}>
                    {transcription}
                </p>
            )}

            {!isInbound && cartText && (
                <div className="text-[11px] px-2 py-1.5 rounded-lg bg-white/20 font-medium whitespace-pre-wrap leading-relaxed">
                    {cartText}
                </div>
            )}
        </div>
    );
}

// ── Lightbox ──────────────────────────────────────────────────────────────────
// A full-screen in-app viewer so the agent sees a shared photo, or plays a reel,
// WITHOUT leaving to Facebook/WhatsApp. Click the backdrop or ✕ to close.
function Lightbox({
    src,
    kind,
    onClose,
}: {
    src: string;
    kind: "image" | "video";
    onClose: () => void;
}) {
    return (
        <div
            onClick={onClose}
            className="fixed inset-0 z-[200] bg-black/85 flex items-center justify-center p-4"
        >
            <button
                onClick={onClose}
                className="absolute top-4 right-5 text-white/80 hover:text-white text-3xl leading-none"
                aria-label="Close"
            >
                ✕
            </button>
            {kind === "video" ? (
                <video
                    src={src}
                    controls
                    autoPlay
                    onClick={(e) => e.stopPropagation()}
                    className="max-w-full max-h-[90vh] rounded-lg shadow-2xl"
                />
            ) : (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                    src={src}
                    alt=""
                    onClick={(e) => e.stopPropagation()}
                    className="max-w-full max-h-[90vh] rounded-lg object-contain shadow-2xl"
                />
            )}
        </div>
    );
}

// ── Lead-stage row chip palette (matches the sidebar pipeline) ───────────────
const STAGE_CHIP: Record<string, { bg: string; fg: string; bd: string }> = {
    contacted:   { bg: "#e0f2fe", fg: "#0369a1", bd: "#bae6fd" },
    qualified:   { bg: "#fef3c7", fg: "#b45309", bd: "#fde68a" },
    negotiation: { bg: "#ede9fe", fg: "#6d28d9", bd: "#ddd6fe" },
    proposal:    { bg: "#ede9fe", fg: "#6d28d9", bd: "#ddd6fe" },
    won:         { bg: "#dcfce7", fg: "#15803d", bd: "#bbf7d0" },
    lost:        { bg: "#fee2e2", fg: "#b91c1c", bd: "#fecaca" },
};

// ── Album (WhatsApp-style) ───────────────────────────────────────────────────
// Consecutive images from the same side collapse into ONE collage bubble;
// clicking any cell opens the sequential viewer with ‹ › navigation.

type AlbumItem = { src: string; caption: string | null };

function AlbumGrid({ items, onOpen }: { items: AlbumItem[]; onOpen: (index: number) => void }) {
    const n = items.length;
    const shown = items.slice(0, 4);
    const extra = n - 4;
    return (
        <div className="grid grid-cols-2 gap-1 w-64">
            {shown.map((it, i) => {
                const tallFirst = n === 3 && i === 0;         // 3 photos: big one on top
                return (
                    <button
                        key={i}
                        type="button"
                        onClick={() => onOpen(i)}
                        className={`relative block overflow-hidden rounded-lg ${tallFirst ? "col-span-2 h-40" : "h-32"}`}
                    >
                        <img src={it.src} alt={it.caption || `photo ${i + 1}`}
                             className="w-full h-full object-cover cursor-zoom-in" />
                        {i === 3 && extra > 0 && (
                            <span className="absolute inset-0 bg-black/55 flex items-center justify-center text-white text-xl font-semibold">
                                +{extra}
                            </span>
                        )}
                    </button>
                );
            })}
        </div>
    );
}

function AlbumViewer({ items, start, onClose }: {
    items: AlbumItem[]; start: number; onClose: () => void;
}) {
    const [i, setI] = React.useState(start);
    const prev = React.useCallback(() => setI((v) => (v + items.length - 1) % items.length), [items.length]);
    const next = React.useCallback(() => setI((v) => (v + 1) % items.length), [items.length]);
    React.useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") onClose();
            else if (e.key === "ArrowLeft") prev();
            else if (e.key === "ArrowRight") next();
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [onClose, prev, next]);
    const cur = items[i];
    if (!cur) return null;
    return (
        <div onClick={onClose} className="fixed inset-0 z-[200] bg-black/90 flex flex-col items-center justify-center p-4">
            <button onClick={onClose} aria-label="Close"
                    className="absolute top-4 right-5 text-white/80 hover:text-white text-3xl leading-none">✕</button>
            <span className="absolute top-5 left-1/2 -translate-x-1/2 text-white/70 text-sm">{i + 1} / {items.length}</span>
            {items.length > 1 && (
                <button aria-label="Previous"
                        onClick={(e) => { e.stopPropagation(); prev(); }}
                        className="absolute left-3 top-1/2 -translate-y-1/2 text-white/70 hover:text-white text-4xl px-2">‹</button>
            )}
            <img src={cur.src} alt={cur.caption || ""} onClick={(e) => e.stopPropagation()}
                 className="max-w-full max-h-[82vh] rounded-lg object-contain shadow-2xl" />
            {items.length > 1 && (
                <button aria-label="Next"
                        onClick={(e) => { e.stopPropagation(); next(); }}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-white/70 hover:text-white text-4xl px-2">›</button>
            )}
            {cur.caption && (
                <p onClick={(e) => e.stopPropagation()}
                   className="mt-3 max-w-2xl text-center text-white/90 text-sm">{cur.caption}</p>
            )}
        </div>
    );
}

// ── CommentContextCard ────────────────────────────────────────────────────────
// A Facebook/Instagram comment is a reply to one of our posts — but the comment
// text alone ("how much?") is meaningless without it. This card shows WHAT the
// comment is on: a big poster of the post/reel that PLAYS INLINE (video source
// fetched on demand) or opens a photo lightbox — so the agent sees the reel and
// responds without ever leaving for Facebook.
function CommentContextCard({
    ctx,
    isInbound,
    channel,
}: {
    ctx: {
        post_id?: string;
        title?: string;
        permalink?: string;
        thumb?: string;
        media_type?: string;
        has_video?: boolean;
    };
    isInbound: boolean;
    // The post lives on the channel that owns the comment — Instagram media and
    // Facebook posts are read differently, so playback needs to say which.
    channel?: string;
}) {
    const title = (ctx.title || "").trim() || "a post";
    const permalink = ctx.permalink || "";
    const thumb = ctx.thumb || "";
    const postId = ctx.post_id || "";
    // Unknown media_type (old rows) → still try to play; the endpoint 404s for a photo.
    const maybeVideo = ctx.has_video === true || ctx.media_type === "video" || ctx.media_type === undefined;

    const [videoUrl, setVideoUrl] = React.useState<string | null>(null);
    const [lightbox, setLightbox] = React.useState<{ src: string; kind: "image" | "video" } | null>(null);
    const [loading, setLoading] = React.useState(false);
    const [thumbOk, setThumbOk] = React.useState(true);

    const openMedia = async () => {
        if (videoUrl || loading) return;
        if (postId && maybeVideo) {
            setLoading(true);
            try {
                const { video_url } = await conversationsApi.postVideo(postId, channel);
                setLoading(false);
                if (video_url) {
                    setVideoUrl(video_url);
                    return;
                }
            } catch {
                setLoading(false); // not a video → fall through to the photo lightbox
            }
        }
        if (thumb) setLightbox({ src: thumb, kind: "image" });
        else if (permalink) window.open(permalink, "_blank");
    };

    const showPreview = thumb && thumbOk;

    return (
        <div
            className={[
                "rounded-lg p-2",
                isInbound ? "bg-[#f0f4ec] border border-[#dde8d5]" : "bg-white/15 border border-white/20",
            ].join(" ")}
        >
            <div
                className={[
                    "text-[9px] font-semibold uppercase tracking-wide leading-none mb-1",
                    isInbound ? "text-[#699a32]" : "text-white/70",
                ].join(" ")}
            >
                Commented on your post
            </div>
            <div
                className={[
                    "text-[11px] leading-snug line-clamp-2 mb-1.5",
                    isInbound ? "text-[#3a5c28]" : "text-white/90",
                ].join(" ")}
                title={title}
            >
                {title}
            </div>

            {videoUrl ? (
                <video src={videoUrl} controls autoPlay className="w-full max-w-[260px] rounded-lg border border-black/10" />
            ) : showPreview ? (
                <button
                    onClick={openMedia}
                    className="relative block w-full max-w-[260px] rounded-lg overflow-hidden group"
                    aria-label={maybeVideo ? "Play reel" : "View post"}
                >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                        src={thumb}
                        alt=""
                        className="w-full aspect-video object-cover"
                        onError={() => setThumbOk(false)}
                    />
                    <span className="absolute inset-0 flex items-center justify-center bg-black/20 group-hover:bg-black/30 transition-colors">
                        <span className="w-10 h-10 rounded-full bg-white/90 flex items-center justify-center shadow">
                            {loading ? (
                                <span className="w-4 h-4 border-2 border-[#427425] border-t-transparent rounded-full animate-spin" />
                            ) : maybeVideo ? (
                                // play triangle
                                <svg className="w-5 h-5 text-[#1c2917] ml-0.5" viewBox="0 0 24 24" fill="currentColor">
                                    <path d="M8 5v14l11-7z" />
                                </svg>
                            ) : (
                                // expand
                                <svg className="w-4 h-4 text-[#1c2917]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                        d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                                </svg>
                            )}
                        </span>
                    </span>
                </button>
            ) : null}

            {permalink && (
                <a
                    href={permalink}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={[
                        "inline-flex items-center gap-1 mt-1.5 text-[10px] font-medium",
                        isInbound ? "text-[#699a32] hover:text-[#427425]" : "text-white/70 hover:text-white",
                    ].join(" ")}
                >
                    View on Facebook
                    <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M10 6H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4M14 4h6m0 0v6m0-6L10 14" />
                    </svg>
                </a>
            )}

            {lightbox && (
                <Lightbox src={lightbox.src} kind={lightbox.kind} onClose={() => setLightbox(null)} />
            )}
        </div>
    );
}

// ── ImageBubble ───────────────────────────────────────────────────────────────
// Renders an inbound customer image with:
//   - Clickable thumbnail (opens full-size in new tab)
//   - Collapsible "Image analysis" toggle — GPT-4o description stored in
//     msg.media_caption, shown exactly like the audio transcript toggle
//   - Customer caption text (msg.text) below the image, if provided
// ── Unrecoverable / expired media placeholder ────────────────────────────────
// Meta serves inbound attachments as signed CDN links that expire, so an older
// photo can silently render as an empty bubble — the operator is left asking
// "what did they even send?". Show it plainly, and offer one click to fetch the
// original back from Meta.
function MediaFallback({
    kind,
    messageId,
    isInbound,
    onRecovered,
}: {
    kind: "image" | "video";
    messageId?: string;
    isInbound: boolean;
    onRecovered: (url: string) => void;
}) {
    const [state, setState] = React.useState<"idle" | "loading" | "gone">("idle");
    const label = kind === "video" ? "Video" : "Photo";

    const recover = async () => {
        if (!messageId) return;
        setState("loading");
        try {
            const res = await conversationsApi.recoverMedia(messageId);
            if (res?.media_url) onRecovered(res.media_url);
            else setState("gone");
        } catch {
            setState("gone");
        }
    };

    return (
        <div className={[
            "flex flex-col gap-1 rounded-xl border border-dashed px-3 py-3 w-56",
            isInbound ? "border-black/15 bg-black/[0.03]" : "border-white/30 bg-white/10",
        ].join(" ")}>
            <span className="text-xs font-medium">
                {kind === "video" ? "🎬" : "📷"} {label} sent
            </span>
            <span className={["text-[11px] leading-snug",
                isInbound ? "text-black/50" : "text-white/70"].join(" ")}>
                {state === "gone"
                    ? "Meta no longer has this file — ask the customer to resend."
                    : "Preview link expired."}
            </span>
            {messageId && state !== "gone" && (
                <button
                    type="button"
                    onClick={recover}
                    disabled={state === "loading"}
                    className={[
                        "mt-0.5 w-fit rounded-full px-2 py-0.5 text-[10px] font-medium",
                        isInbound
                            ? "bg-[#f0f9e8] text-[#427425] hover:bg-[#e2f2d3]"
                            : "bg-white/20 text-white hover:bg-white/30",
                        state === "loading" ? "opacity-60" : "",
                    ].join(" ")}
                >
                    {state === "loading" ? "Fetching…" : "Recover from Meta"}
                </button>
            )}
        </div>
    );
}

// ── Messaging-window strip ───────────────────────────────────────────────────
// Meta and WhatsApp both shut free-form replies 24h after the customer's last
// message. Nothing used to say so, so a carefully typed reply was refused only
// at the moment of sending. This states the position up front — and, on a Meta
// DM, that a human still has seven days.
function WindowStrip({ win }: {
    win: { mode: string; expires_at?: string | null;
           human_agent_until?: string | null; reason?: string };
}) {
    // `now` lives in state, ticking each minute: reading the clock during render
    // is impure, and a countdown that never counts down is worse than no
    // countdown — an agent watching the last hour needs it to move.
    const [now, setNow] = React.useState(() => Date.now());
    React.useEffect(() => {
        const t = setInterval(() => setNow(Date.now()), 60_000);
        return () => clearInterval(t);
    }, []);

    const left = (iso?: string | null) => {
        if (!iso) return "";
        const ms = new Date(iso).getTime() - now;
        if (ms <= 0) return "";
        const h = Math.floor(ms / 3600000);
        const m = Math.floor((ms % 3600000) / 60000);
        return h >= 24 ? `${Math.floor(h / 24)}d ${h % 24}h` : h > 0 ? `${h}h ${m}m` : `${m}m`;
    };

    const look = {
        open:        { bg: "#f0f9e8", bd: "#d6e9c2", fg: "#427425", icon: "🟢" },
        human_agent: { bg: "#fff7ed", bd: "#fed7aa", fg: "#b45309", icon: "🟠" },
        closed:      { bg: "#fef2f2", bd: "#fecaca", fg: "#b91c1c", icon: "🔴" },
    }[win.mode] ?? { bg: "#f5f6f3", bd: "#e8ebe3", fg: "#6b7e64", icon: "•" };

    const text =
        win.mode === "open"
            ? `Reply window open — ${left(win.expires_at)} left`
            : win.mode === "human_agent"
              ? `24h window closed — you can still reply as a human agent for ${left(win.human_agent_until)}. Neema cannot.`
              : win.reason ||
                "Messaging window closed — only an approved template can reach them now.";

    return (
        <div className="mb-2 px-3 py-1.5 rounded-lg flex items-center gap-2 text-[11px] font-medium"
             style={{ backgroundColor: look.bg, border: `1px solid ${look.bd}`, color: look.fg }}>
            <span aria-hidden>{look.icon}</span>
            <span className="leading-snug">{text}</span>
        </div>
    );
}

function VideoBubble({
    src, caption, isInbound, messageId,
}: {
    src: string;
    caption: string | null;
    isInbound: boolean;
    messageId?: string;
}) {
    const [broken, setBroken] = React.useState(false);
    const [url, setUrl] = React.useState(src);
    React.useEffect(() => { setUrl(src); setBroken(false); }, [src]);

    return (
        <div className="space-y-1">
            {broken ? (
                <MediaFallback
                    kind="video"
                    messageId={messageId}
                    isInbound={isInbound}
                    onRecovered={(u) => { setUrl(u); setBroken(false); }}
                />
            ) : (
                <video
                    src={url}
                    controls
                    onError={() => setBroken(true)}
                    className="max-w-full rounded-xl border border-black/10"
                    style={{ maxHeight: 200 }}
                />
            )}
            {caption && (
                <p className="text-xs px-1 leading-relaxed whitespace-pre-wrap">
                    {formatWa(caption)}
                </p>
            )}
        </div>
    );
}

function ImageBubble({
    src,
    analysis,
    caption,
    isInbound,
    messageId,
}: {
    src: string;
    analysis: string | null;
    caption: string | null;
    isInbound: boolean;
    messageId?: string;
}) {
    const [open, setOpen] = React.useState(false);
    const [zoom, setZoom] = React.useState(false);
    const [broken, setBroken] = React.useState(false);
    const [url, setUrl] = React.useState(src);
    const hasAnalysis = !!analysis;

    // A new src (poll refresh, or a background re-host completing) gets a fresh
    // chance to load — never stay stuck on a stale failure.
    React.useEffect(() => { setUrl(src); setBroken(false); }, [src]);

    return (
        <div className="flex flex-col gap-1.5">
            {/* Click to view large IN-APP (lightbox) — no leaving the inbox */}
            {broken ? (
                <MediaFallback
                    kind="image"
                    messageId={messageId}
                    isInbound={isInbound}
                    onRecovered={(u) => { setUrl(u); setBroken(false); }}
                />
            ) : (
                <button type="button" onClick={() => setZoom(true)} className="block">
                    <img
                        src={url}
                        alt={caption || "image"}
                        onError={() => setBroken(true)}
                        className="max-w-full rounded-xl border border-black/10 object-cover cursor-zoom-in"
                        style={{ maxHeight: 240 }}
                    />
                </button>
            )}
            {zoom && !broken && <Lightbox src={url} kind="image" onClose={() => setZoom(false)} />}

            {/* Analysis toggle — same pill style as audio transcript toggle */}
            {hasAnalysis && (
                <button
                    onClick={() => setOpen((o) => !o)}
                    className={[
                        "flex items-center gap-1.5 text-[10px] font-medium",
                        "transition-colors w-fit rounded-full px-2 py-0.5",
                        isInbound
                            ? "text-[#699a32] hover:text-[#427425] bg-[#f0f9e8]"
                            : "text-white/70 hover:text-white bg-white/15",
                    ].join(" ")}
                >
                    {/* magnifier icon */}
                    <svg className="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
                    </svg>
                    {open ? "Hide image analysis" : "Show image analysis"}
                    <span style={{ display: "inline-block", transform: open ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.15s" }}>▾</span>
                </button>
            )}

            {/* GPT-4o analysis text (collapsible) */}
            {open && analysis && (
                <p className={[
                    "text-[11px] leading-relaxed px-1 whitespace-pre-wrap",
                    isInbound ? "italic text-[#3a5c28]/70" : "text-white/80",
                ].join(" ")}>
                    {analysis}
                </p>
            )}

            {/* Customer's own caption text, rendered below the image */}
            {caption && !caption.startsWith("[") && (
                <p className={[
                    "text-xs px-1 leading-relaxed",
                    isInbound ? "text-[#1a2e0f]" : "text-white/90",
                ].join(" ")}>
                    {caption}
                </p>
            )}
        </div>
    );
}

type MobilePanel = "list" | "thread";

interface ConversationsViewProps extends SharedViewProps {
    conversations: Conversation[];
    setConversations: React.Dispatch<React.SetStateAction<Conversation[]>>;
    messages: MessagesMap;
    setMessages: React.Dispatch<React.SetStateAction<MessagesMap>>;
    agents: Agent[];
    orders?: Order[];
    refetchConversations?: () => void;
    // A wa_id/external_id another view (Calls) asked us to open in-app.
    openConvKey?: string | null;
    onConsumeOpenConvKey?: () => void;
    // True once the conversations list is fresh from the server (not a cached
    // snapshot) — gates the "no conversation yet" verdict on deep links.
    freshLoaded?: boolean;
}

const CHANNEL_TABS: { id: "all" | Channel; label: string; short: string }[] = [
    { id: "all", label: "All", short: "All" },
    { id: "whatsapp", label: "WhatsApp", short: "WA" },
    { id: "facebook", label: "Facebook", short: "FB" },
    { id: "messenger", label: "Messenger", short: "MSG" },
    { id: "instagram", label: "Instagram", short: "IG" },
    // Email + SMS hidden for now — no traffic on those channels yet.
];

// Accent for the "All" tab (gold) — channels use their own brand colour.
const ALL_TAB_ACCENT = "#f59e0b";
// Active-row accent (Figma gold).
const ROW_ACCENT = "#f59e0b";

// Desktop width of the conversation list column: an inch wider than the old
// 340px (1 CSS inch = 96px), so a row's chips sit on one line. Clamped rather
// than fixed — a narrow laptop keeps the old 340 instead of starving the
// thread panel, and only roomy screens pay out the full extra inch.
const LIST_WIDTH = "clamp(340px, 38vw, 436px)";
// Activity-log panel: an inch wider than the old 196px, so an event line like
// "Moses Mwicigi intercepted the conversation" stops wrapping into a column of
// single words. Clamped for the same reason as LIST_WIDTH — it sits alongside
// the list, the thread AND the CRM sidebar, so a narrow screen keeps the 196.
const ACTIVITY_WIDTH = "clamp(196px, 16vw, 292px)";
// Short channel labels for the conversation-row pill (Figma: WA / FB / IG).
const CH_SHORT: Record<Channel, string> = {
    whatsapp: "WA",
    messenger: "MSG",
    facebook: "FB",
    instagram: "IG",
    tiktok: "TT",
    email: "Email",
    sms: "SMS",
};

// Chip order for a unified (multi-channel) customer row — WhatsApp first (it can
// transact), then the social channels.
const CHAN_ORDER: Channel[] = ["whatsapp", "messenger", "facebook", "instagram", "tiktok", "email", "sms"];
const SparkleIcon = () => (
    <svg viewBox="0 0 24 24" fill="currentColor" className="w-3.5 h-3.5">
        <path d="M12 2l1.9 5.6L19.5 9l-5.6 1.9L12 16.5 10.1 10.9 4.5 9l5.6-1.4L12 2zm6.5 11l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9.9-2.6z" />
    </svg>
);

export function ConversationsView({
    conversations,
    setConversations,
    messages,
    setMessages,
    agents,
    orders = [],
    onToast,
    isMobile,
    refetchConversations,
    openConvKey,
    onConsumeOpenConvKey,
    freshLoaded,
}: ConversationsViewProps): React.ReactElement {
    const [activeConvId, setActiveConvId] = useState<string>("");
    const [mobilePanel, setMobilePanel] = useState<MobilePanel>("list");
    const [channelTab, setChannelTab] = useState<"all" | Channel>("all");
    const [tagFilter, setTagFilter] = useState<string>("all");
    const [interceptFilter, setInterceptFilter] = useState<
        "all" | "human" | "ai" | "paused"
    >("all");
    // Bulk selection in the conversation list (see "Bulk selection" below).
    const [selectMode, setSelectMode] = useState(false);
    const [selected, setSelected] = useState<Set<string>>(() => new Set());
    const [bulkBusy, setBulkBusy] = useState(false);
    const anchorRow = useRef<number | null>(null);   // shift-click range anchor
    const longPressed = useRef(false);               // suppress the click it fired from
    // Held in a ref, not a per-row local: the list re-renders on every poll, and
    // a timer captured in a closure that a re-render replaced can never be
    // cleared — the hold would fire after the finger already lifted.
    const pressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

    const [readFilter, setReadFilter] = useState<"all" | "unread" | "read" | "human" | "yours">(
        "all",
    );
    const [searchQ, setSearchQ] = useState<string>("");
    const [replyText, setReplyText] = useState<string>("");
    // The message the agent is replying to. Same-channel → a native threaded reply
    // (reply_to id, shown as a quoted strip on the bubble; WhatsApp delivers it as a
    // native reply too). A quote grabbed from ANOTHER channel keeps the old
    // prepend-as-text behaviour. View-level so it survives switching channel chips.
    const [quoted, setQuoted] = useState<{ msgId?: string; sender?: string; text: string;
        channel: string; mediaUrl?: string; mediaType?: string } | null>(null);
    const [draftVisible, setDraftVisible] = useState<boolean>(false);
    const [draftExpanded, setDraftExpanded] = useState<boolean>(false);
    const [draftText, setDraftText] = useState<string>("");
    const [draftEditing, setDraftEditing] = useState<boolean>(false);
    const [generatingDraft, setGeneratingDraft] = useState<boolean>(false);
    const [transferModal, setTransferModal] = useState<boolean>(false);
    const [noteModal, setNoteModal] = useState<boolean>(false);
    const [noteText, setNoteText] = useState<string>("");
    const [showFilters, setShowFilters] = useState<boolean>(false);
    const [threadLoading, setThreadLoading] = useState(false);
    const [sending, setSending] = useState(false);
    // Meta/WhatsApp messaging window for the open thread — fetched per thread so
    // the composer can say what will happen BEFORE a reply is typed.
    const [window24, setWindow24] = useState<{
        mode: "open" | "human_agent" | "closed" | "n/a";
        expires_at?: string | null;
        human_agent_until?: string | null;
        reason?: string;
    } | null>(null);
    const [crmOpen, setCrmOpen] = useState<boolean>(true);
    const [activityLogOpen, setActivityLogOpen] = useState<boolean>(false);
    // The person-scoped journey ledger (pickups, check-ins, deals, orders,
    // calls) — fetched per thread, refreshed while the panel is open.
    const [activityEvents, setActivityEvents] = useState<ApiActivityEvent[]>([]);
    const [clearConfirm, setClearConfirm] = useState(false);
    const [clearing, setClearing] = useState(false);
    const [mobileCrmOpen, setMobileCrmOpen] = useState(false);
    // Tracks unread count at the moment a thread is opened — used to place the "N new" divider
    const [unreadSnapshot, setUnreadSnapshot] = useState<
        Record<string, number>
    >({});

    const { data: session } = useSession();
    const currentAgentId = (session as any)?.user?.id as string | undefined;

    // ── Fetch current agent profile to get role/permissions ──────────────────
    const [currentAgent, setCurrentAgent] = useState<{
        role: string;
        is_superuser: boolean;
    } | null>(null);

    useEffect(() => {
        if (!currentAgentId) return;

        // Retry up to 3 times with backoff — token may not be on window yet
        // on the very first render if page.tsx hasn't flushed it
        let attempts = 0;
        const fetchMe = () => {
            attempts++;
            profileApi
                .me()
                .then((data) => {
                    setCurrentAgent({
                        role: data.role,
                        is_superuser: data.is_superuser,
                    });
                })
                .catch((e) => {
                    // Retry on 401 up to 3 times with increasing delay
                    if (attempts < 3 && String(e).includes("401")) {
                        setTimeout(fetchMe, attempts * 400);
                    } else {
                        console.error("profileApi.me() error:", e);
                    }
                });
        };

        fetchMe();
    }, [currentAgentId]);

    const currentRole = currentAgent?.role;
    const isSuperuser = currentAgent?.is_superuser ?? false;
    const isAdminOrSuper = isSuperuser || currentRole === "admin";
    const canHandleConversations = isAdminOrSuper || currentRole === "agent";

    // ── Media attachment state (multi-select) ─────────────────────────────────
    // Each picked file carries its own object-URL preview AND its own caption —
    // like WhatsApp: attach several, write a caption under each (or leave blank),
    // then send them all in one go.
    type MediaItem = { id: string; file: File; previewUrl: string | null; caption: string };
    const [mediaItems, setMediaItems] = useState<MediaItem[]>([]);
    const [uploadingMedia, setUploadingMedia] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const prevMessageCount = useRef<number>(0);

    // ── Load messages for a conversation (always fetches fresh) ───────────────
    const loadMessages = useCallback(
        async (convId: string, silent = false) => {
            if (!convId) return;
            if (!silent) setThreadLoading(true);
            try {
                const msgs = await conversationsApi.messages(convId);
                setMessages((m) => ({ ...m, [convId]: msgs }));
            } catch {
                if (!silent) onToast("Failed to load messages", "error");
            } finally {
                if (!silent) setThreadLoading(false);
            }
        },
        [setMessages, onToast],
    );

    // ── Auto-select & load the first conversation on initial data load ────────
    useEffect(() => {
        if (conversations.length > 0 && !activeConvId) {
            const firstId = conversations[0].id;
            setActiveConvId(firstId);
            loadMessages(firstId);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [conversations.length > 0, activeConvId]);

    const activeConv = conversations.find((c) => c.id === activeConvId);
    const activeMessages: Message[] = messages[activeConvId] ?? [];
    // Memoized: this sort ran inline in the thread JSX on EVERY render of the
    // view (each keystroke, poll, ws event), allocating Dates per comparison.
    const sortedActiveMessages = useMemo(() => [...activeMessages].sort((a, b) => {
        const tA = new Date(a.created_at ?? 0).getTime() +
            (a.type === "system_event" && (a.event_kind === "escalated" || (a.event_kind === "intercept" && !a.agent_name)) ? 1 : 0);
        const tB = new Date(b.created_at ?? 0).getTime() +
            (b.type === "system_event" && (b.event_kind === "escalated" || (b.event_kind === "intercept" && !b.agent_name)) ? 1 : 0);
        return tA - tB;
    }), [activeMessages]);

    // WhatsApp-style albums: runs of ≥2 consecutive image messages from the same
    // side collapse into one collage bubble (the first message renders the grid;
    // the rest render nothing). Clicking opens the sequential viewer.
    const albumOf = useMemo(() => {
        const map = new Map<string, { lead: boolean; items: Message[] }>();
        let run: Message[] = [];
        const flush = () => {
            if (run.length >= 2) {
                const items = run;
                items.forEach((m, i) => map.set(m.id, { lead: i === 0, items }));
            }
            run = [];
        };
        for (const m of sortedActiveMessages) {
            const isImg = m.type !== "system_event" && !m.isNote &&
                (m as any).media_type === "image" && (m as any).media_url;
            const prevM = run[run.length - 1];
            if (isImg && (!prevM || (prevM.direction === m.direction && prevM.sender === m.sender))) {
                run.push(m);
            } else {
                flush();
                if (isImg) run.push(m);
            }
        }
        flush();
        return map;
    }, [sortedActiveMessages]);
    const [albumViewer, setAlbumViewer] = useState<{ items: AlbumItem[]; start: number } | null>(null);
    const albumItemsOf = (msgs: Message[]): AlbumItem[] => msgs.map((m) => ({
        src: (m as any).media_url as string,
        caption: (m.text || "").trim() && !(m.text || "").trim().startsWith("[")
            ? (m.text || "").trim() : null,
    }));

    // Jump to the same person's conversation on another channel (clicking a
    // linked identity in the customer panel). WhatsApp real numbers open wa.me in
    // the sidebar itself; everything else lands here and we switch the thread.
    // Open a conversation another view requested (Calls → "message in Neema").
    // Match by wa_id/external_id, preferring a WhatsApp thread for a caller.
    useEffect(() => {
        if (!openConvKey) return;
        // A deep link (hub → Neema) can land before the inbox has loaded —
        // don't consume the key against an empty list.
        if (conversations.length === 0) return;
        const key = openConvKey.replace(/^\+/, "");
        const matches = conversations.filter(
            (c) => c.wa_id === key || c.external_id === key || c.wa_id === openConvKey,
        );
        const conv = matches.find((c) => c.channel === "whatsapp") ?? matches[0];
        // Full open semantics (messages load, unread clears) — selecting the id
        // alone leaves the thread pane empty until the 20s poll catches up.
        if (conv) handleSelectConv(conv.id);
        // A cached snapshot may simply not contain a brand-new conversation —
        // don't declare "no conversation" until the fresh list has arrived.
        else if (!freshLoaded) return;
        else onToast?.("No conversation yet — they haven't messaged. Use Invite to WhatsApp.", "warning");
        onConsumeOpenConvKey?.();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [openConvKey, conversations, freshLoaded, onConsumeOpenConvKey, onToast]);

    const openIdentityConversation = (channel: string, externalId: string) => {
        const conv = conversations.find(
            (c) =>
                c.channel === channel &&
                (c.external_id === externalId || c.wa_id === externalId),
        );
        if (conv) handleSelectConv(conv.id);
        else onToast?.("No conversation on that channel yet.", "warning");
    };

    // ── Ownership helpers (depend on activeConv) ──────────────────────────────
    // isOwner: current agent is the one who intercepted this conversation
    const isOwner =
        !!activeConv && activeConv.assigned_agent_id === currentAgentId;

    // convOwnedByOther: conv is human-intercepted by a different agent
    const convOwnedByOther =
        !!activeConv &&
        activeConv.intercept_mode === "human" &&
        !!activeConv.assigned_agent_id &&
        activeConv.assigned_agent_id !== currentAgentId;

    // canActOnThisConv: can perform Pause/Resume/Transfer.
    // True when agent has permissions AND (owns the conv, OR is admin/super,
    // OR the conv isn't currently human-intercepted by someone else).
    const canActOnThisConv =
        canHandleConversations &&
        (isOwner || isAdminOrSuper || activeConv?.intercept_mode !== "human");

    // ── Scroll to bottom only when new messages arrive ────────────────────────
    useEffect(() => {
        const count = activeMessages.length;
        if (count > prevMessageCount.current) {
            messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
        }
        prevMessageCount.current = count;
    }, [activeMessages.length]);

    useEffect(() => {
        prevMessageCount.current = 0;
        setTimeout(() => {
            messagesEndRef.current?.scrollIntoView({ behavior: "instant" });
        }, 50);
    }, [activeConvId]);

    // ── Poll active thread as a WebSocket fallback (WS is primary; skip
    // ticks while the tab is hidden) ──────────────────────────────────────────
    useEffect(() => {
        if (!activeConvId) return;
        const timer = setInterval(() => {
            if (document.visibilityState === "hidden") return;
            loadMessages(activeConvId, true);
        }, 20000);
        return () => clearInterval(timer);
    }, [activeConvId, loadMessages]);

    // ── Journey ledger for the Activity Log panel ─────────────────────────────
    useEffect(() => {
        if (!activeConvId) { setActivityEvents([]); return; }
        let stale = false;
        const load = () =>
            conversationsApi.activity(activeConvId)
                .then((r) => { if (!stale) setActivityEvents(r.events); })
                .catch(() => { if (!stale) setActivityEvents([]); });
        load();
        // Slow refresh while the panel is open — new check-ins/orders surface
        // without a reopen; WS message traffic doesn't cover these.
        const timer = activityLogOpen
            ? setInterval(() => {
                  if (document.visibilityState !== "hidden") load();
              }, 60000)
            : null;
        return () => { stale = true; if (timer) clearInterval(timer); };
    }, [activeConvId, activityLogOpen]);

    // ── Messaging window for the open thread ──────────────────────────────────
    // Refreshed on open and on every new message (an inbound reopens it).
    useEffect(() => {
        if (!activeConvId) { setWindow24(null); return; }
        let cancelled = false;
        conversationsApi.window(activeConvId)
            .then((w) => { if (!cancelled) setWindow24(w); })
            .catch(() => { if (!cancelled) setWindow24(null); });
        return () => { cancelled = true; };
    }, [activeConvId, activeMessages.length]);

    // ── Reset draft when switching conversations ──────────────────────────────
    useEffect(() => {
        setDraftVisible(false);
        setDraftExpanded(false);
        setDraftText("");
        setDraftEditing(false);
        if (!activeConvId) return;
        const conv = conversations.find((c) => c.id === activeConvId);
        if (conv?.intercept_mode === "human") {
            conversationsApi
                .latestDraft(activeConvId)
                .then((res) => {
                    if (res.draft) {
                        setDraftText(res.draft);
                        setDraftVisible(true);
                        // Don't auto-expand — show pill only
                    }
                })
                .catch(() => {});
        }
    }, [activeConvId]);

    // ── WebSocket: live events for the active conversation ────────────────────
    useConversationEvents(activeConvId, (event) => {
        if (
            event.type === "ai_draft_ready" &&
            event.conversationId === activeConvId
        ) {
            setDraftText(event.draft ?? "");
            setDraftVisible(true);
            setDraftExpanded(false); // notify but don't auto-open
            setDraftEditing(false);
        }
        if (
            event.type === "new_message" &&
            event.conversationId === activeConvId
        ) {
            const msg: Message = {
                id: event.id ?? crypto.randomUUID(),
                type: "message",
                direction: event.direction ?? "outbound",
                sender: event.sender ?? "ai",
                text: event.text,
                created_at: event.created_at ?? new Date().toISOString(),
                // Media fields from WebSocket broadcast
                media_type: event.mediaType ?? undefined,
                media_id: event.mediaId ?? undefined,
                media_url: event.mediaUrl ?? undefined,
                media_caption: event.mediaCaption ?? undefined,
                mime_type: event.mimeType ?? undefined,
                filename: event.filename ?? undefined,
            };
            setMessages((m) => {
                const existing = m[activeConvId] ?? [];
                // Primary dedup: exact DB id match
                if (existing.some((x) => x.id === msg.id)) return m;
                // Secondary dedup: audio replies broadcast before the DB row is
                // committed get a crypto.randomUUID() id that never matches the
                // real DB id on the next poll. Guard with media_url + direction
                // within a 15-second window.
                if (msg.media_url) {
                    const tMs = new Date(msg.created_at).getTime();
                    if (
                        existing.some(
                            (x) =>
                                (x as any).media_url === msg.media_url &&
                                x.direction === msg.direction &&
                                Math.abs(new Date(x.created_at).getTime() - tMs) < 15_000,
                        )
                    )
                        return m;
                }
                return { ...m, [activeConvId]: [...existing, msg] };
            });
        }
        if (
            event.type === "intercept_changed" &&
            event.conversationId === activeConvId
        ) {
            // Inject a live system-event bubble into the thread so agents
            // see mode changes (escalations, pickups, releases, transfers)
            // without waiting for the next full thread reload.
            const sysEvt = buildSystemEventFromWs(event);
            if (sysEvt) {
                setMessages((m) => {
                    const existing = m[activeConvId] ?? [];
                    // Avoid injecting a duplicate live pill:
                    // - If a live-evt entry with the same kind already exists
                    //   (WS fired twice), skip it.
                    // - DB-loaded events have ids like "evt-<uuid>" and are
                    //   kept; they replace the temporary live-evt on next poll.
                    const alreadyLive = existing.some(
                        (x) =>
                            x.id?.startsWith("live-evt-") &&
                            x.event_kind === sysEvt.event_kind,
                    );
                    if (alreadyLive) return m;
                    // Drop any previous live-evt for this kind so the new one
                    // (with the latest reason / agent name) takes its place.
                    const filtered = existing.filter(
                        (x) =>
                            !(x.id?.startsWith("live-evt-") &&
                              x.event_kind === sysEvt.event_kind),
                    );
                    return { ...m, [activeConvId]: [...filtered, sysEvt] };
                });
            }
        }
        if (
            event.type === "history_cleared" &&
            event.conversationId === activeConvId
        ) {
            setMessages((m) => ({ ...m, [activeConvId]: [] }));
            onToast(`History cleared by ${event.clearedBy}`);
        }
    });

    const handleSelectConv = (id: string) => {
        // Snapshot the unread count before clearing it so we can show the divider
        const conv = conversations.find((c) => c.id === id);
        if (conv && conv.unread > 0) {
            setUnreadSnapshot((prev) => ({ ...prev, [id]: conv.unread }));
            // Optimistically clear the unread badge locally
            setConversations((prev) =>
                prev.map((c) => (c.id === id ? { ...c, unread: 0 } : c)),
            );
        }
        setActiveConvId(id);
        loadMessages(id);
        if (isMobile) setMobilePanel("thread");
    };

    // ── Actions ───────────────────────────────────────────────────────────────

    const intercept = async (convId: string) => {
        try {
            await conversationsApi.intercept(convId);
            refetchConversations?.();
            onToast("Conversation claimed — you now control replies");
        } catch (err: any) {
            if (err?.message?.includes("409")) {
                onToast("Already claimed by another agent", "error");
            } else {
                onToast("Failed to claim conversation", "error");
            }
        }
    };

    const release = async (convId: string) => {
        try {
            await conversationsApi.release(convId);
            refetchConversations?.();
            onToast("Conversation released back to AI");
        } catch {
            onToast("Failed to release", "error");
        }
    };

    const transfer = async (agentId: string) => {
        if (!activeConvId) return;
        try {
            await conversationsApi.transfer(activeConvId, agentId);
            setTransferModal(false);
            refetchConversations?.();
            const agent = agents.find((a) => a.id === agentId);
            onToast(`Transferred to ${agent?.name ?? "agent"}`);
        } catch {
            onToast("Failed to transfer", "error");
        }
    };

    const sendReply = async () => {
        if (!replyText.trim() || !activeConvId) return;
        setSending(true);
        // Prepend the cross-channel quote so the customer sees what we're answering.
        // Same-channel reply → a native threaded reply (reply_to id). A quote from
        // ANOTHER channel can't be threaded, so it rides as a text prefix (as before).
        const sameChannel = !!quoted && quoted.channel === (activeConv?.channel || "whatsapp");
        const replyToId = sameChannel ? quoted?.msgId : undefined;
        const q = quoted && !sameChannel
            ? `↩ Re (${CHANNEL_CONFIG[quoted.channel as Channel]?.label ?? quoted.channel}): "${quoted.text.slice(0, 180)}"\n\n`
            : "";
        const text = q + replyText;
        try {
            const optimisticMsg: Message = {
                id: `optimistic-${Date.now()}`,
                direction: "outbound",
                sender: "human_agent",
                text,
                created_at: new Date().toISOString(),
                reply_to: replyToId && quoted
                    ? { id: replyToId, text: quoted.text, sender: quoted.sender ?? null,
                        media_type: quoted.mediaType ?? null, media_url: quoted.mediaUrl ?? null }
                    : null,
            };
            setMessages((m) => ({
                ...m,
                [activeConvId]: [...(m[activeConvId] ?? []), optimisticMsg],
            }));
            setReplyText("");
            setQuoted(null);
            await conversationsApi.sendReply(activeConvId, text, replyToId);
            const msgs = await conversationsApi.messages(activeConvId);
            setMessages((m) => ({ ...m, [activeConvId]: msgs }));
            refetchConversations?.();
        } catch {
            setMessages((m) => ({
                ...m,
                [activeConvId]: (m[activeConvId] ?? []).filter(
                    (msg) => !msg.id?.startsWith("optimistic-"),
                ),
            }));
            setReplyText(text);
            onToast("Failed to send message", "error");
        } finally {
            setSending(false);
        }
    };

    // Start replying to a specific message (from the Reply button or a swipe).
    // A pure image message (no text) is quotable too — like WhatsApp.
    const beginReplyTo = (msg: Message) => {
        const mediaUrl = (msg as any).media_url as string | undefined;
        const mediaType = (msg as any).media_type as string | undefined;
        if (!(msg.text || "").trim() && !mediaUrl) return;
        setQuoted({
            msgId: msg.id,
            sender: msg.sender,
            text: (msg.text || "").replace(/^\[comment\]\s*/, "").slice(0, 300),
            channel: activeConv?.channel || "whatsapp",
            mediaUrl: mediaType === "image" ? mediaUrl : undefined,
            mediaType,
        });
    };

    // Swipe a bubble left→right (like WhatsApp) to reply to it — touch devices.
    const swipeStart = useRef<{ x: number; y: number } | null>(null);
    const makeSwipeHandlers = (msg: Message) => ({
        onTouchStart: (e: React.TouchEvent) => {
            const t = e.touches[0];
            swipeStart.current = { x: t.clientX, y: t.clientY };
        },
        onTouchEnd: (e: React.TouchEvent) => {
            const s = swipeStart.current;
            swipeStart.current = null;
            if (!s) return;
            const t = e.changedTouches[0];
            const dx = t.clientX - s.x;
            const dy = t.clientY - s.y;
            if (dx > 55 && Math.abs(dy) < 40) beginReplyTo(msg);
        },
    });

    const approveDraft = async () => {
        if (!activeConvId) return;
        const textToSend = draftText;
        try {
            const optimisticMsg: Message = {
                id: `optimistic-${Date.now()}`,
                direction: "outbound",
                sender: "ai",
                text: textToSend,
                created_at: new Date().toISOString(),
            };
            setMessages((m) => ({
                ...m,
                [activeConvId]: [...(m[activeConvId] ?? []), optimisticMsg],
            }));
            setDraftVisible(false);
            setDraftExpanded(false);
            setDraftText("");
            setDraftEditing(false);
            await conversationsApi.approveDraft(
                activeConvId,
                textToSend || undefined,
            );
            const msgs = await conversationsApi.messages(activeConvId);
            setMessages((m) => ({ ...m, [activeConvId]: msgs }));
            refetchConversations?.();
            onToast("AI draft approved & sent");
        } catch {
            setMessages((m) => ({
                ...m,
                [activeConvId]: (m[activeConvId] ?? []).filter(
                    (msg) => !msg.id?.startsWith("optimistic-"),
                ),
            }));
            setDraftVisible(true);
            setDraftExpanded(true);
            setDraftText(textToSend);
            onToast("Failed to approve draft", "error");
        }
    };

    const generateDraft = async () => {
        if (!activeConvId) return;
        setGeneratingDraft(true);
        try {
            const res = await conversationsApi.generateDraft(activeConvId);
            if (res.draft) {
                setDraftText(res.draft);
                setDraftVisible(true);
                setDraftExpanded(true); // agent requested it — open immediately
                setDraftEditing(false);
                onToast("Draft generated");
            }
        } catch {
            onToast("Failed to generate draft", "error");
        } finally {
            setGeneratingDraft(false);
        }
    };

    const closeConv = async (convId: string) => {
        try {
            await conversationsApi.close(convId);
            refetchConversations?.();
            onToast("Conversation closed");
        } catch {
            onToast("Failed to close conversation", "error");
        }
    };

    // ── Media actions ─────────────────────────────────────────────────────────

    const ACCEPT_TYPES =
        "image/jpeg,image/png,image/webp,image/gif," +
        "application/pdf,application/msword," +
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document," +
        "application/vnd.ms-excel," +
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet," +
        "video/mp4,video/3gpp,video/quicktime,video/hevc,video/x-m4v,.mov,.hevc," +
        "audio/ogg,audio/aac,audio/mpeg";

    // Per-type ceilings enforced BEFORE upload. Images over the WhatsApp 5 MB
    // cap get compressed in-browser (below); videos are accepted up to 150 MB —
    // the server transcodes them to WhatsApp's 16 MB H.264 MP4 (like the
    // WhatsApp app itself does on send). Audio/documents match hard limits.
    const MB = 1024 * 1024;
    const MAX_IMAGE_BYTES = 5 * MB;      // WhatsApp image limit
    const MAX_VIDEO_BYTES = 150 * MB;    // raw phone clip — server transcodes down
    const MAX_AUDIO_BYTES = 16 * MB;     // WhatsApp audio limit
    const MAX_DOC_BYTES = 18 * MB;

    const isVideoFile = (f: File) =>
        f.type.startsWith("video/") || /\.(mov|hevc|mp4|m4v|3gp)$/i.test(f.name);

    const limitFor = (file: File): { bytes: number; label: string } => {
        if (file.type.startsWith("image/")) return { bytes: MAX_IMAGE_BYTES, label: "5 MB" };
        if (isVideoFile(file)) return { bytes: MAX_VIDEO_BYTES, label: "150 MB" };
        if (file.type.startsWith("audio/")) return { bytes: MAX_AUDIO_BYTES, label: "16 MB" };
        return { bytes: MAX_DOC_BYTES, label: "18 MB" };
    };

    // WhatsApp never rejects a normal photo — it downscales and re-encodes it.
    // Same here: an oversized image is resized to max 2048px on its long side
    // and saved as JPEG, stepping quality down until it fits the 5 MB Cloud API
    // limit. Animated GIFs can't be re-encoded on a canvas (they'd freeze), so
    // they keep the hard limit; so do videos/documents.
    const compressImage = async (file: File): Promise<File | null> => {
        try {
            const bitmap = await createImageBitmap(file);
            const MAX_SIDE = 2048;
            const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
            const w = Math.max(1, Math.round(bitmap.width * scale));
            const h = Math.max(1, Math.round(bitmap.height * scale));
            const canvas = document.createElement("canvas");
            canvas.width = w;
            canvas.height = h;
            const ctx = canvas.getContext("2d");
            if (!ctx) return null;
            ctx.drawImage(bitmap, 0, 0, w, h);
            bitmap.close?.();
            for (const q of [0.85, 0.7, 0.55, 0.4]) {
                const blob: Blob | null = await new Promise((r) => canvas.toBlob(r, "image/jpeg", q));
                if (blob && blob.size <= MAX_IMAGE_BYTES) {
                    const name = file.name.replace(/\.[^.]+$/, "") + ".jpg";
                    return new File([blob], name, { type: "image/jpeg" });
                }
            }
            return null;
        } catch {
            return null;
        }
    };

    const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const picked = Array.from(e.target.files ?? []);
        if (fileInputRef.current) fileInputRef.current.value = ""; // allow re-pick same file
        if (!picked.length) return;

        const accepted: MediaItem[] = [];
        for (let file of picked) {
            const { bytes, label } = limitFor(file);
            if (file.size > bytes) {
                const compressible = file.type.startsWith("image/") && file.type !== "image/gif";
                const smaller = compressible ? await compressImage(file) : null;
                if (!smaller) {
                    onToast(`${file.name} is too large (max ${label})`, "error");
                    continue;
                }
                file = smaller;              // silently fitted, like WhatsApp
            }
            accepted.push({
                id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`,
                file,
                previewUrl: file.type.startsWith("image/") ? URL.createObjectURL(file) : null,
                caption: "",
            });
        }
        if (accepted.length) setMediaItems((prev) => [...prev, ...accepted]);
    };

    const updateMediaCaption = (id: string, caption: string) => {
        setMediaItems((prev) => prev.map((it) => (it.id === id ? { ...it, caption } : it)));
    };

    const removeMediaItem = (id: string) => {
        setMediaItems((prev) => {
            const gone = prev.find((it) => it.id === id);
            if (gone?.previewUrl) URL.revokeObjectURL(gone.previewUrl);
            return prev.filter((it) => it.id !== id);
        });
    };

    const clearMediaAttachment = () => {
        setMediaItems((prev) => {
            prev.forEach((it) => it.previewUrl && URL.revokeObjectURL(it.previewUrl));
            return [];
        });
        if (fileInputRef.current) fileInputRef.current.value = "";
    };

    const sendMedia = async () => {
        if (!mediaItems.length || !activeConvId) return;
        setUploadingMedia(true);
        const sent: Message[] = [];
        let failed = 0;
        try {
            // Send sequentially; each file carries its OWN caption (or none).
            for (let i = 0; i < mediaItems.length; i++) {
                try {
                    const msg = await conversationsApi.uploadMedia(
                        activeConvId,
                        mediaItems[i].file,
                        mediaItems[i].caption.trim() || undefined,
                    );
                    sent.push(msg);
                } catch (err: any) {
                    failed++;
                    onToast(
                        `${mediaItems[i].file.name}: ${err?.message ?? "failed"}`,
                        "error",
                    );
                }
            }
            if (sent.length) {
                setMessages((m) => ({
                    ...m,
                    [activeConvId]: [...(m[activeConvId] ?? []), ...sent],
                }));
                clearMediaAttachment();
                refetchConversations?.();
                onToast(
                    failed
                        ? `Sent ${sent.length}, ${failed} failed`
                        : sent.length > 1
                          ? `${sent.length} files sent`
                          : "Media sent",
                    failed ? "error" : "success",
                );
            }
        } finally {
            setUploadingMedia(false);
        }
    };

    // ── Filters ───────────────────────────────────────────────────────────────

    // All derived list data is memoized: this component re-renders on every
    // keystroke in the reply box and every websocket event, and recomputing
    // these (especially the O(n log n) Date-allocating sort) inline made the
    // names list stutter while scrolling.
    const channelCounts = useMemo(() => CHANNEL_TABS.reduce<Record<string, number>>(
        (acc, tab) => {
            acc[tab.id] =
                tab.id === "all"
                    ? conversations
                          .filter((c) => c.unread > 0)
                          .reduce((s, c) => s + (c.unread ?? 0), 0)
                    : conversations
                          .filter((c) => c.channel === tab.id && c.unread > 0)
                          .reduce((s, c) => s + (c.unread ?? 0), 0);
            return acc;
        },
        {},
    ), [conversations]);

    // Collect all unique tags across all conversations for the tag filter UI
    const allTags = useMemo(() => Array.from(
        new Set(conversations.flatMap((c) => (c as any).tags ?? [])),
    ).sort() as string[], [conversations]);

    const unreadCount = useMemo(
        () => conversations.filter((c) => c.unread > 0).length, [conversations]);

    const filteredConvs = useMemo(() => conversations
        .filter((c) => {
            if (channelTab !== "all" && c.channel !== channelTab) return false;
            // Tag filter: only show conversations whose customer has the selected tag
            if (tagFilter !== "all") {
                const convTags: string[] = (c as any).tags ?? [];
                if (!convTags.includes(tagFilter)) return false;
            }
            if (
                interceptFilter !== "all" &&
                c.intercept_mode !== interceptFilter
            )
                return false;
            if (readFilter === "unread" && !(c.unread > 0)) return false;
            if (readFilter === "read" && c.unread > 0) return false;
            if (readFilter === "human" && c.intercept_mode !== "human") return false;
            // "Yours" — held by a human AND that human is me.
            if (readFilter === "yours" &&
                !(c.intercept_mode === "human" && c.assigned_agent_id === currentAgentId))
                return false;
            if (
                searchQ &&
                !c.name?.toLowerCase().includes(searchQ.toLowerCase()) &&
                !c.last_message?.toLowerCase().includes(searchQ.toLowerCase())
            )
                return false;
            return true;
        })
        .sort((a, b) => {
            // Sort by the most recent activity — inbound OR outbound — falling
            // back to created_at so brand-new conversations surface correctly.
            const aTime = a.last_message_at
                ? new Date(a.last_message_at).getTime()
                : a.created_at
                  ? new Date(a.created_at).getTime()
                  : 0;
            const bTime = b.last_message_at
                ? new Date(b.last_message_at).getTime()
                : b.created_at
                  ? new Date(b.created_at).getTime()
                  : 0;
            return bTime - aTime;
        }), [conversations, channelTab, tagFilter, interceptFilter, readFilter, searchQ,
             currentAgentId]);

    // ── Collapse siblings into one row per person ─────────────────────────────
    // Conversations sharing a person_id are the SAME customer across channels
    // (Doctors West on Facebook + Messenger + WhatsApp). filteredConvs is already
    // sorted newest-first, so the first occurrence of each person is the
    // representative row; the rest become channel chips on it. A conversation
    // with no person_id stands alone. On a specific channel tab there's nothing
    // to collapse, so grouping only changes the "All" view.
    const groupedConvs = useMemo(() => {
        const repByPerson = new Map<string, Conversation>();
        const siblings = new Map<string, Conversation[]>();
        const order: Conversation[] = [];
        for (const c of filteredConvs) {
            const pid = c.person_id;
            if (!pid) {
                order.push(c);
                siblings.set(c.id, [c]);
                continue;
            }
            if (!repByPerson.has(pid)) {
                repByPerson.set(pid, c);
                order.push(c);
                siblings.set(c.id, [c]);
            } else {
                siblings.get(repByPerson.get(pid)!.id)!.push(c);
            }
        }
        return order.map((rep) => {
            const sibs = (siblings.get(rep.id) ?? [rep])
                .slice()
                .sort((a, b) => CHAN_ORDER.indexOf(a.channel) - CHAN_ORDER.indexOf(b.channel));
            return {
                rep,
                siblings: sibs,
                unread: sibs.reduce((n, s) => n + (s.unread || 0), 0),
                lastAt: sibs.reduce<string | null>(
                    (m, s) => (s.last_message_at && (!m || s.last_message_at > m) ? s.last_message_at : m),
                    null,
                ),
            };
        });
    }, [filteredConvs]);

    const humanCount = useMemo(() => conversations.filter(
        (c) => c.intercept_mode === "human",
    ).length, [conversations]);

    const yoursCount = useMemo(() => conversations.filter(
        (c) => c.intercept_mode === "human" && c.assigned_agent_id === currentAgentId,
    ).length, [conversations, currentAgentId]);

    // ── Bulk selection ────────────────────────────────────────────────────────
    // Picking up ten threads is one click each; handing them back was ten more.
    // Selection mode turns the list into a checklist so a whole shift's worth of
    // conversations goes back to Neema in one action. A row is a PERSON, so
    // releasing it releases every channel they're held on.
    const rowKeyOf = useCallback(
        (g: { rep: Conversation }) => g.rep.person_id ?? g.rep.id, []);

    const heldIdsOf = useCallback(
        (g: { siblings: Conversation[] }) =>
            g.siblings.filter((s) => s.intercept_mode === "human").map((s) => s.id), []);

    const exitSelect = useCallback(() => {
        setSelectMode(false);
        setSelected(new Set());
        anchorRow.current = null;
    }, []);

    // How many conversations the Release button would actually act on — a row
    // that is already with Neema is selectable but costs nothing.
    const selectedHeldIds = useMemo(() => {
        const out: string[] = [];
        for (const g of groupedConvs) {
            if (selected.has(rowKeyOf(g))) out.push(...heldIdsOf(g));
        }
        return out;
    }, [groupedConvs, selected, rowKeyOf, heldIdsOf]);

    const toggleRow = useCallback((key: string, index: number, range = false) => {
        setSelected((prev) => {
            const next = new Set(prev);
            if (range && anchorRow.current !== null) {
                // Shift-click fills the span — the difference between releasing
                // a morning's worth of threads in one gesture or forty clicks.
                const [from, to] = anchorRow.current <= index
                    ? [anchorRow.current, index] : [index, anchorRow.current];
                for (let i = from; i <= to; i++) {
                    const g = groupedConvs[i];
                    if (g) next.add(rowKeyOf(g));
                }
            } else if (next.has(key)) {
                next.delete(key);
            } else {
                next.add(key);
            }
            return next;
        });
        anchorRow.current = index;
    }, [groupedConvs, rowKeyOf]);

    const releaseSelected = useCallback(async () => {
        const ids = selectedHeldIds;
        if (!ids.length) {
            onToast("None of those are held by a human", "warning");
            return;
        }
        setBulkBusy(true);
        const results = await Promise.allSettled(ids.map((id) => conversationsApi.release(id)));
        const failed = results.filter((r) => r.status === "rejected").length;
        const ok = ids.length - failed;
        setBulkBusy(false);
        exitSelect();
        refetchConversations?.();
        if (failed) onToast(`Released ${ok} — ${failed} failed`, "error");
        else onToast(`${ok} conversation${ok === 1 ? "" : "s"} released back to Neema`);
    }, [selectedHeldIds, exitSelect, refetchConversations, onToast]);

    // Esc leaves selection, ⌘/Ctrl+A takes everything currently filtered — so
    // "Yours" + select-all + Release hands back a whole shift in three actions.
    useEffect(() => {
        if (!selectMode) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") { e.preventDefault(); exitSelect(); }
            else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "a") {
                e.preventDefault();
                setSelected(new Set(groupedConvs.map(rowKeyOf)));
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [selectMode, exitSelect, groupedConvs, rowKeyOf]);

    // Changing what the list shows clears the picks: a selection you can no
    // longer see is one you can't check before releasing it.
    // (selectMode is deliberately not a dependency — entering it via long-press
    // must not wipe the row that gesture just picked.)
    useEffect(() => {
        setSelected(new Set());
        anchorRow.current = null;
    }, [readFilter, channelTab, searchQ, tagFilter]);

    // ── Render ────────────────────────────────────────────────────────────────

    const ConvList = (
        <div
            className="flex flex-col h-full bg-white"
            style={{
                width: isMobile ? "100%" : LIST_WIDTH,
                minWidth: isMobile ? "100%" : LIST_WIDTH,
                borderRight: "1px solid #edf0ea",
            }}
        >
            {/* Header */}
            <div className="px-4 pt-4 pb-3" style={{ borderBottom: "1px solid #edf0ea" }}>
                <div className="flex items-center justify-between mb-3">
                    <h1 className="text-sm font-semibold" style={{ color: "#1c2917", letterSpacing: "-0.01em" }}>
                        {selectMode
                            ? `${selected.size} selected`
                            : "Chats"}
                    </h1>
                    <div className="flex items-center gap-2">
                        {selectMode ? (
                            <>
                                <button
                                    onClick={() => setSelected(
                                        selected.size === groupedConvs.length
                                            ? new Set()
                                            : new Set(groupedConvs.map(rowKeyOf)))}
                                    className="text-[11px] font-medium px-2 py-1 rounded-lg hover:bg-[#f0f4ec]"
                                    style={{ color: "#427425" }}
                                >
                                    {selected.size === groupedConvs.length && groupedConvs.length > 0
                                        ? "Clear" : "Select all"}
                                </button>
                                <button
                                    onClick={exitSelect}
                                    className="text-[11px] font-medium px-2 py-1 rounded-lg hover:bg-[#f0f4ec]"
                                    style={{ color: "#8a9e80" }}
                                >
                                    Cancel
                                </button>
                            </>
                        ) : (
                            <>
                                {humanCount > 0 && (
                                    <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: "#fff3cd", color: "#856404" }}>
                                        {humanCount} live
                                    </span>
                                )}
                                <button
                                    onClick={() => setSelectMode(true)}
                                    title="Select several (or press and hold a chat)"
                                    className="w-7 h-7 rounded-lg flex items-center justify-center transition-colors hover:bg-[#f0f4ec]"
                                    style={{ color: "#8a9e80" }}
                                >
                                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                              d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                                    </svg>
                                </button>
                            </>
                        )}
                        <button
                            onClick={() => setShowFilters((f) => !f)}
                            className={`w-7 h-7 rounded-lg flex items-center justify-center transition-colors ${showFilters ? "bg-[#589b31] text-white" : "hover:bg-[#f0f4ec]"}`}
                            style={{ color: showFilters ? "white" : "#8a9e80" }}
                        >
                            <svg
                                className="w-3.5 h-3.5"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                            >
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M3 4h18M7 8h10M11 12h2M13 16h-2"
                                />
                            </svg>
                        </button>
                    </div>
                </div>

                {/* Read / Unread / Human-pickup / Yours toggle */}
                <div className="flex items-center flex-wrap gap-1 mb-2">
                    {(["all", "unread", "read", "human", "yours"] as const).map((f) => (
                        <button
                            key={f}
                            onClick={() => setReadFilter(f)}
                            className={`flex-1 min-w-[58px] h-7 px-1.5 rounded-lg text-xs font-medium transition-colors flex items-center justify-center gap-1.5`}
                            style={{
                                backgroundColor: readFilter === f
                                    ? f === "unread" ? "#427425"
                                    : f === "human" ? "#b45309"
                                    : f === "yours" ? "#589b31"
                                    : "#1c2917"
                                    : "#f5f6f3",
                                color: readFilter === f ? "#fff" : "#6b7e64",
                            }}
                        >
                            {f === "all" && "All"}
                            {f === "unread" && (
                                <>
                                    Unread
                                    {unreadCount > 0 && (
                                        <span
                                            className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full leading-none ${readFilter === "unread" ? "bg-white/25 text-white" : "bg-[#427425] text-white"}`}
                                        >
                                            {unreadCount}
                                        </span>
                                    )}
                                </>
                            )}
                            {f === "read" && "Read"}
                            {f === "human" && (
                                <>
                                    Human
                                    {humanCount > 0 && (
                                        <span
                                            className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full leading-none ${readFilter === "human" ? "bg-white/25 text-white" : "bg-[#b45309] text-white"}`}
                                        >
                                            {humanCount}
                                        </span>
                                    )}
                                </>
                            )}
                            {f === "yours" && (
                                <>
                                    Yours
                                    {yoursCount > 0 && (
                                        <span
                                            className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full leading-none ${readFilter === "yours" ? "bg-white/25 text-white" : "bg-[#589b31] text-white"}`}
                                        >
                                            {yoursCount}
                                        </span>
                                    )}
                                </>
                            )}
                        </button>
                    ))}
                </div>

                {/* Search */}
                <div className="relative mb-2">
                    <svg
                        className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5"
                        style={{ color: "#b5c9a8" }}
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                    >
                        <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                        />
                    </svg>
                    <input
                        value={searchQ}
                        onChange={(e) => setSearchQ(e.target.value)}
                        placeholder="Start typing to search"
                        className="w-full h-8 pl-8 pr-3 text-xs rounded-lg focus:outline-none focus:ring-1 focus:ring-[#589b31]"
                        style={{
                            fontSize: 13,
                            backgroundColor: "#f5f6f3",
                            border: "1px solid #edf0ea",
                            color: "#1c2917",
                        }}
                    />
                </div>

                {/* Channel tabs — icon pills per channel, spread evenly across the row */}
                <div className="flex gap-1.5 pt-2 pb-1">
                    {CHANNEL_TABS.map((tab) => {
                        const active = channelTab === tab.id;
                        const cfg = tab.id === "all" ? null : CHANNEL_CONFIG[tab.id as Channel];
                        const accent = cfg?.color ?? ALL_TAB_ACCENT;
                        const count = channelCounts[tab.id] ?? 0;
                        return (
                            <button
                                key={tab.id}
                                onClick={() => setChannelTab(tab.id)}
                                title={tab.label}
                                className="relative flex-1 min-w-0 flex flex-col items-center justify-center gap-0.5 h-10 rounded-lg border transition-all hover:brightness-[0.97]"
                                style={{
                                    // Each channel wears its own brand hue: full fill when
                                    // active, a soft tint of the same colour when not — so
                                    // the tabs read as distinct, coloured, and attractive.
                                    backgroundColor: active ? accent : accent + "14",
                                    borderColor: active ? accent : accent + "33",
                                }}
                            >
                                <span
                                    className="flex items-center justify-center [&>svg]:w-3.5 [&>svg]:h-3.5"
                                    style={{ color: active ? "#ffffff" : accent }}
                                >
                                    {tab.id === "all" ? <SparkleIcon /> : cfg!.icon}
                                </span>
                                <span
                                    className="text-[8px] font-bold leading-none tracking-tight"
                                    style={{ color: active ? "#ffffff" : accent }}
                                >
                                    {tab.short}
                                </span>
                                {count > 0 && (
                                    <span
                                        className="absolute -top-1 -right-1 min-w-[14px] h-[14px] px-[3px] rounded-full text-[8px] font-bold flex items-center justify-center text-white leading-none"
                                        style={{ backgroundColor: active ? "#ef4444" : accent }}
                                    >
                                        {count}
                                    </span>
                                )}
                            </button>
                        );
                    })}
                </div>

                {/* Extra filters */}
                {showFilters && (
                    <div className="mt-2 flex gap-1.5 flex-wrap">
                        {/* Tag filter */}
                        {allTags.length > 0 && (
                            <>
                                <button
                                    key="all-tags"
                                    onClick={() => setTagFilter("all")}
                                    className={`h-6 px-2.5 rounded-md text-xs font-medium transition-colors ${tagFilter === "all" ? "text-white" : "bg-[#e6f3d8] text-[#699a32]"}`}
                                    style={
                                        tagFilter === "all"
                                            ? { backgroundColor: "#589b31" }
                                            : undefined
                                    }
                                >
                                    All tags
                                </button>
                                {allTags.map((tag) => (
                                    <button
                                        key={tag}
                                        onClick={() =>
                                            setTagFilter(
                                                tag === tagFilter ? "all" : tag,
                                            )
                                        }
                                        className={`h-6 px-2.5 rounded-md text-xs font-medium transition-colors ${tagFilter === tag ? "text-white" : "bg-[#e6f3d8] text-[#699a32]"}`}
                                        style={
                                            tagFilter === tag
                                                ? { backgroundColor: "#589b31" }
                                                : undefined
                                        }
                                    >
                                        {tag}
                                    </button>
                                ))}
                                <div className="w-full" />
                            </>
                        )}
                        {(["all", "ai", "human", "paused"] as const).map(
                            (m) => (
                                <button
                                    key={m}
                                    onClick={() => setInterceptFilter(m)}
                                    className={`h-6 px-2.5 rounded-md text-xs font-medium capitalize transition-colors ${interceptFilter === m ? "text-white" : "bg-[#e6f3d8] text-[#699a32]"}`}
                                    style={
                                        interceptFilter === m
                                            ? { backgroundColor: "#589b31" }
                                            : undefined
                                    }
                                >
                                    {m}
                                </button>
                            ),
                        )}
                    </div>
                )}
            </div>

            {/* Conversation list */}
            <div
                className={`flex-1 overflow-y-auto scrollbar-none ${isMobile ? "pb-16" : ""}`}
                style={{ backgroundColor: "#ffffff" }}
            >
                {filteredConvs.length === 0 && (
                    <div className="py-16 text-center">
                        <p className="text-sm" style={{ color: "#b5c9a8" }}>
                            No conversations found
                        </p>
                    </div>
                )}
                {groupedConvs.map((group, rowIndex) => {
                    // The row shows the person; the ACTIVE conversation is whichever
                    // sibling (channel) is open — default to the representative.
                    const activeSib =
                        group.siblings.find((s) => s.id === activeConvId) ?? group.rep;
                    const conv = activeSib;
                    const isActive = group.siblings.some((s) => s.id === activeConvId);
                    const hasUnread = group.unread > 0;
                    const multi = group.siblings.length > 1;
                    const rowName = displayName(conv.name, conv.wa_id);
                    // Human pickup on ANY of this person's channels shows on the
                    // row — not only when the human-handled sibling is the open one.
                    const humanSib = group.siblings.find((s) => s.intercept_mode === "human");
                    const chipConv = humanSib ?? conv;
                    const rowStage = group.siblings.map((s) => s.lead_stage).find(Boolean) ?? null;
                    // Completed (paid) orders for the person behind this row —
                    // siblings of one person carry the same count, so max is it.
                    const rowOrders = Math.max(
                        0,
                        ...group.siblings.map((s) => (s as any).orders_count || 0),
                    );
                    const rowKey = group.rep.person_id ?? group.rep.id;
                    const isPicked = selected.has(rowKey);
                    const heldHere = group.siblings.some((s) => s.intercept_mode === "human");
                    // Press and hold to start selecting — the WhatsApp gesture,
                    // so nobody has to find the toolbar button first.
                    const startPress = () => {
                        longPressed.current = false;   // every press starts clean
                        if (selectMode) return;
                        if (pressTimer.current) clearTimeout(pressTimer.current);
                        pressTimer.current = setTimeout(() => {
                            longPressed.current = true;
                            setSelectMode(true);
                            setSelected(new Set([rowKey]));
                            anchorRow.current = rowIndex;
                        }, 450);
                    };
                    const cancelPress = () => {
                        if (pressTimer.current) {
                            clearTimeout(pressTimer.current);
                            pressTimer.current = null;
                        }
                    };
                    return (
                        <button
                            key={rowKey}
                            onClick={(e) => {
                                if (longPressed.current) { longPressed.current = false; return; }
                                if (selectMode) toggleRow(rowKey, rowIndex, e.shiftKey);
                                else handleSelectConv(conv.id);
                            }}
                            onPointerDown={startPress}
                            onPointerUp={cancelPress}
                            onPointerLeave={cancelPress}
                            onPointerCancel={cancelPress}
                            onContextMenu={(e) => {
                                // Right-click is the desktop equivalent of the hold.
                                if (selectMode) return;
                                e.preventDefault();
                                setSelectMode(true);
                                setSelected(new Set([rowKey]));
                                anchorRow.current = rowIndex;
                            }}
                            className="w-full text-left px-4 py-3 transition-colors relative"
                            style={{
                                backgroundColor: isPicked ? "#eef6e5" : isActive ? "#fdf6e9" : "transparent",
                                borderBottom: "1px solid #f2f4ef",
                                borderLeft: `3px solid ${isPicked ? "#589b31" : isActive ? ROW_ACCENT : hasUnread ? "#fcd98a" : "transparent"}`,
                                // Off-screen rows skip layout + paint entirely —
                                // scrolling only ever renders the visible slice.
                                contentVisibility: "auto",
                                containIntrinsicSize: "auto 74px",
                                userSelect: selectMode ? "none" : undefined,
                            } as React.CSSProperties}
                            onMouseEnter={(e) => {
                                if (!isActive && !isPicked) (e.currentTarget as HTMLElement).style.backgroundColor = "#fbfaf6";
                            }}
                            onMouseLeave={(e) => {
                                if (!isActive && !isPicked) (e.currentTarget as HTMLElement).style.backgroundColor = "transparent";
                            }}
                        >
                            <div className="flex items-start gap-3">
                                {selectMode && (
                                    <span
                                        title={heldHere ? undefined : "Already with Neema — nothing to release"}
                                        className="flex-shrink-0 mt-3 w-[18px] h-[18px] rounded-md border flex items-center justify-center transition-all"
                                        style={{
                                            borderColor: isPicked ? "#589b31" : "#cfdac6",
                                            backgroundColor: isPicked ? "#589b31" : "#fff",
                                            transform: isPicked ? "scale(1)" : "scale(0.92)",
                                            // A row Neema already handles stays selectable but
                                            // reads as a no-op, so the count never surprises.
                                            opacity: heldHere ? 1 : 0.45,
                                        }}
                                    >
                                        {isPicked && (
                                            <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                            </svg>
                                        )}
                                    </span>
                                )}
                                <div className="relative flex-shrink-0">
                                    <Avatar
                                        name={rowName}
                                        src={conv.avatar_url}
                                        size={38}
                                    />
                                    {/* Country flag — top right */}
                                    {(conv as any).country_iso && (
                                        <img
                                            src={`https://flagcdn.com/w20/${(conv as any).country_iso.toLowerCase()}.png`}
                                            alt={(conv as any).country_iso}
                                            className="absolute -top-0.5 -right-0.5 w-4 h-3 rounded-sm object-cover border border-white shadow-sm"
                                        />
                                    )}
                                    {/* Unread pulse dot on avatar */}
                                    {hasUnread && (
                                        <span className="absolute -top-0.5 -left-0.5 w-2.5 h-2.5 rounded-full border-2 border-white" style={{ backgroundColor: ROW_ACCENT }} />
                                    )}
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center justify-between mb-0.5">
                                        <span
                                            className="text-sm truncate"
                                            style={{
                                                fontWeight: hasUnread ? 600 : 500,
                                                color: "#1c2917",
                                            }}
                                        >
                                            {rowName}
                                        </span>
                                        <span className="flex items-center gap-1.5 flex-shrink-0 ml-2">
                                            {/* Repeat-buyer badge: how many orders this
                                                customer has completed (paid) before. */}
                                            {rowOrders > 0 && (
                                                <span
                                                    title={`${rowOrders} completed order${rowOrders > 1 ? "s" : ""}`}
                                                    className="min-w-[16px] h-[16px] px-1 rounded-full text-white text-[9px] font-bold inline-flex items-center justify-center leading-none"
                                                    style={{
                                                        background: "linear-gradient(135deg, #f59e0b, #d97706)",
                                                        boxShadow: "0 1px 2px rgba(217,119,6,.35)",
                                                    }}
                                                >
                                                    {rowOrders > 99 ? "99+" : rowOrders}
                                                </span>
                                            )}
                                            <span
                                                className="text-[10px]"
                                                style={{
                                                    fontWeight: hasUnread ? 600 : 400,
                                                    color: hasUnread ? "#427425" : "#b5c9a8",
                                                }}
                                            >
                                                {group.lastAt
                                                    ? timeAgo(group.lastAt)
                                                    : ""}
                                            </span>
                                        </span>
                                    </div>
                                    {/* Chips on their OWN line (never squeezing the
                                        preview), then the preview gets the full width
                                        and a clean 2-line clamp. */}
                                    <div className="flex flex-col gap-0.5">
                                        <div className="flex items-center gap-1 flex-wrap">
                                            {/* Channel chips — one per linked channel for
                                                this person. Click loads THAT channel's
                                                thread. The open one is filled; the rest are
                                                tinted. A lone channel is just a pill. */}
                                            {group.siblings.map((sib) => {
                                                const scfg = CHANNEL_CONFIG[sib.channel as Channel];
                                                if (!scfg) return null;
                                                const open = sib.id === activeConvId;
                                                const chipUnread = (sib.unread || 0) > 0;
                                                return (
                                                    <span
                                                        key={sib.id}
                                                        role={multi ? "button" : undefined}
                                                        onClick={
                                                            multi
                                                                ? (e) => {
                                                                      e.stopPropagation();
                                                                      handleSelectConv(sib.id);
                                                                  }
                                                                : undefined
                                                        }
                                                        title={multi ? `Open ${sib.channel}` : undefined}
                                                        className="text-[10px] font-bold px-1.5 h-[16px] rounded border flex items-center leading-none relative"
                                                        style={{
                                                            // Matches the channel-tab palette:
                                                            // filled brand colour when open, a soft
                                                            // tint of the same hue otherwise.
                                                            backgroundColor: open ? scfg.color : scfg.color + "14",
                                                            borderColor: open ? scfg.color : scfg.color + "33",
                                                            color: open ? "#fff" : scfg.color,
                                                            cursor: multi ? "pointer" : "default",
                                                        }}
                                                    >
                                                        {CH_SHORT[sib.channel as Channel]}
                                                        {multi && chipUnread && !open && (
                                                            <span
                                                                className="absolute -top-1 -right-1 w-1.5 h-1.5 rounded-full"
                                                                style={{ backgroundColor: "#589b31" }}
                                                            />
                                                        )}
                                                    </span>
                                                );
                                            })}
                                            {rowStage && rowStage !== "new" && (
                                                <span
                                                    className="text-[10px] font-semibold px-1.5 h-[16px] rounded border flex items-center leading-none capitalize"
                                                    title={`Lead stage: ${rowStage}`}
                                                    style={{
                                                        backgroundColor: (STAGE_CHIP[rowStage] ?? STAGE_CHIP.contacted).bg,
                                                        borderColor: (STAGE_CHIP[rowStage] ?? STAGE_CHIP.contacted).bd,
                                                        color: (STAGE_CHIP[rowStage] ?? STAGE_CHIP.contacted).fg,
                                                    }}
                                                >
                                                    {rowStage}
                                                </span>
                                            )}
                                            {/* Country chip — the flag on the avatar
                                                says it small; this says it by name. */}
                                            {(conv as any).country_iso && (
                                                <span
                                                    className="text-[10px] font-semibold px-1.5 h-[16px] rounded border inline-flex items-center leading-none"
                                                    title={`Country: ${countryName((conv as any).country_iso)}`}
                                                    style={{
                                                        // Bright brand-orange so the
                                                        // country reads at a glance.
                                                        backgroundColor: "#ffedd5",
                                                        borderColor: "#fdba74",
                                                        color: "#c2410c",
                                                    }}
                                                >
                                                    <span className="truncate max-w-[96px]">
                                                        {countryName((conv as any).country_iso)}
                                                    </span>
                                                </span>
                                            )}
                                            {chipConv.intercept_mode !== "ai" && (
                                                <div className="flex items-center gap-1">
                                                    <InterceptBadge
                                                        mode={
                                                            chipConv.intercept_mode
                                                        }
                                                    />
                                                    {chipConv.intercept_mode ===
                                                        "human" &&
                                                        chipConv.assigned_agent_id && (
                                                            <span
                                                                className={`text-[10px] font-medium truncate max-w-[92px] ${
                                                                    chipConv.assigned_agent_id ===
                                                                    currentAgentId
                                                                        ? "text-[#427425]"
                                                                        : "text-amber-600"
                                                                }`}
                                                            >
                                                                {chipConv.assigned_agent_id ===
                                                                currentAgentId
                                                                    ? "● Yours"
                                                                    : `🔒 ${chipConv.assigned_agent_name?.split(" ")[0] || "Agent"}`}
                                                            </span>
                                                        )}
                                                </div>
                                            )}
                                            {hasUnread && (
                                                <span className="min-w-[18px] h-[18px] px-1 text-white text-[10px] font-bold rounded-full flex items-center justify-center" style={{ backgroundColor: "#589b31" }}>
                                                    {group.unread > 99
                                                        ? "99+"
                                                        : group.unread}
                                                </span>
                                            )}
                                        </div>
                                        <p
                                            className="text-xs line-clamp-2 break-words"
                                            style={{
                                                color: hasUnread ? "#3d5a30" : "#8a9e80",
                                                fontWeight: hasUnread ? 500 : 400,
                                            }}
                                        >
                                            {conv.last_message ??
                                                "No messages yet"}
                                        </p>
                                    </div>
                                </div>
                            </div>
                        </button>
                    );
                })}
            </div>

            {/* Bulk action bar — only while selecting, so it never costs space */}
            {selectMode && (
                <div
                    className="px-3 py-2.5 flex items-center gap-2"
                    style={{ borderTop: "1px solid #edf0ea", backgroundColor: "#fbfcfa" }}
                >
                    <div className="flex-1 min-w-0">
                        <p className="text-[11px] font-medium truncate" style={{ color: "#3d5a30" }}>
                            {selected.size === 0
                                ? "Tap chats to select"
                                : `${selected.size} chat${selected.size === 1 ? "" : "s"} selected`}
                        </p>
                        {selected.size > 0 && (
                            <p className="text-[10px]" style={{ color: "#8a9e80" }}>
                                {selectedHeldIds.length === 0
                                    ? "none are human-held"
                                    : `${selectedHeldIds.length} to hand back to Neema`}
                            </p>
                        )}
                    </div>
                    <button
                        onClick={releaseSelected}
                        disabled={bulkBusy || selectedHeldIds.length === 0}
                        className="text-xs font-semibold px-3 h-8 rounded-lg text-white transition-opacity disabled:opacity-40"
                        style={{ backgroundColor: "#589b31" }}
                    >
                        {bulkBusy ? "Releasing…" : `Release${selectedHeldIds.length ? ` ${selectedHeldIds.length}` : ""}`}
                    </button>
                </div>
            )}
        </div>
    );

    const ThreadPanel = (
        <div className="flex flex-1 overflow-hidden">
            <div className="flex flex-col flex-1 overflow-hidden relative" style={{ backgroundColor: "#f8fafc" }}>
                {!activeConv ? (
                    <div className="flex-1 flex items-center justify-center" style={{ color: "#c5d5bc" }}>
                        <div className="text-center">
                            <div className="text-4xl mb-2">💬</div>
                            <p className="text-sm">Select a conversation</p>
                        </div>
                    </div>
                ) : (
                    <>
                        {/* Floating profile FAB — mobile only */}
                        {isMobile && (
                            <button
                                onClick={() => setMobileCrmOpen(true)}
                                title="View customer profile"
                                className="absolute top-3 right-3 z-20 w-8 h-8 rounded-full bg-white border border-[#edf0ea] shadow-sm flex items-center justify-center text-[#427425] hover:bg-[#fafbf8] transition-colors"
                            >
                                <svg
                                    className="w-4 h-4"
                                    fill="none"
                                    stroke="currentColor"
                                    viewBox="0 0 24 24"
                                >
                                    <path
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                        strokeWidth={2}
                                        d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
                                    />
                                </svg>
                            </button>
                        )}
                        {/* Thread header */}
                        <div className="px-4 py-3 bg-white flex items-center gap-2 flex-wrap" style={{ borderBottom: "1px solid #edf0ea" }}>
                            {isMobile && (
                                <button
                                    onClick={() => setMobilePanel("list")}
                                    className="text-[#8a9e80] mr-1 flex-shrink-0"
                                >
                                    <svg
                                        className="w-5 h-5"
                                        fill="none"
                                        stroke="currentColor"
                                        viewBox="0 0 24 24"
                                    >
                                        <path
                                            strokeLinecap="round"
                                            strokeLinejoin="round"
                                            strokeWidth={2}
                                            d="M15 19l-7-7 7-7"
                                        />
                                    </svg>
                                </button>
                            )}
                            <Avatar
                                name={displayName(
                                    activeConv.name,
                                    activeConv.wa_id,
                                )}
                                src={activeConv.avatar_url}
                                size={32}
                            />
                            <div className="flex-1 min-w-0">
                                <div className="text-sm font-semibold truncate" style={{ color: "#1c2917" }}>
                                    {displayName(
                                        activeConv.name,
                                        activeConv.wa_id,
                                    )}
                                </div>
                                <div className="text-xs truncate" style={{ color: "#b5c9a8", fontFamily: "'DM Mono', monospace" }}>
                                    {formatPhone(activeConv.wa_id)}
                                </div>
                            </div>
                            <div className="flex items-center gap-1.5 flex-shrink-0 flex-wrap">
                                <InterceptBadge
                                    mode={activeConv.intercept_mode}
                                />

                                {/* Assigned agent name */}
                                {activeConv.assigned_agent_id &&
                                    activeConv.assigned_agent_name && (
                                        <span className="text-xs text-[#b5c9a8] hidden lg:block">
                                            → {activeConv.assigned_agent_name}
                                        </span>
                                    )}

                                {/* ── Intercept ──
                                    Any agent/admin can intercept an AI conv.
                                    Not ownership-restricted — whoever picks it up owns it. */}
                                {activeConv.intercept_mode === "ai" &&
                                    canHandleConversations && (
                                        <Btn
                                            small
                                            onClick={() =>
                                                intercept(activeConv.id)
                                            }
                                            variant="primary"
                                        >
                                            ⚡ Intercept
                                        </Btn>
                                    )}
                                {/* ── Pick up ──
                                    Shown when conversation was auto-escalated (media received)
                                    but not yet claimed by any agent. First one to click gets it. */}
                                {activeConv.intercept_mode === "human" &&
                                    !activeConv.assigned_agent_id &&
                                    canHandleConversations && (
                                        <Btn
                                            small
                                            onClick={() =>
                                                intercept(activeConv.id)
                                            }
                                            variant="primary"
                                        >
                                            🙋 Pick up
                                        </Btn>
                                    )}

                                {/* ── Release ──
                                    Owner-restricted: only the intercepting agent or admin/super can release. */}
                                {activeConv.intercept_mode === "human" &&
                                    (isOwner || isAdminOrSuper) && (
                                        <Btn
                                            key="release"
                                            small
                                            onClick={() =>
                                                release(activeConv.id)
                                            }
                                            variant="secondary"
                                        >
                                            ↩ Release
                                        </Btn>
                                    )}

                                {/* ── Locked badge ──
                                    Regular agents see this when another agent owns the conv.
                                    Admin/superuser never see this badge. */}
                                {convOwnedByOther && !isAdminOrSuper && (
                                    <span
                                        className="text-xs px-2 py-1 rounded-md bg-stone-100 text-stone-400 cursor-not-allowed"
                                        title={`Handled by ${activeConv.assigned_agent_name ?? "another agent"} — they must release or transfer it first`}
                                    >
                                        🔒{" "}
                                        {activeConv.assigned_agent_name?.split(
                                            " ",
                                        )[0] ?? "Locked"}
                                    </span>
                                )}

                                {/* ── Pause ──
                                    Any agent/admin can pause unless another agent owns
                                    it (regular agents blocked; admin/super can override). */}
                                {activeConv.intercept_mode !== "paused" &&
                                    canActOnThisConv && (
                                        <Btn
                                            key="pause"
                                            small
                                            onClick={() =>
                                                release(activeConv.id)
                                            }
                                            variant="secondary"
                                        >
                                            ⏸ Pause
                                        </Btn>
                                    )}

                                {/* ── Resume — same rules as Pause */}
                                {activeConv.intercept_mode === "paused" &&
                                    canActOnThisConv && (
                                        <Btn
                                            key="resume"
                                            small
                                            onClick={() =>
                                                release(activeConv.id)
                                            }
                                            variant="primary"
                                        >
                                            ▶ Resume
                                        </Btn>
                                    )}

                                {/* ── Transfer — same rules as Pause/Resume */}
                                {canActOnThisConv && (
                                    <Btn
                                        key="transfer"
                                        small
                                        onClick={() => setTransferModal(true)}
                                        variant="secondary"
                                    >
                                        ⇄
                                    </Btn>
                                )}

                                {/* ── Note — any agent/admin, no ownership restriction */}
                                {canHandleConversations && (
                                    <Btn
                                        key="note"
                                        small
                                        onClick={() => setNoteModal(true)}
                                        variant="secondary"
                                    >
                                        📝
                                    </Btn>
                                )}

                                {/* ── Clear history — admin/superuser only ── */}
                                {isAdminOrSuper && (
                                    <Btn
                                        key="clear-history"
                                        small
                                        onClick={() => setClearConfirm(true)}
                                        variant="danger"
                                    >
                                        🗑️
                                    </Btn>
                                )}

                                {/* ── Close — any agent/admin, no ownership restriction */}
                                {/* {activeConv.status === "open" &&
                                    canHandleConversations && (
                                        <Btn
                                            key="close"
                                            small
                                            onClick={() =>
                                                closeConv(activeConv.id)
                                            }
                                            variant="danger"
                                        >
                                            ✓
                                        </Btn>
                                    )} */}
                            </div>
                        </div>

                        {/* Messages */}
                        <div
                            className="flex-1 overflow-y-auto px-5 py-4 space-y-3"
                            style={{ backgroundColor: "#f5f7f2" }}
                        >
                            {threadLoading && (
                                <div className="flex justify-center py-8">
                                    <div className="w-5 h-5 border-2 border-t-transparent rounded-full animate-spin" style={{ borderColor: "#589b31", borderTopColor: "transparent" }} />
                                </div>
                            )}
                            {!threadLoading && activeMessages.length === 0 && (
                                <div className="text-center py-12" style={{ color: "#c5d5bc" }}>
                                    <p className="text-sm">No messages yet</p>
                                </div>
                            )}
                            {(() => {
                                // How many messages were unread when this thread was opened
                                const snap = unreadSnapshot[activeConvId] ?? 0;
                                // The divider sits before the first unread message
                                const dividerIdx =
                                    snap > 0
                                        ? Math.max(
                                              0,
                                              activeMessages.length - snap,
                                          )
                                        : -1;
                                // ── Sort: escalation system events nudged just after their
                                // preceding inbound message so they always appear below it.
                                const sortedMessages = sortedActiveMessages;

                                // ── Dedup: only show the FIRST escalation/system-intercept per thread.
                                // Repeat media requests after the first escalation are suppressed.
                                let escalationShown = false;

                                return sortedMessages.map((msg, idx) => {
                                    const isInbound =
                                        msg.direction === "inbound";
                                    const isNote = msg.isNote;
                                    const showDivider =
                                        idx === dividerIdx && snap > 0;
                                    // Album members render inside the lead's collage.
                                    const album = albumOf.get(msg.id);
                                    if (album && !album.lead) return null;

                                    // ── System event card ────────────────────
                                    if (msg.type === "system_event") {
                                        const kind = msg.event_kind ?? "";

                                        // ── Handoff / mode-change events live in the
                                        // Activity Log side panel ONLY — keep them out
                                        // of the thread so the log isn't duplicated
                                        // inline (Released to AI, agent pickup, transfer,
                                        // approved draft). Escalation/flag cards stay
                                        // inline since they carry "why" context.
                                        const isAgentPickup =
                                            kind === "intercept" && !!msg.agent_name;
                                        if (
                                            kind === "release" ||
                                            kind === "transfer" ||
                                            kind === "approve_draft" ||
                                            isAgentPickup
                                        ) {
                                            // Preserve the "N new" divider if it happens
                                            // to land on a suppressed event.
                                            return showDivider ? (
                                                <div
                                                    key={msg.id}
                                                    className="flex items-center gap-2 my-1"
                                                >
                                                    <div className="flex-1 h-px bg-[#427425]/30" />
                                                    <span className="text-[10px] font-semibold text-[#427425] bg-[#e6f3d8] px-2 py-0.5 rounded-full whitespace-nowrap">
                                                        {snap} new {snap === 1 ? "message" : "messages"}
                                                    </span>
                                                    <div className="flex-1 h-px bg-[#427425]/30" />
                                                </div>
                                            ) : null;
                                        }

                                        // ── Escalated card ───────────────────
                                        // Shown when AI cannot handle (customer
                                        // request or media received).  Gives full
                                        // context so the agent understands why.
                                        if (kind === "escalated") {
                                            // Only show the first escalation; suppress repeats
                                            if (escalationShown) return null;
                                            escalationShown = true;
                                            const reasonText = msg.event_reason || "AI could not continue — agent needed";
                                            return (
                                                <React.Fragment key={msg.id}>
                                                    {showDivider && (
                                                        <div className="flex items-center gap-2 my-1">
                                                            <div className="flex-1 h-px bg-[#427425]/30" />
                                                            <span className="text-[10px] font-semibold text-[#427425] bg-[#e6f3d8] px-2 py-0.5 rounded-full whitespace-nowrap">
                                                                {snap} new {snap === 1 ? "message" : "messages"}
                                                            </span>
                                                            <div className="flex-1 h-px bg-[#427425]/30" />
                                                        </div>
                                                    )}
                                                    <div className="flex flex-col items-center gap-1 my-2">
                                                        <div className="flex items-center gap-2 w-full">
                                                            <div className="flex-1 h-px bg-amber-200" />
                                                            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-50 border border-amber-200 flex-shrink-0">
                                                                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse flex-shrink-0" />
                                                                <span className="text-[10px] font-semibold text-amber-700 whitespace-nowrap">Escalated to agent</span>
                                                                <span className="text-[9px] text-amber-400 whitespace-nowrap">· {msg.created_at ? timeAgo(msg.created_at) : ""}</span>
                                                            </div>
                                                            <div className="flex-1 h-px bg-amber-200" />
                                                        </div>
                                                        <p className="text-[10px] text-amber-600 text-center leading-relaxed max-w-[72%]">{reasonText}</p>
                                                    </div>
                                                </React.Fragment>
                                            );
                                        }

                                        // ── Flag card ────────────────────────
                                        // "Needs Attention" — shown as a compact
                                        // red pill when the conv is flagged.
                                        if (kind === "flag") {
                                            return (
                                                <React.Fragment key={msg.id}>
                                                    {showDivider && (
                                                        <div className="flex items-center gap-2 my-1">
                                                            <div className="flex-1 h-px bg-[#427425]/30" />
                                                            <span className="text-[10px] font-semibold text-[#427425] bg-[#e6f3d8] px-2 py-0.5 rounded-full whitespace-nowrap">
                                                                {snap} new {snap === 1 ? "message" : "messages"}
                                                            </span>
                                                            <div className="flex-1 h-px bg-[#427425]/30" />
                                                        </div>
                                                    )}
                                                    <div className="flex items-center gap-2 my-2">
                                                        <div className="flex-1 h-px bg-red-100" />
                                                        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-red-100 text-red-700">
                                                            <span className="text-[10px] font-semibold whitespace-nowrap">🚩 Flagged: Needs Attention</span>
                                                            {msg.created_at && <span className="text-[9px] opacity-60 whitespace-nowrap">· {timeAgo(msg.created_at)}</span>}
                                                        </div>
                                                        <div className="flex-1 h-px bg-red-100" />
                                                    </div>
                                                </React.Fragment>
                                            );
                                        }

                                        // ── Intercept card ───────────────────
                                        // Two cases:
                                        //  1. agent_name is null  → system auto-escalated
                                        //     (customer sent media, or requested media).
                                        //     Render the amber escalation card so agents
                                        //     understand WHY the conv is now human-mode.
                                        //  2. agent_name is set   → a real agent picked up.
                                        //     Render the named purple pickup pill.
                                        if (kind === "intercept") {
                                            // ── Case 1: system / media escalation ──
                                            if (!msg.agent_name) {
                                                // Only show the first escalation; suppress repeats
                                                if (escalationShown) return null;
                                                escalationShown = true;
                                                const hasInboundMedia = sortedMessages
                                                    .slice(0, idx)
                                                    .some(
                                                        (m) =>
                                                            m.direction === "inbound" &&
                                                            !!m.media_type,
                                                    );
                                                const reasonText =
                                                    msg.event_reason ||
                                                    (hasInboundMedia
                                                        ? "Media received — AI cannot process"
                                                        : "AI could not continue — agent needed");

                                                return (
                                                    <React.Fragment key={msg.id}>
                                                        {showDivider && (
                                                            <div className="flex items-center gap-2 my-1">
                                                                <div className="flex-1 h-px bg-[#427425]/30" />
                                                                <span className="text-[10px] font-semibold text-[#427425] bg-[#e6f3d8] px-2 py-0.5 rounded-full whitespace-nowrap">
                                                                    {snap} new {snap === 1 ? "message" : "messages"}
                                                                </span>
                                                                <div className="flex-1 h-px bg-[#427425]/30" />
                                                            </div>
                                                        )}
                                                        <div className="flex flex-col items-center gap-1 my-2">
                                                            <div className="flex items-center gap-2 w-full">
                                                                <div className="flex-1 h-px bg-amber-200" />
                                                                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-50 border border-amber-200 flex-shrink-0">
                                                                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse flex-shrink-0" />
                                                                    <span className="text-[10px] font-semibold text-amber-700 whitespace-nowrap">Escalated to agent</span>
                                                                    <span className="text-[9px] text-amber-400 whitespace-nowrap">· {msg.created_at ? timeAgo(msg.created_at) : ""}</span>
                                                                </div>
                                                                <div className="flex-1 h-px bg-amber-200" />
                                                            </div>
                                                            <p className="text-[10px] text-amber-600 text-center leading-relaxed max-w-[72%]">{reasonText}</p>
                                                        </div>
                                                    </React.Fragment>
                                                );
                                            }

                                            // ── Case 2: named agent pickup ──────
                                            const agentInitials = msg.agent_name
                                                .split(" ")
                                                .map((w: string) => w[0])
                                                .join("")
                                                .slice(0, 2)
                                                .toUpperCase();
                                            return (
                                                <React.Fragment key={msg.id}>
                                                    {showDivider && (
                                                        <div className="flex items-center gap-2 my-1">
                                                            <div className="flex-1 h-px bg-[#427425]/30" />
                                                            <span className="text-[10px] font-semibold text-[#427425] bg-[#e6f3d8] px-2 py-0.5 rounded-full whitespace-nowrap">
                                                                {snap} new {snap === 1 ? "message" : "messages"}
                                                            </span>
                                                            <div className="flex-1 h-px bg-[#427425]/30" />
                                                        </div>
                                                    )}
                                                    <div className="flex items-center gap-2 my-3">
                                                        <div className="flex-1 h-px bg-purple-100" />
                                                        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-purple-50 border border-purple-200">
                                                            <div className="w-4 h-4 rounded-full bg-purple-200 flex items-center justify-center text-[8px] font-bold text-purple-800 flex-shrink-0">
                                                                {agentInitials}
                                                            </div>
                                                            <span className="text-[10px] font-semibold text-purple-800 whitespace-nowrap">
                                                                {msg.agent_name} picked up
                                                            </span>
                                                            <span className="text-[9px] text-purple-400 whitespace-nowrap">· {msg.created_at ? timeAgo(msg.created_at) : ""}</span>
                                                        </div>
                                                        <div className="flex-1 h-px bg-purple-100" />
                                                    </div>
                                                </React.Fragment>
                                            );
                                        }

                                        // ── Release / Transfer / other ───────
                                        // Simple centred pill for mode changes
                                        // that don't need extra elaboration.
                                        const genericPillStyle: Record<string, string> = {
                                            release:      "bg-blue-50 border-blue-200 text-blue-700",
                                            transfer:     "bg-indigo-50 border-indigo-200 text-indigo-700",
                                            approve_draft: "bg-green-50 border-green-200 text-green-700",
                                        };
                                        const pillStyle = genericPillStyle[kind] ?? "bg-stone-100 border-stone-200 text-stone-600";

                                        return (
                                            <React.Fragment key={msg.id}>
                                                {showDivider && (
                                                    <div className="flex items-center gap-2 my-1">
                                                        <div className="flex-1 h-px bg-[#427425]/30" />
                                                        <span className="text-[10px] font-semibold text-[#427425] bg-[#e6f3d8] px-2 py-0.5 rounded-full whitespace-nowrap">
                                                            {snap} new {snap === 1 ? "message" : "messages"}
                                                        </span>
                                                        <div className="flex-1 h-px bg-[#427425]/30" />
                                                    </div>
                                                )}
                                                <div className="flex items-center gap-2 my-2">
                                                    <div className="flex-1 h-px bg-stone-200" />
                                                    <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border whitespace-nowrap ${pillStyle}`}>
                                                        <span className="text-[10px] font-semibold">{msg.text}</span>
                                                        {msg.created_at && <span className="text-[9px] opacity-60">· {timeAgo(msg.created_at)}</span>}
                                                    </div>
                                                    <div className="flex-1 h-px bg-stone-200" />
                                                </div>
                                            </React.Fragment>
                                        );
                                    }

                                    if (isNote) {
                                        return (
                                            <React.Fragment
                                                key={msg.id ?? `msg-${idx}`}
                                            >
                                                {showDivider && (
                                                    <div className="flex items-center gap-2 my-1">
                                                        <div className="flex-1 h-px bg-[#427425]/30" />
                                                        <span className="text-[10px] font-semibold text-[#427425] bg-[#e6f3d8] px-2 py-0.5 rounded-full whitespace-nowrap">
                                                            {snap} new{" "}
                                                            {snap === 1
                                                                ? "message"
                                                                : "messages"}
                                                        </span>
                                                        <div className="flex-1 h-px bg-[#427425]/30" />
                                                    </div>
                                                )}
                                                <div className="flex justify-center">
                                                    <div className="max-w-[85%] w-full rounded-xl px-3 py-2 bg-amber-50 border border-amber-200 border-dashed">
                                                        <div className="flex items-center gap-1.5 mb-1">
                                                            <span className="text-amber-500 text-xs">
                                                                📝
                                                            </span>
                                                            <span className="text-[10px] font-semibold text-amber-600 uppercase tracking-wide">
                                                                Internal Note
                                                            </span>
                                                        </div>
                                                        <p className="text-xs text-amber-800 leading-relaxed whitespace-pre-wrap">
                                                            {msg.text}
                                                        </p>
                                                        <div className="text-[10px] text-amber-400 mt-1">
                                                            {msg.created_at
                                                                ? timeAgo(
                                                                      msg.created_at,
                                                                  )
                                                                : ""}
                                                        </div>
                                                    </div>
                                                </div>
                                            </React.Fragment>
                                        );
                                    }

                                    return (
                                        <React.Fragment
                                            key={msg.id ?? `msg-${idx}`}
                                        >
                                            {showDivider && (
                                                <div className="flex items-center gap-2 my-1">
                                                    <div className="flex-1 h-px bg-[#427425]/30" />
                                                    <span className="text-[10px] font-semibold text-[#427425] bg-[#e6f3d8] px-2 py-0.5 rounded-full whitespace-nowrap">
                                                        {snap} new{" "}
                                                        {snap === 1
                                                            ? "message"
                                                            : "messages"}
                                                    </span>
                                                    <div className="flex-1 h-px bg-[#427425]/30" />
                                                </div>
                                            )}
                                            <div
                                                className={`flex ${isInbound ? "justify-start" : "justify-end"}`}
                                                {...makeSwipeHandlers(msg)}
                                            >
                                                <div
                                                    className={`rounded-2xl text-xs ${
                                                        (msg as any)
                                                            .media_type &&
                                                        (msg as any)
                                                            .media_type !==
                                                            "note" &&
                                                        (msg as any)
                                                            .media_url &&
                                                        (msg as any).media_type
                                                            .startsWith
                                                            ? "p-1.5 max-w-[65%]"
                                                            : "px-4 py-2.5 max-w-[75%]"
                                                    } ${
                                                        isInbound
                                                            ? "bg-white text-[#1c2917] rounded-tl-sm"
                                                            : msg.sender ===
                                                                "ai"
                                                              ? "bg-[#1e293b] text-white rounded-tr-sm"
                                                              : "bg-[#2ad113] text-[#0a2e05] rounded-tr-sm"
                                                    }`}
                                                    style={{
                                                        border: isInbound ? "1px solid #edf0ea" : "none",
                                                        boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
                                                    }}
                                                >
                                                    {!isInbound && (
                                                        <div className="text-[10px] opacity-70 mb-1 font-medium uppercase tracking-wide">
                                                            {msg.sender === "ai"
                                                                ? "AI"
                                                                : (msg as any)
                                                                        .agent_name
                                                                  ? (msg as any)
                                                                        .agent_name
                                                                  : "Agent"}
                                                        </div>
                                                    )}
                                                    {/* Quoted message this bubble replies to */}
                                                    {msg.reply_to && (() => {
                                                        // WhatsApp-style quote: text left, and when the quoted
                                                        // message is an image, its real thumbnail on the right —
                                                        // never an "[image]" placeholder.
                                                        const qImg = msg.reply_to.media_type === "image" && msg.reply_to.media_url
                                                            ? msg.reply_to.media_url : null;
                                                        const rawQ = (msg.reply_to.text || "").trim();
                                                        const qText = rawQ && rawQ !== "[image]"
                                                            ? rawQ
                                                            : qImg ? "📷 Photo"
                                                            : msg.reply_to.media_type ? `[${msg.reply_to.media_type}]` : "(media)";
                                                        return (
                                                        <div
                                                            className="mb-1.5 pl-2 pr-1 rounded-sm border-l-2 flex items-center gap-2"
                                                            style={{
                                                                borderColor: isInbound ? "#589b31" : "rgba(255,255,255,0.55)",
                                                                backgroundColor: isInbound ? "#f2f7ee" : "rgba(255,255,255,0.14)",
                                                            }}
                                                        >
                                                            <div className="flex-1 min-w-0">
                                                                <div className="text-[9px] font-semibold uppercase tracking-wide opacity-70 px-1 pt-0.5">
                                                                    {msg.reply_to.sender === "user"
                                                                        ? "Customer"
                                                                        : msg.reply_to.sender === "ai"
                                                                          ? "Neema"
                                                                          : "You"}
                                                                </div>
                                                                <div className="text-[11px] opacity-80 px-1 pb-1 whitespace-pre-wrap line-clamp-2">
                                                                    {qText}
                                                                </div>
                                                            </div>
                                                            {qImg && (
                                                                <img
                                                                    src={qImg}
                                                                    alt="quoted"
                                                                    className="w-10 h-10 rounded object-cover flex-shrink-0 my-1 mr-0.5"
                                                                />
                                                            )}
                                                        </div>
                                                        );
                                                    })()}
                                                    {(() => {
                                                        // ── Facebook/IG comment ──
                                                        // Show the source-post card
                                                        // so the agent knows what the
                                                        // comment is replying to. Also
                                                        // covers legacy rows whose text
                                                        // still carries a "[comment]"
                                                        // prefix (no context captured).
                                                        const cctx = (msg as any)
                                                            .comment_context as
                                                            | {
                                                                  post_id?: string;
                                                                  title?: string;
                                                                  permalink?: string;
                                                                  thumb?: string;
                                                                  media_type?: string;
                                                                  has_video?: boolean;
                                                                  reply_to?: string;
                                                              }
                                                            | null
                                                            | undefined;
                                                        const rawText = msg.text ?? "";
                                                        // Our public reply to a comment: render it threaded
                                                        // (↳ indented) so it reads as a reply under the comment.
                                                        if (cctx?.reply_to) {
                                                            return (
                                                                <div className="flex gap-1.5 pl-2 border-l-2 border-amber-300/60">
                                                                    <span className="text-amber-400 select-none">↳</span>
                                                                    <p className="leading-relaxed whitespace-pre-wrap">
                                                                        {formatWa(msg.text)}
                                                                    </p>
                                                                </div>
                                                            );
                                                        }
                                                        // An inbound comment: the source-post card + the comment.
                                                        const isComment =
                                                            !!(cctx && (cctx.title || cctx.post_id)) ||
                                                            rawText.startsWith("[comment]");
                                                        if (isComment) {
                                                            const body = rawText.replace(
                                                                /^\[comment\]\s*/,
                                                                "",
                                                            );
                                                            return (
                                                                <div className="flex flex-col gap-1.5">
                                                                    {cctx && (cctx.title || cctx.post_id) && (
                                                                        <CommentContextCard
                                                                            ctx={cctx}
                                                                            isInbound={isInbound}
                                                                            channel={activeConv?.channel}
                                                                        />
                                                                    )}
                                                                    {body && (
                                                                        <p className="leading-relaxed whitespace-pre-wrap">
                                                                            {formatWa(body)}
                                                                        </p>
                                                                    )}
                                                                </div>
                                                            );
                                                        }
                                                        const mt = (msg as any)
                                                            .media_type as
                                                            | string
                                                            | null
                                                            | undefined;
                                                        const mu = (msg as any)
                                                            .media_url as
                                                            | string
                                                            | null
                                                            | undefined;
                                                        if (!mt || !mu) {
                                                            // A media message whose URL never landed would
                                                            // otherwise show as a bare "[image]" — say what
                                                            // was sent and offer to fetch it back.
                                                            const kind = mt === "video" ? "video"
                                                                : mt === "image" ? "image" : null;
                                                            if (kind && !mu) {
                                                                return (
                                                                    <MediaFallback
                                                                        kind={kind}
                                                                        messageId={String(msg.id)}
                                                                        isInbound={isInbound}
                                                                        onRecovered={() => { if (activeConvId) loadMessages(activeConvId, true); }}
                                                                    />
                                                                );
                                                            }
                                                            if (!rawText.trim()) {
                                                                // A truly empty row (a message type the
                                                                // ingester couldn't extract) must never
                                                                // render as a blank bubble.
                                                                return (
                                                                    <p className="leading-relaxed italic text-stone-400">
                                                                        Message can&apos;t be displayed (unsupported type) — ask them to resend as text.
                                                                    </p>
                                                                );
                                                            }
                                                            return (
                                                                <p className="leading-relaxed whitespace-pre-wrap">
                                                                    {formatWa(msg.text)}
                                                                </p>
                                                            );
                                                        }
                                                        if (
                                                            mt === "image" ||
                                                            mt.startsWith?.(
                                                                "image/",
                                                            )
                                                        ) {
                                                            if (album?.lead) {
                                                                const items = albumItemsOf(album.items);
                                                                return (
                                                                    <AlbumGrid
                                                                        items={items}
                                                                        onOpen={(i) => setAlbumViewer({ items, start: i })}
                                                                    />
                                                                );
                                                            }
                                                            // media_caption = GPT-4o image analysis
                                                            // (Product Image Recognition sub-workflow).
                                                            // msg.text = customer's own caption only.
                                                            //
                                                            // Guard: suppress imgCaption when msg.text
                                                            // is identical to media_caption, or starts
                                                            // with the analysis content. This happens on
                                                            // legacy rows where the analysis leaked into
                                                            // the text field before the field-mapping fix.
                                                            // In that case the analysis should only appear
                                                            // via the collapsible toggle, never as a
                                                            // visible caption below the image.
                                                            const imgAnalysis =
                                                                ((msg as any).media_caption as
                                                                    | string
                                                                    | null
                                                                    | undefined) ?? null;
                                                            const rawText = msg.text ?? "";
                                                            const imgCaption = (() => {
                                                                if (!rawText) return null;
                                                                // Bracket placeholders are never real captions
                                                                if (rawText.startsWith("[")) return null;
                                                                // Text IS the analysis — no user caption was added
                                                                if (imgAnalysis && rawText.trim() === imgAnalysis.trim()) return null;
                                                                // Text STARTS WITH the analysis — legacy leak
                                                                if (imgAnalysis && rawText.trim().startsWith(imgAnalysis.trim().slice(0, 40))) return null;
                                                                return rawText;
                                                            })();
                                                            return (
                                                                <ImageBubble
                                                                    src={mu}
                                                                    analysis={imgAnalysis}
                                                                    caption={imgCaption}
                                                                    isInbound={isInbound}
                                                                    messageId={String(msg.id)}
                                                                />
                                                            );
                                                        }
                                                        if (
                                                            mt === "video" ||
                                                            mt.startsWith?.(
                                                                "video/",
                                                            )
                                                        ) {
                                                            return (
                                                                <VideoBubble
                                                                    src={mu}
                                                                    caption={msg.text && !msg.text.startsWith("[") ? msg.text : null}
                                                                    isInbound={isInbound}
                                                                    messageId={String(msg.id)}
                                                                />
                                                            );
                                                        }
                                                        if (
                                                            mt === "audio" ||
                                                            mt.startsWith?.(
                                                                "audio/",
                                                            )
                                                        ) {
                                                            // inbound : transcription = msg.text
                                                            //   patch_message writes the Whisper transcript
                                                            //   to msg.text after transcription completes.
                                                            // outbound: text    = full AI reply (transcript label)
                                                            //           caption = cart summary
                                                            const transcription = isInbound
                                                                ? (msg.text && !msg.text.startsWith("[") ? msg.text : null)
                                                                : (msg.text && !msg.text.startsWith("[") ? msg.text : null);
                                                            const cartText = !isInbound
                                                                ? ((msg as any).media_caption as string | null | undefined) ?? null
                                                                : null;
                                                            return (
                                                                <AudioBubble
                                                                    src={mu}
                                                                    transcription={transcription}
                                                                    cartText={cartText}
                                                                    isInbound={isInbound}
                                                                />
                                                            );
                                                        }
                                                        const fileName =
                                                            msg.text ||
                                                            mu
                                                                .split("/")
                                                                .pop() ||
                                                            "file";
                                                        return (
                                                            <a
                                                                href={mu}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                className={`flex items-center gap-2 px-3 py-2 rounded-xl border transition-opacity hover:opacity-80 ${
                                                                    isInbound
                                                                        ? "bg-white border-[#edf0ea] text-[#1c2917]"
                                                                        : "bg-white/20 border-white/30 text-white"
                                                                }`}
                                                            >
                                                                <svg
                                                                    className="w-5 h-5 flex-shrink-0 opacity-70"
                                                                    fill="none"
                                                                    stroke="currentColor"
                                                                    viewBox="0 0 24 24"
                                                                >
                                                                    <path
                                                                        strokeLinecap="round"
                                                                        strokeLinejoin="round"
                                                                        strokeWidth={
                                                                            1.5
                                                                        }
                                                                        d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"
                                                                    />
                                                                </svg>
                                                                <span className="text-xs font-medium truncate max-w-[160px]">
                                                                    {fileName}
                                                                </span>
                                                                <svg
                                                                    className="w-4 h-4 flex-shrink-0 opacity-60"
                                                                    fill="none"
                                                                    stroke="currentColor"
                                                                    viewBox="0 0 24 24"
                                                                >
                                                                    <path
                                                                        strokeLinecap="round"
                                                                        strokeLinejoin="round"
                                                                        strokeWidth={
                                                                            2
                                                                        }
                                                                        d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                                                                    />
                                                                </svg>
                                                            </a>
                                                        );
                                                    })()}
                                                    <div
                                                        className={`text-[10px] mt-1 flex items-center gap-2 ${isInbound ? "" : "opacity-60 justify-end"}`}
                                                        style={{ color: isInbound ? "#b5c9a8" : undefined }}
                                                    >
                                                        {msg.created_at
                                                            ? timeAgo(
                                                                  msg.created_at,
                                                              )
                                                            : ""}
                                                        {/* Reply to this message — a threaded
                                                            quote (native on WhatsApp). */}
                                                        {isInbound && (msg.text || "").trim() && (
                                                            <button
                                                                onClick={() => beginReplyTo(msg)}
                                                                title="Reply to this message"
                                                                className="text-[#b5c9a8] hover:text-[#f59e0b] font-medium"
                                                            >
                                                                ↩ Reply
                                                            </button>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>
                                        </React.Fragment>
                                    );
                                });
                            })()}
                            <div ref={messagesEndRef} />
                        </div>

                        {/* Reply box — shown when agent owns the conv, or is admin/superuser */}
                        {activeConv.intercept_mode === "human" &&
                            (activeConv.assigned_agent_id === currentAgentId ||
                                isAdminOrSuper) && (
                                <div className="px-4 py-3 bg-white" style={{ borderTop: "1px solid #edf0ea" }}>
                                    {/* ── AI Draft pill — shown when a draft exists but panel is collapsed */}
                                    {draftVisible && !draftExpanded && (
                                        <button
                                            onClick={() =>
                                                setDraftExpanded(true)
                                            }
                                            className="mb-2 w-full flex items-center gap-2 px-3 py-2 rounded-xl bg-blue-50 border border-blue-200 hover:bg-blue-100 transition-colors text-left"
                                        >
                                            <span className="text-blue-500 text-sm flex-shrink-0">
                                                🤖
                                            </span>
                                            <span className="text-xs font-semibold text-blue-700 flex-1">
                                                AI has a draft ready
                                            </span>
                                            <span className="text-[10px] text-blue-400 flex-shrink-0">
                                                Tap to review ↑
                                            </span>
                                        </button>
                                    )}

                                    {/* ── AI Draft panel — shown when expanded */}
                                    {draftVisible && draftExpanded && (
                                        <div className="mb-2 rounded-xl bg-blue-50 border border-blue-200 overflow-hidden">
                                            {/* Header */}
                                            <div className="flex items-center justify-between px-3 py-2 border-b border-blue-100">
                                                <div className="flex items-center gap-1.5">
                                                    <span className="text-blue-500 text-sm">
                                                        🤖
                                                    </span>
                                                    <p className="text-xs font-semibold text-blue-700">
                                                        AI Draft
                                                    </p>
                                                </div>
                                                <div className="flex items-center gap-1">
                                                    <button
                                                        onClick={() =>
                                                            setDraftEditing(
                                                                (e) => !e,
                                                            )
                                                        }
                                                        className="text-[10px] text-blue-500 hover:text-blue-700 px-2 py-0.5 rounded border border-blue-200 hover:border-blue-400 transition-colors"
                                                    >
                                                        {draftEditing
                                                            ? "Preview"
                                                            : "Edit"}
                                                    </button>
                                                    <button
                                                        onClick={() =>
                                                            setDraftExpanded(
                                                                false,
                                                            )
                                                        }
                                                        className="text-[10px] text-blue-400 hover:text-blue-600 px-1.5 py-0.5"
                                                        title="Collapse"
                                                    >
                                                        ↓
                                                    </button>
                                                    <button
                                                        onClick={() => {
                                                            setDraftVisible(
                                                                false,
                                                            );
                                                            setDraftExpanded(
                                                                false,
                                                            );
                                                            setDraftText("");
                                                            setDraftEditing(
                                                                false,
                                                            );
                                                        }}
                                                        className="text-[10px] text-blue-400 hover:text-blue-600 px-1.5 py-0.5"
                                                        title="Dismiss"
                                                    >
                                                        ✕
                                                    </button>
                                                </div>
                                            </div>
                                            {/* Body */}
                                            <div className="px-3 py-2">
                                                {draftEditing ? (
                                                    <textarea
                                                        value={draftText}
                                                        onChange={(e) =>
                                                            setDraftText(
                                                                e.target.value,
                                                            )
                                                        }
                                                        rows={4}
                                                        className="w-full text-xs text-blue-800 bg-white border border-blue-200 rounded-lg px-2.5 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-blue-400"
                                                        placeholder="Edit the draft…"
                                                    />
                                                ) : (
                                                    <p className="text-xs text-blue-700 whitespace-pre-wrap leading-relaxed">
                                                        {draftText ||
                                                            "AI has a reply ready."}
                                                    </p>
                                                )}
                                            </div>
                                            {/* Actions */}
                                            <div className="flex items-center gap-2 px-3 pb-2.5">
                                                <Btn
                                                    small
                                                    onClick={approveDraft}
                                                    variant="primary"
                                                >
                                                    ✓ Send
                                                </Btn>
                                                <Btn
                                                    small
                                                    onClick={() => {
                                                        setReplyText(draftText);
                                                        setDraftVisible(false);
                                                        setDraftExpanded(false);
                                                        setDraftText("");
                                                        setDraftEditing(false);
                                                    }}
                                                    variant="secondary"
                                                >
                                                    Edit & send manually
                                                </Btn>
                                                <Btn
                                                    small
                                                    onClick={() => {
                                                        setDraftVisible(false);
                                                        setDraftExpanded(false);
                                                        setDraftText("");
                                                        setDraftEditing(false);
                                                    }}
                                                    variant="ghost"
                                                >
                                                    Dismiss
                                                </Btn>
                                            </div>
                                        </div>
                                    )}

                                    {/* ── Generate draft button — shown when no draft exists */}
                                    {!draftVisible &&
                                        activeConv.intercept_mode ===
                                            "human" && (
                                            <div className="mb-2 flex justify-end">
                                                <button
                                                    onClick={generateDraft}
                                                    disabled={generatingDraft}
                                                    className="flex items-center gap-1.5 h-7 px-3 text-xs font-medium rounded-lg border border-blue-200 text-blue-600 hover:bg-blue-50 disabled:opacity-50 transition-colors"
                                                >
                                                    {generatingDraft ? (
                                                        <>
                                                            <div className="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                                                            Generating…
                                                        </>
                                                    ) : (
                                                        <>
                                                            🤖 Generate AI draft
                                                        </>
                                                    )}
                                                </button>
                                            </div>
                                        )}

                                    {/* Reply preview — the message we're answering. */}
                                    {quoted && (
                                        <div className="flex items-start gap-2 mb-2 px-3 py-2 rounded-lg bg-[#f1f5f9] border-l-2 border-[#f59e0b]">
                                            <div className="flex-1 min-w-0">
                                                <span className="text-[10px] font-semibold text-[#f59e0b] uppercase tracking-wide">
                                                    {quoted.msgId
                                                        ? `Replying to ${quoted.sender === "user" ? "Customer" : quoted.sender === "ai" ? "Neema" : "you"}`
                                                        : `Replying to ${CHANNEL_CONFIG[quoted.channel as Channel]?.label ?? quoted.channel}`}
                                                </span>
                                                <p className="text-xs text-[#475569] truncate">
                                                    {quoted.text.trim() && quoted.text.trim() !== "[image]"
                                                        ? quoted.text
                                                        : quoted.mediaUrl ? "📷 Photo"
                                                        : quoted.mediaType ? `[${quoted.mediaType}]` : quoted.text}
                                                </p>
                                            </div>
                                            {quoted.mediaUrl && (
                                                <img src={quoted.mediaUrl} alt="quoted"
                                                     className="w-9 h-9 rounded object-cover flex-shrink-0" />
                                            )}
                                            <button
                                                onClick={() => setQuoted(null)}
                                                title="Remove quote"
                                                className="text-[#94a3b8] hover:text-[#475569] text-sm leading-none flex-shrink-0"
                                            >✕</button>
                                        </div>
                                    )}

                                    {/* Messaging-window state — say it BEFORE a reply
                                        is typed that Meta would refuse. */}
                                    {window24 && window24.mode !== "n/a" && (
                                        <WindowStrip win={window24} />
                                    )}

                                    <div className="flex gap-2 items-end">
                                        {/* Hidden file input */}
                                        <input
                                            ref={fileInputRef}
                                            type="file"
                                            accept={ACCEPT_TYPES}
                                            multiple
                                            className="hidden"
                                            onChange={handleFileSelect}
                                        />
                                        {/* Paperclip attach button */}
                                        <button
                                            onClick={() =>
                                                fileInputRef.current?.click()
                                            }
                                            title="Attach images or files (up to 5 MB each for images)"
                                            className="h-10 w-10 rounded-xl bg-[#f1f3f5] hover:bg-[#e5e8eb] flex items-center justify-center text-[#64748b] transition-colors flex-shrink-0"
                                        >
                                            <svg
                                                className="w-4 h-4"
                                                fill="none"
                                                stroke="currentColor"
                                                viewBox="0 0 24 24"
                                            >
                                                <path
                                                    strokeLinecap="round"
                                                    strokeLinejoin="round"
                                                    strokeWidth={2}
                                                    d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
                                                />
                                            </svg>
                                        </button>
                                        <textarea
                                            value={replyText}
                                            onChange={(e) =>
                                                setReplyText(e.target.value)
                                            }
                                            onKeyDown={(e) => {
                                                if (
                                                    e.key === "Enter" &&
                                                    !e.shiftKey
                                                ) {
                                                    e.preventDefault();
                                                    sendReply();
                                                }
                                            }}
                                            placeholder="Type a reply… (Enter to send)"
                                            rows={2}
                                            className="flex-1 resize-none px-3 py-2 text-sm rounded-xl focus:outline-none focus:ring-2 focus:ring-[#f59e0b] focus:border-transparent"
                                            style={{
                                                backgroundColor: "#f8fafc",
                                                border: "1px solid #e2e8f0",
                                                color: "#1c2917",
                                            }}
                                        />
                                        <button
                                            onClick={sendReply}
                                            disabled={
                                                !replyText.trim() || sending ||
                                                window24?.mode === "closed"
                                            }
                                            title={window24?.mode === "closed"
                                                ? (window24.reason || "Outside the messaging window")
                                                : "Send"}
                                            className="h-10 w-10 rounded-xl disabled:opacity-50 flex items-center justify-center text-white transition-colors"
                                            style={{ backgroundColor: "#f59e0b" }}
                                            onMouseEnter={(e) => { if (!(!replyText.trim() || sending)) (e.currentTarget as HTMLElement).style.backgroundColor = "#d97706"; }}
                                            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "#f59e0b"; }}
                                        >
                                            {sending ? (
                                                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                                            ) : (
                                                <svg
                                                    className="w-4 h-4"
                                                    fill="none"
                                                    stroke="currentColor"
                                                    viewBox="0 0 24 24"
                                                >
                                                    <path
                                                        strokeLinecap="round"
                                                        strokeLinejoin="round"
                                                        strokeWidth={2}
                                                        d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
                                                    />
                                                </svg>
                                            )}
                                        </button>
                                    </div>

                                    {/* Media attachment preview panel (multi-select) */}
                                    {mediaItems.length > 0 && (
                                        <div className="mt-2 p-2.5 rounded-xl space-y-2" style={{ backgroundColor: "#f5f7f2", border: "1px solid #e8ebe3" }}>
                                            {/* Per-file rows — each with its OWN caption (WhatsApp-style) */}
                                            <div className="space-y-2">
                                                {mediaItems.map((it) => (
                                                    <div key={it.id} className="flex items-center gap-2">
                                                        <div className="relative flex-shrink-0">
                                                            {it.previewUrl ? (
                                                                <img
                                                                    src={it.previewUrl}
                                                                    alt={it.file.name}
                                                                    title={it.file.name}
                                                                    className="w-14 h-14 rounded-lg object-cover border border-[#edf0ea]"
                                                                />
                                                            ) : (
                                                                <div className="w-14 h-14 rounded-lg flex flex-col items-center justify-center gap-0.5 px-1" style={{ backgroundColor: "#e8ebe3" }} title={it.file.name}>
                                                                    <svg className="w-5 h-5" style={{ color: "#8a9e80" }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                                                                    </svg>
                                                                    <span className="text-[9px] leading-tight text-[#5f6f57] truncate max-w-[52px]">{it.file.name}</span>
                                                                </div>
                                                            )}
                                                            <button
                                                                onClick={() => removeMediaItem(it.id)}
                                                                disabled={uploadingMedia}
                                                                title="Remove"
                                                                className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-[#1c2917] text-white text-xs leading-none flex items-center justify-center shadow disabled:opacity-40 hover:bg-black"
                                                            >
                                                                ✕
                                                            </button>
                                                        </div>
                                                        <input
                                                            value={it.caption}
                                                            onChange={(e) => updateMediaCaption(it.id, e.target.value)}
                                                            disabled={uploadingMedia}
                                                            placeholder="Add a caption (optional)…"
                                                            className="flex-1 min-w-0 px-2 py-1.5 text-xs rounded-lg focus:outline-none focus:ring-1 focus:ring-[#589b31]"
                                                            style={{ backgroundColor: "#ffffff", border: "1px solid #e8ebe3", color: "#1c2917" }}
                                                        />
                                                    </div>
                                                ))}
                                                {/* Add-more tile */}
                                                <button
                                                    onClick={() => fileInputRef.current?.click()}
                                                    disabled={uploadingMedia}
                                                    title="Add more"
                                                    className="w-14 h-14 rounded-lg border border-dashed border-[#c7cec0] flex items-center justify-center text-[#8a9e80] hover:bg-[#eef1ea] disabled:opacity-40"
                                                >
                                                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                                                    </svg>
                                                </button>
                                            </div>

                                            <div className="flex items-center gap-1.5">
                                                <button
                                                    onClick={sendMedia}
                                                    disabled={uploadingMedia}
                                                    className="flex items-center gap-1 h-7 px-3 disabled:opacity-50 text-white text-xs font-medium rounded-lg transition-colors"
                                                    style={{ backgroundColor: "#589b31" }}
                                                >
                                                    {uploadingMedia ? (
                                                        <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                                                    ) : (
                                                        <>
                                                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                                                            </svg>
                                                            {mediaItems.length > 1 ? `Send ${mediaItems.length}` : "Send"}
                                                        </>
                                                    )}
                                                </button>
                                                <button
                                                    onClick={clearMediaAttachment}
                                                    disabled={uploadingMedia}
                                                    className="h-7 px-3 text-xs rounded-lg transition-colors disabled:opacity-40"
                                                    style={{ color: "#8a9e80", border: "1px solid #e8ebe3" }}
                                                >
                                                    Cancel
                                                </button>
                                                <span className="ml-auto text-[10px] text-[#8a9e80]">
                                                    Images up to 5 MB each
                                                </span>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}

                        {/* Lock banner */}
                        {activeConv.intercept_mode === "human" &&
                        activeConv.assigned_agent_id &&
                        activeConv.assigned_agent_id !== currentAgentId &&
                        !isAdminOrSuper ? (
                            <div className="px-4 py-4 flex items-center justify-center gap-2" style={{ borderTop: "1px solid #edf0ea", backgroundColor: "#fafbf8" }}>
                                <span className="text-base">🔒</span>
                                <p className="text-xs" style={{ color: "#8a9e80" }}>
                                    Handled by{" "}
                                    <strong style={{ color: "#589b31" }}>
                                        {activeConv.assigned_agent_name ??
                                            "another agent"}
                                    </strong>{" "}
                                    — ask them to release or transfer it to you
                                </p>
                            </div>
                        ) : null}
                    </>
                )}
            </div>
            {/* Activity Log — collapsible, desktop only */}
            {activeConv && !isMobile && (() => {
                const dotColor: Record<string, string> = {
                    escalated:        "bg-amber-100 border-amber-300",
                    flag:             "bg-red-100 border-red-300",
                    intercept:        "bg-purple-100 border-purple-300",
                    release:          "bg-blue-100 border-blue-300",
                    transfer:         "bg-indigo-100 border-indigo-300",
                    approve_draft:    "bg-green-100 border-green-300",
                    checkin_planned:  "bg-sky-100 border-sky-300",
                    checkin_sent:     "bg-sky-200 border-sky-400",
                    checkin_vetoed:   "bg-stone-100 border-stone-300",
                    checkin_failed:   "bg-red-100 border-red-300",
                    deal:             "bg-emerald-100 border-emerald-300",
                    promise:          "bg-amber-100 border-amber-300",
                    order:            "bg-green-100 border-green-400",
                    call:             "bg-teal-100 border-teal-300",
                };

                if (!activityLogOpen) {
                    return (
                        <button
                            onClick={() => setActivityLogOpen(true)}
                            title="Show activity log"
                            className="flex-shrink-0 w-8 flex flex-col items-center justify-center gap-1 transition-colors"
                            style={{ borderLeft: "1px solid #edf0ea", backgroundColor: "#ffffff" }}
                            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "#fafbf8"; }}
                            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffffff"; }}
                        >
                            <svg
                                className="w-4 h-4"
                                style={{ color: "#c5d5bc" }}
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                            >
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M9 5l7 7-7 7"
                                />
                            </svg>
                            <span
                                className="text-[9px] font-semibold uppercase tracking-widest"
                                style={{
                                    color: "#c5d5bc",
                                    writingMode: "vertical-rl",
                                    transform: "rotate(180deg)",
                                }}
                            >
                                Activity
                            </span>
                            {activityEvents.length > 0 && (
                                <span className="w-4 h-4 rounded-full bg-amber-100 border border-amber-300 text-[8px] font-bold text-amber-700 flex items-center justify-center">
                                    {activityEvents.length > 20 ? "20+" : activityEvents.length}
                                </span>
                            )}
                        </button>
                    );
                }

                return (
                    <div
                        className="flex-shrink-0 flex flex-col overflow-hidden"
                        style={{ width: ACTIVITY_WIDTH, backgroundColor: "#ffffff", borderLeft: "1px solid #edf0ea" }}
                    >
                        {/* Header with collapse button */}
                        <div className="px-3 pt-3 pb-2 flex items-center justify-between" style={{ borderBottom: "1px solid #edf0ea" }}>
                            <p className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: "#b5c9a8" }}>
                                Activity log
                            </p>
                            <button
                                onClick={() => setActivityLogOpen(false)}
                                title="Collapse activity log"
                                className="w-5 h-5 rounded flex items-center justify-center transition-colors"
                                style={{ color: "#b5c9a8" }}
                                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "#f5f7f2"; }}
                                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; }}
                            >
                                <svg
                                    className="w-3.5 h-3.5"
                                    fill="none"
                                    stroke="currentColor"
                                    viewBox="0 0 24 24"
                                >
                                    <path
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                        strokeWidth={2}
                                        d="M9 5l7 7-7 7"
                                    />
                                </svg>
                            </button>
                        </div>

                        {activityEvents.length === 0 ? (
                            <div className="flex-1 flex items-center justify-center px-3">
                                <p className="text-[11px] text-stone-300 text-center leading-relaxed">
                                    No activity yet — pickups, check-ins, deals,
                                    orders and calls will appear here as the
                                    journey unfolds.
                                </p>
                            </div>
                        ) : (
                            <div className="flex-1 overflow-y-auto px-3 py-3 space-y-0">
                                {activityEvents.map((evt, i) => (
                                    <div key={evt.id} className="flex gap-2 pb-3 relative">
                                        {/* Connector line */}
                                        {i < activityEvents.length - 1 && (
                                            <div className="absolute left-[6px] top-4 bottom-0 w-px bg-stone-100" />
                                        )}
                                        {/* Dot */}
                                        <div
                                            className={`w-3.5 h-3.5 rounded-full border flex-shrink-0 mt-0.5 ${dotColor[evt.kind] ?? "bg-stone-100 border-stone-300"}`}
                                        />
                                        <div className="min-w-0">
                                            <p className="text-[11px] font-medium text-[#1c2917] leading-snug">
                                                {evt.label}
                                            </p>
                                            {evt.detail && (
                                                <p className="text-[10px] text-[#8fa383] mt-0.5 leading-snug break-words">
                                                    {evt.detail}
                                                </p>
                                            )}
                                            <p className="text-[10px] text-stone-400 mt-0.5">
                                                {timeAgo(evt.at)}
                                            </p>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                );
            })()}
            {/* CRM Sidebar — open by default, collapsible */}
            {activeConv &&
                !isMobile &&
                (crmOpen ? (
                    <CustomerSidebar
                        conversation={activeConv}
                        orders={orders}
                        onToast={onToast}
                        onClose={() => setCrmOpen(false)}
                        onOpenIdentity={openIdentityConversation}
                        onNameChange={(wa_id, newName) => {
                            setConversations((prev) =>
                                prev.map((c) =>
                                    c.wa_id === wa_id
                                        ? {
                                              ...c,
                                              name: newName,
                                              contact_name: newName,
                                          }
                                        : c,
                                ),
                            );
                        }}
                    />
                ) : (
                    <button
                        onClick={() => setCrmOpen(true)}
                        title="Show customer profile"
                        className="flex-shrink-0 w-8 flex flex-col items-center justify-center gap-1 transition-colors"
                        style={{ borderLeft: "1px solid #edf0ea", backgroundColor: "#ffffff" }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "#fafbf8"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "#ffffff"; }}
                    >
                        <svg
                            className="w-4 h-4"
                            style={{ color: "#c5d5bc" }}
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                        >
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M15 19l-7-7 7-7"
                            />
                        </svg>
                        <span
                            className="text-[9px] font-semibold uppercase tracking-widest"
                            style={{
                                color: "#c5d5bc",
                                writingMode: "vertical-rl",
                                transform: "rotate(180deg)",
                            }}
                        >
                            Customer
                        </span>
                    </button>
                ))}
        </div>
    );

    // Transfer modal
    const TransferModalEl = (
        <Modal
            show={transferModal}
            onClose={() => setTransferModal(false)}
            title="Transfer Conversation"
        >
            <p className="text-sm mb-3" style={{ color: "#8a9e80" }}>
                Select an agent to transfer this conversation to:
            </p>
            <div className="space-y-2 max-h-64 overflow-y-auto">
                {agents
                    .filter(
                        (a) =>
                            a.is_available &&
                            a.id !== activeConv?.assigned_agent_id,
                    )
                    .map((a) => (
                        <button
                            key={a.id}
                            onClick={() => transfer(a.id)}
                            className="w-full flex items-center gap-3 p-3 rounded-xl hover:bg-[#fafbf8] border border-[#edf0ea] transition-colors"
                        >
                            <Avatar name={a.name} size={32} />
                            <div className="text-left">
                                <div className="text-sm font-semibold text-[#1c2917]">
                                    {a.name}
                                </div>
                                <div className="text-xs text-[#b5c9a8]">
                                    {a.active_convs} active conversations
                                </div>
                            </div>
                        </button>
                    ))}
                {agents.filter((a) => a.is_available).length === 0 && (
                    <p className="text-sm text-[#b5c9a8] text-center py-4">
                        No available agents
                    </p>
                )}
            </div>
        </Modal>
    );

    const NoteModalEl = (
        <Modal
            show={noteModal}
            onClose={() => setNoteModal(false)}
            title="Add Note"
        >
            <TextareaField
                label="Note"
                value={noteText}
                onChange={(v) => setNoteText(v)}
                placeholder="Internal note (not sent to customer)…"
                rows={4}
            />
            <div className="flex gap-2">
                <Btn
                    onClick={async () => {
                        if (!noteText.trim() || !activeConvId) return;
                        const text = noteText.trim();
                        try {
                            const optimistic: Message = {
                                id: `optimistic-note-${Date.now()}`,
                                direction: "outbound",
                                sender: "human_agent",
                                text,
                                isNote: true,
                                created_at: new Date().toISOString(),
                            };
                            setMessages((m) => ({
                                ...m,
                                [activeConvId]: [
                                    ...(m[activeConvId] ?? []),
                                    optimistic,
                                ],
                            }));
                            setNoteModal(false);
                            setNoteText("");
                            onToast("Note saved");

                            await conversationsApi.addNote(activeConvId, text);
                            const msgs =
                                await conversationsApi.messages(activeConvId);
                            setMessages((m) => ({
                                ...m,
                                [activeConvId]: msgs,
                            }));
                        } catch {
                            setMessages((m) => ({
                                ...m,
                                [activeConvId]: (m[activeConvId] ?? []).filter(
                                    (msg) =>
                                        !msg.id?.startsWith("optimistic-note-"),
                                ),
                            }));
                            setNoteText(text);
                            setNoteModal(true);
                            onToast("Failed to save note", "error");
                        }
                    }}
                    variant="primary"
                >
                    Save Note
                </Btn>
                <Btn onClick={() => setNoteModal(false)} variant="outline">
                    Cancel
                </Btn>
            </div>
        </Modal>
    );

    const clearHistory = async () => {
        if (!activeConvId) return;
        setClearing(true);
        try {
            await conversationsApi.clearHistory(activeConvId);
            setMessages((m) => ({ ...m, [activeConvId]: [] }));
            setClearConfirm(false);
            refetchConversations?.();
            onToast("Chat history cleared");
        } catch (err: any) {
            onToast(
                err?.message?.includes("403")
                    ? "You don't have permission to clear chat history"
                    : "Failed to clear history",
                "error",
            );
        } finally {
            setClearing(false);
        }
    };

    const ClearHistoryModalEl = (
        <Modal
            show={clearConfirm}
            onClose={() => setClearConfirm(false)}
            title="Clear Chat History"
        >
            <p className="text-sm text-stone-600 mb-4">
                This will permanently delete all messages in this conversation.
                The conversation record and customer profile will be kept. This
                cannot be undone.
            </p>
            <div className="flex gap-2">
                <Btn
                    onClick={clearHistory}
                    variant="danger"
                    disabled={clearing}
                >
                    {clearing ? "Clearing…" : "Yes, clear history"}
                </Btn>
                <Btn onClick={() => setClearConfirm(false)} variant="outline">
                    Cancel
                </Btn>
            </div>
        </Modal>
    );

    if (isMobile) {
        return (
            <div className="flex-1 overflow-hidden flex flex-col">
                <div
                    className="flex flex-col flex-1 overflow-hidden"
                    style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
                >
                    {mobilePanel === "list" ? (
                        ConvList
                    ) : (
                        <div className="flex flex-col flex-1 overflow-hidden pb-16">
                            {ThreadPanel}
                        </div>
                    )}
                </div>
                {TransferModalEl}
                {NoteModalEl}
                {ClearHistoryModalEl}

                {/* Mobile CRM drawer — slides in from the right */}
                {mobileCrmOpen && activeConv && (
                    <div className="fixed inset-0 z-50 flex justify-end">
                        {/* Backdrop */}
                        <div
                            className="absolute inset-0 bg-black/40"
                            onClick={() => setMobileCrmOpen(false)}
                        />
                        {/* Drawer */}
                        <div className="relative bg-white w-full max-w-sm flex flex-col overflow-hidden shadow-xl">
                            {/* Header */}
                            <div className="flex items-center justify-between px-4 pt-4 pb-3 flex-shrink-0" style={{ borderBottom: "1px solid #edf0ea" }}>
                                <h2 className="text-sm font-semibold" style={{ color: "#1c2917" }}>
                                    Customer Profile
                                </h2>
                                <button
                                    onClick={() => setMobileCrmOpen(false)}
                                    className="w-7 h-7 rounded-full flex items-center justify-center transition-colors"
                                    style={{ backgroundColor: "#f5f7f2", color: "#589b31" }}
                                >
                                    <svg
                                        className="w-4 h-4"
                                        fill="none"
                                        stroke="currentColor"
                                        viewBox="0 0 24 24"
                                    >
                                        <path
                                            strokeLinecap="round"
                                            strokeLinejoin="round"
                                            strokeWidth={2}
                                            d="M6 18L18 6M6 6l12 12"
                                        />
                                    </svg>
                                </button>
                            </div>
                            <div className="overflow-y-auto flex-1 w-full">
                                <CustomerSidebar
                                    conversation={activeConv}
                                    orders={orders}
                                    onToast={onToast}
                                    onClose={() => setMobileCrmOpen(false)}
                                    onOpenIdentity={openIdentityConversation}
                                    className="w-full flex flex-col overflow-hidden"
                                    hideHeader
                                    onNameChange={(wa_id, newName) => {
                                        setConversations((prev) =>
                                            prev.map((c) =>
                                                c.wa_id === wa_id
                                                    ? {
                                                          ...c,
                                                          name: newName,
                                                          contact_name: newName,
                                                      }
                                                    : c,
                                            ),
                                        );
                                    }}
                                />
                            </div>
                        </div>
                    </div>
                )}
            </div>
        );
    }

    return (
        <div className="flex flex-1 overflow-hidden">
            {ConvList}
            {ThreadPanel}
            {TransferModalEl}
            {NoteModalEl}
            {ClearHistoryModalEl}

            {/* {typeof window !== "undefined" && (
                <div
                    style={{
                        background: "red",
                        color: "white",
                        fontSize: 11,
                        padding: "4px 8px",
                        position: "fixed",
                        bottom: 0,
                        left: 0,
                        zIndex: 9999,
                        maxWidth: "100vw",
                        wordBreak: "break-all",
                    }}
                >
                    id={currentAgentId ?? "none"} | role={currentRole ?? "none"}{" "}
                    | super={String(isSuperuser)} | canHandle=
                    {String(canHandleConversations)} | agent=
                    {JSON.stringify(currentAgent)} | me=
                    {(() => {
                        profileApi
                            .me()
                            .then((data) =>
                                console.log("profileApi.me():", data),
                            )
                            .catch((e) =>
                                console.error("profileApi.me() error:", e),
                            );
                        return "check console";
                    })()}
                </div>
            )} */}
            {albumViewer && (
                <AlbumViewer
                    items={albumViewer.items}
                    start={albumViewer.start}
                    onClose={() => setAlbumViewer(null)}
                />
            )}
        </div>
    );
}