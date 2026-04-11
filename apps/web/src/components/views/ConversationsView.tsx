import React, { useState, useRef, useEffect, useCallback } from "react";
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
import { timeAgo, formatPhone, displayName } from "@/lib/utils";
import { CHANNEL_CONFIG, ALL_CHANNELS } from "@/lib/channels";
import { conversationsApi, profileApi } from "@/lib/api";
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

type MobilePanel = "list" | "thread";

interface ConversationsViewProps extends SharedViewProps {
    conversations: Conversation[];
    setConversations: React.Dispatch<React.SetStateAction<Conversation[]>>;
    messages: MessagesMap;
    setMessages: React.Dispatch<React.SetStateAction<MessagesMap>>;
    agents: Agent[];
    orders?: Order[];
    refetchConversations?: () => void;
}

const CHANNEL_TABS: { id: "all" | Channel; label: string }[] = [
    { id: "all", label: "All" },
    { id: "whatsapp", label: "WhatsApp" },
    { id: "messenger", label: "Messenger" },
    { id: "instagram", label: "Instagram" },
    { id: "email", label: "Email" },
    { id: "sms", label: "SMS" },
];

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
}: ConversationsViewProps): React.ReactElement {
    const [activeConvId, setActiveConvId] = useState<string>("");
    const [mobilePanel, setMobilePanel] = useState<MobilePanel>("list");
    const [channelTab, setChannelTab] = useState<"all" | Channel>("all");
    const [tagFilter, setTagFilter] = useState<string>("all");
    const [interceptFilter, setInterceptFilter] = useState<
        "all" | "human" | "ai" | "paused"
    >("all");
    const [readFilter, setReadFilter] = useState<"all" | "unread" | "read">(
        "all",
    );
    const [searchQ, setSearchQ] = useState<string>("");
    const [replyText, setReplyText] = useState<string>("");
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
    const [crmOpen, setCrmOpen] = useState<boolean>(true);
    const [activityLogOpen, setActivityLogOpen] = useState<boolean>(false);
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

    // ── Media attachment state ────────────────────────────────────────────────
    const [mediaFile, setMediaFile] = useState<File | null>(null);
    const [mediaCaption, setMediaCaption] = useState<string>("");
    const [mediaPreviewUrl, setMediaPreviewUrl] = useState<string | null>(null);
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

    // ── Poll active thread every 10s as a WebSocket fallback ─────────────────
    useEffect(() => {
        if (!activeConvId) return;
        const timer = setInterval(() => {
            loadMessages(activeConvId, true);
        }, 10000);
        return () => clearInterval(timer);
    }, [activeConvId, loadMessages]);

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
                    // Avoid double-adding if a reload already persisted it
                    if (existing.some((x) => x.event_kind === sysEvt.event_kind &&
                        Math.abs(new Date(x.created_at).getTime() - new Date(sysEvt.created_at).getTime()) < 3000
                    )) return m;
                    return { ...m, [activeConvId]: [...existing, sysEvt] };
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
        const text = replyText;
        try {
            const optimisticMsg: Message = {
                id: `optimistic-${Date.now()}`,
                direction: "outbound",
                sender: "human_agent",
                text,
                created_at: new Date().toISOString(),
            };
            setMessages((m) => ({
                ...m,
                [activeConvId]: [...(m[activeConvId] ?? []), optimisticMsg],
            }));
            setReplyText("");
            await conversationsApi.sendReply(activeConvId, text);
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
        "video/mp4,video/3gpp," +
        "audio/ogg,audio/aac,audio/mpeg";

    const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        setMediaFile(file);
        if (file.type.startsWith("image/")) {
            setMediaPreviewUrl(URL.createObjectURL(file));
        } else {
            setMediaPreviewUrl(null);
        }
    };

    const clearMediaAttachment = () => {
        setMediaFile(null);
        setMediaCaption("");
        if (mediaPreviewUrl) URL.revokeObjectURL(mediaPreviewUrl);
        setMediaPreviewUrl(null);
        if (fileInputRef.current) fileInputRef.current.value = "";
    };

    const sendMedia = async () => {
        if (!mediaFile || !activeConvId) return;
        setUploadingMedia(true);
        try {
            const msg = await conversationsApi.uploadMedia(
                activeConvId,
                mediaFile,
                mediaCaption || undefined,
            );
            setMessages((m) => ({
                ...m,
                [activeConvId]: [...(m[activeConvId] ?? []), msg],
            }));
            clearMediaAttachment();
            refetchConversations?.();
            onToast("Media sent");
        } catch (err: any) {
            onToast(err?.message ?? "Failed to send media", "error");
        } finally {
            setUploadingMedia(false);
        }
    };

    // ── Filters ───────────────────────────────────────────────────────────────

    const channelCounts = CHANNEL_TABS.reduce<Record<string, number>>(
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
    );

    // Collect all unique tags across all conversations for the tag filter UI
    const allTags = Array.from(
        new Set(conversations.flatMap((c) => (c as any).tags ?? [])),
    ).sort() as string[];

    const unreadCount = conversations.filter((c) => c.unread > 0).length;

    const filteredConvs = conversations
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
                : new Date(a.created_at).getTime();
            const bTime = b.last_message_at
                ? new Date(b.last_message_at).getTime()
                : new Date(b.created_at).getTime();
            return bTime - aTime;
        });

    const humanCount = conversations.filter(
        (c) => c.intercept_mode === "human",
    ).length;

    // ── Render ────────────────────────────────────────────────────────────────

    const ConvList = (
        <div
            className="flex flex-col h-full bg-white"
            style={{
                width: isMobile ? "100%" : 288,
                minWidth: isMobile ? "100%" : 288,
                borderRight: "1px solid #edf0ea",
            }}
        >
            {/* Header */}
            <div className="px-4 pt-4 pb-3" style={{ borderBottom: "1px solid #edf0ea" }}>
                <div className="flex items-center justify-between mb-3">
                    <h1 className="text-sm font-semibold" style={{ color: "#1c2917", letterSpacing: "-0.01em" }}>
                        Chats
                    </h1>
                    <div className="flex items-center gap-2">
                        {humanCount > 0 && (
                            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: "#fff3cd", color: "#856404" }}>
                                {humanCount} live
                            </span>
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

                {/* Read / Unread toggle */}
                <div className="flex items-center gap-1 mb-2">
                    {(["all", "unread", "read"] as const).map((f) => (
                        <button
                            key={f}
                            onClick={() => setReadFilter(f)}
                            className={`flex-1 h-7 rounded-lg text-xs font-medium transition-colors flex items-center justify-center gap-1.5`}
                            style={{
                                backgroundColor: readFilter === f
                                    ? f === "unread" ? "#427425" : "#1c2917"
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

                {/* Channel tabs */}
                <div className="flex gap-1 overflow-x-auto scrollbar-none pb-1">
                    {CHANNEL_TABS.map((tab) => (
                        <button
                            key={tab.id}
                            onClick={() => setChannelTab(tab.id)}
                            className="flex-shrink-0 h-6 px-2.5 rounded-md text-xs font-medium transition-colors relative"
                            style={{
                                backgroundColor: channelTab === tab.id ? "#589b31" : "transparent",
                                color: channelTab === tab.id ? "#fff" : "#8a9e80",
                            }}
                        >
                            {tab.label}
                            {channelCounts[tab.id] > 0 && (
                                <span className="ml-1 text-[10px] bg-red-500 text-white px-1 rounded-full">
                                    {channelCounts[tab.id]}
                                </span>
                            )}
                        </button>
                    ))}
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
                {filteredConvs.map((conv) => {
                    const isActive = conv.id === activeConvId;
                    const hasUnread = conv.unread > 0;
                    const cfg = conv.channel
                        ? CHANNEL_CONFIG[conv.channel as Channel]
                        : null;
                    return (
                        <button
                            key={conv.id}
                            onClick={() => handleSelectConv(conv.id)}
                            className="w-full text-left px-4 py-3 transition-colors relative"
                            style={{
                                backgroundColor: isActive ? "#f5f7f2" : "transparent",
                                borderBottom: "1px solid #f2f4ef",
                                borderLeft: `3px solid ${isActive ? "#589b31" : hasUnread ? "#a8da8b" : "transparent"}`,
                            }}
                            onMouseEnter={(e) => {
                                if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = "#fafbf8";
                            }}
                            onMouseLeave={(e) => {
                                if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = "transparent";
                            }}
                        >
                            <div className="flex items-start gap-3">
                                <div className="relative flex-shrink-0">
                                    <Avatar
                                        name={displayName(
                                            conv.name,
                                            conv.wa_id,
                                        )}
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
                                    {/* Channel badge — bottom right */}
                                    {cfg && (
                                        <div
                                            className="absolute -bottom-0.5 -right-0.5 w-4 h-4 rounded-full flex items-center justify-center text-white text-[9px]"
                                            style={{
                                                backgroundColor: cfg.color,
                                            }}
                                        >
                                            {cfg.icon}
                                        </div>
                                    )}
                                    {/* Unread pulse dot on avatar */}
                                    {hasUnread && (
                                        <span className="absolute -top-0.5 -left-0.5 w-2.5 h-2.5 bg-[#427425] rounded-full border-2 border-white" />
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
                                            {displayName(conv.name, conv.wa_id)}
                                        </span>
                                        <span
                                            className="text-[10px] flex-shrink-0 ml-2"
                                            style={{
                                                fontWeight: hasUnread ? 600 : 400,
                                                color: hasUnread ? "#427425" : "#b5c9a8",
                                            }}
                                        >
                                            {conv.last_message_at
                                                ? timeAgo(conv.last_message_at)
                                                : ""}
                                        </span>
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <p
                                            className="text-xs truncate flex-1"
                                            style={{
                                                color: hasUnread ? "#3d5a30" : "#8a9e80",
                                                fontWeight: hasUnread ? 500 : 400,
                                            }}
                                        >
                                            {conv.last_message ??
                                                "No messages yet"}
                                        </p>
                                        <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                                            {conv.intercept_mode !== "ai" && (
                                                <div className="flex items-center gap-1">
                                                    <InterceptBadge
                                                        mode={
                                                            conv.intercept_mode
                                                        }
                                                    />
                                                    {conv.intercept_mode ===
                                                        "human" &&
                                                        conv.assigned_agent_id && (
                                                            <span
                                                                className={`text-[10px] font-medium truncate max-w-[64px] ${
                                                                    conv.assigned_agent_id ===
                                                                    currentAgentId
                                                                        ? "text-[#427425]"
                                                                        : "text-amber-600"
                                                                }`}
                                                            >
                                                                {conv.assigned_agent_id ===
                                                                currentAgentId
                                                                    ? "● Yours"
                                                                    : `🔒 ${conv.assigned_agent_name?.split(" ")[0] || "Agent"}`}
                                                            </span>
                                                        )}
                                                </div>
                                            )}
                                            {hasUnread && (
                                                <span className="min-w-[18px] h-[18px] px-1 text-white text-[10px] font-bold rounded-full flex items-center justify-center" style={{ backgroundColor: "#589b31" }}>
                                                    {conv.unread > 99
                                                        ? "99+"
                                                        : conv.unread}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </button>
                    );
                })}
            </div>
        </div>
    );

    const ThreadPanel = (
        <div className="flex flex-1 overflow-hidden">
            <div className="flex flex-col flex-1 overflow-hidden relative" style={{ backgroundColor: "#f9faf7" }}>
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
                                size={32}
                            />
                            <div className="flex-1 min-w-0">
                                <div className="text-sm font-semibold truncate" style={{ color: "#1c2917" }}>
                                    {displayName(
                                        activeConv.name,
                                        activeConv.wa_id,
                                    )}
                                </div>
                                <div className="text-xs truncate" style={{ color: "#b5c9a8", fontFamily: "'JetBrains Mono', monospace" }}>
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
                                return activeMessages.map((msg, idx) => {
                                    const isInbound =
                                        msg.direction === "inbound";
                                    const isNote = msg.isNote;
                                    const showDivider =
                                        idx === dividerIdx && snap > 0;

                                    // ── System event card ────────────────────
                                    if (msg.type === "system_event") {
                                        const kind = msg.event_kind ?? "";

                                        // ── Escalated card ───────────────────
                                        // Shown when AI cannot handle (customer
                                        // request or media received).  Gives full
                                        // context so the agent understands why.
                                        if (kind === "escalated") {
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
                                                    <div className="flex justify-center my-3">
                                                        <div className="w-full max-w-[88%] rounded-2xl overflow-hidden border border-amber-200 bg-amber-50">
                                                            {/* Header bar */}
                                                            <div className="flex items-center gap-2 px-3 py-2 bg-amber-100 border-b border-amber-200">
                                                                <span className="text-amber-600 text-sm leading-none">⚠</span>
                                                                <span className="text-[11px] font-semibold text-amber-800 uppercase tracking-wide">
                                                                    Escalated — awaiting agent
                                                                </span>
                                                                <span className="ml-auto text-[10px] text-amber-500">
                                                                    {msg.created_at ? timeAgo(msg.created_at) : ""}
                                                                </span>
                                                            </div>
                                                            {/* Reason body */}
                                                            {msg.event_reason && (
                                                                <div className="px-3 py-2">
                                                                    <p className="text-[10px] font-semibold text-amber-700 uppercase tracking-wide mb-1">
                                                                        Reason
                                                                    </p>
                                                                    <p className="text-xs text-amber-900 leading-relaxed">
                                                                        {msg.event_reason}
                                                                    </p>
                                                                </div>
                                                            )}
                                                            {/* Waiting indicator */}
                                                            <div className="flex items-center gap-1.5 px-3 py-2 border-t border-amber-100">
                                                                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                                                                <span className="text-[10px] text-amber-600">
                                                                    Waiting for an agent to pick up
                                                                </span>
                                                            </div>
                                                        </div>
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
                                                        <span className="text-[10px] font-semibold px-2.5 py-1 rounded-full bg-red-100 text-red-700 whitespace-nowrap">
                                                            🚩 Flagged: Needs Attention
                                                        </span>
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
                                                // Derive a human-readable reason from
                                                // event_reason if the backend wrote one,
                                                // otherwise fall back to context from the
                                                // surrounding messages.
                                                const hasInboundMedia = activeMessages
                                                    .slice(0, idx)
                                                    .some(
                                                        (m) =>
                                                            m.direction === "inbound" &&
                                                            m.media_type &&
                                                            m.media_type !== "note",
                                                    );
                                                const reasonText =
                                                    msg.event_reason ||
                                                    (hasInboundMedia
                                                        ? "Customer sent a media file that the AI cannot process. An agent needs to review and respond."
                                                        : "Customer requested media or the AI could not continue. An agent needs to take over.");

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
                                                        <div className="flex justify-center my-3">
                                                            <div className="w-full max-w-[88%] rounded-2xl overflow-hidden border border-amber-200 bg-amber-50">
                                                                <div className="flex items-center gap-2 px-3 py-2 bg-amber-100 border-b border-amber-200">
                                                                    <span className="text-amber-600 text-sm leading-none">⚠</span>
                                                                    <span className="text-[11px] font-semibold text-amber-800 uppercase tracking-wide">
                                                                        Escalated — awaiting agent
                                                                    </span>
                                                                    <span className="ml-auto text-[10px] text-amber-500">
                                                                        {msg.created_at ? timeAgo(msg.created_at) : ""}
                                                                    </span>
                                                                </div>
                                                                <div className="px-3 py-2">
                                                                    <p className="text-[10px] font-semibold text-amber-700 uppercase tracking-wide mb-1">
                                                                        Reason
                                                                    </p>
                                                                    <p className="text-xs text-amber-900 leading-relaxed">
                                                                        {reasonText}
                                                                    </p>
                                                                </div>
                                                                <div className="flex items-center gap-1.5 px-3 py-2 border-t border-amber-100">
                                                                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                                                                    <span className="text-[10px] text-amber-600">
                                                                        Waiting for an agent to pick up
                                                                    </span>
                                                                </div>
                                                            </div>
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
                                                    <span className={`text-[10px] font-semibold px-2.5 py-1 rounded-full border whitespace-nowrap ${pillStyle}`}>
                                                        {msg.text}
                                                    </span>
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
                                                              ? "bg-[#2a48a2] text-white rounded-tr-sm"
                                                              : "bg-[#2c7a1e] text-white rounded-tr-sm"
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
                                                    {(() => {
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
                                                            return (
                                                                <p className="leading-relaxed whitespace-pre-wrap">
                                                                    {msg.text}
                                                                </p>
                                                            );
                                                        }
                                                        if (
                                                            mt === "image" ||
                                                            mt.startsWith?.(
                                                                "image/",
                                                            )
                                                        ) {
                                                            return (
                                                                <div className="space-y-1">
                                                                    <a
                                                                        href={
                                                                            mu
                                                                        }
                                                                        target="_blank"
                                                                        rel="noopener noreferrer"
                                                                    >
                                                                        <img
                                                                            src={
                                                                                mu
                                                                            }
                                                                            alt={
                                                                                msg.text ||
                                                                                "image"
                                                                            }
                                                                            className="max-w-full rounded-xl border border-black/10 object-cover"
                                                                            style={{
                                                                                maxHeight: 240,
                                                                            }}
                                                                        />
                                                                    </a>
                                                                    {msg.text &&
                                                                        !msg.text.startsWith(
                                                                            "[",
                                                                        ) && (
                                                                            <p className="text-xs px-1 leading-relaxed">
                                                                                {
                                                                                    msg.text
                                                                                }
                                                                            </p>
                                                                        )}
                                                                </div>
                                                            );
                                                        }
                                                        if (
                                                            mt === "video" ||
                                                            mt.startsWith?.(
                                                                "video/",
                                                            )
                                                        ) {
                                                            return (
                                                                <div className="space-y-1">
                                                                    <video
                                                                        src={mu}
                                                                        controls
                                                                        className="max-w-full rounded-xl border border-black/10"
                                                                        style={{
                                                                            maxHeight: 200,
                                                                        }}
                                                                    />
                                                                    {msg.text &&
                                                                        !msg.text.startsWith(
                                                                            "[",
                                                                        ) && (
                                                                            <p className="text-xs px-1 leading-relaxed">
                                                                                {
                                                                                    msg.text
                                                                                }
                                                                            </p>
                                                                        )}
                                                                </div>
                                                            );
                                                        }
                                                        if (
                                                            mt === "audio" ||
                                                            mt.startsWith?.(
                                                                "audio/",
                                                            )
                                                        ) {
                                                            // inbound : caption = Whisper transcription
                                                            // outbound: text    = full AI reply (transcript label)
                                                            //           caption = cart summary
                                                            const transcription = isInbound
                                                                ? ((msg as any).media_caption as string | null | undefined) ?? null
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
                                                        className={`text-[10px] mt-1 ${isInbound ? "" : "opacity-60"}`}
                                                        style={{ color: isInbound ? "#b5c9a8" : undefined }}
                                                    >
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

                                    <div className="flex gap-2 items-end">
                                        {/* Hidden file input */}
                                        <input
                                            ref={fileInputRef}
                                            type="file"
                                            accept={ACCEPT_TYPES}
                                            className="hidden"
                                            onChange={handleFileSelect}
                                        />
                                        {/* Paperclip attach button */}
                                        <button
                                            onClick={() =>
                                                fileInputRef.current?.click()
                                            }
                                            title="Attach image or file"
                                            className="h-10 w-10 rounded-xl bg-[#e6f3d8] hover:bg-[#cee6b2] flex items-center justify-center text-[#427425] transition-colors flex-shrink-0"
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
                                            className="flex-1 resize-none px-3 py-2 text-sm rounded-xl focus:outline-none focus:ring-2 focus:ring-[#589b31] focus:border-transparent"
                                            style={{
                                                backgroundColor: "#f5f7f2",
                                                border: "1px solid #e8ebe3",
                                                color: "#1c2917",
                                            }}
                                        />
                                        <button
                                            onClick={sendReply}
                                            disabled={
                                                !replyText.trim() || sending
                                            }
                                            className="h-10 w-10 rounded-xl disabled:opacity-50 flex items-center justify-center text-white transition-colors"
                                            style={{ backgroundColor: "#589b31" }}
                                            onMouseEnter={(e) => { if (!(!replyText.trim() || sending)) (e.currentTarget as HTMLElement).style.backgroundColor = "#427425"; }}
                                            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "#589b31"; }}
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

                                    {/* Media attachment preview panel */}
                                    {mediaFile && (
                                        <div className="mt-2 p-2.5 rounded-xl flex items-start gap-2" style={{ backgroundColor: "#f5f7f2", border: "1px solid #e8ebe3" }}>
                                            {mediaPreviewUrl ? (
                                                <img
                                                    src={mediaPreviewUrl}
                                                    alt="preview"
                                                    className="w-14 h-14 rounded-lg object-cover border border-[#edf0ea] flex-shrink-0"
                                                />
                                            ) : (
                                                <div className="w-14 h-14 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: "#e8ebe3" }}>
                                                    <svg
                                                        className="w-6 h-6"
                                                        style={{ color: "#8a9e80" }}
                                                        fill="none"
                                                        stroke="currentColor"
                                                        viewBox="0 0 24 24"
                                                    >
                                                        <path
                                                            strokeLinecap="round"
                                                            strokeLinejoin="round"
                                                            strokeWidth={1.5}
                                                            d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"
                                                        />
                                                    </svg>
                                                </div>
                                            )}
                                            <div className="flex-1 min-w-0 space-y-1.5">
                                                <p className="text-xs font-medium text-[#1c2917] truncate">
                                                    {mediaFile.name}
                                                </p>
                                                <input
                                                    value={mediaCaption}
                                                    onChange={(e) =>
                                                        setMediaCaption(
                                                            e.target.value,
                                                        )
                                                    }
                                                    placeholder="Add a caption (optional)…"
                                                    className="w-full px-2 py-1 text-xs rounded-lg focus:outline-none focus:ring-1 focus:ring-[#589b31]"
                                                    style={{
                                                        backgroundColor: "#ffffff",
                                                        border: "1px solid #e8ebe3",
                                                        color: "#1c2917",
                                                    }}
                                                />
                                                <div className="flex gap-1.5">
                                                    <button
                                                        onClick={sendMedia}
                                                        disabled={
                                                            uploadingMedia
                                                        }
                                                        className="flex items-center gap-1 h-7 px-3 disabled:opacity-50 text-white text-xs font-medium rounded-lg transition-colors"
                                                        style={{ backgroundColor: "#589b31" }}
                                                    >
                                                        {uploadingMedia ? (
                                                            <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                                                        ) : (
                                                            <>
                                                                <svg
                                                                    className="w-3 h-3"
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
                                                                        d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
                                                                    />
                                                                </svg>
                                                                Send
                                                            </>
                                                        )}
                                                    </button>
                                                    <button
                                                        onClick={
                                                            clearMediaAttachment
                                                        }
                                                        className="h-7 px-3 text-xs rounded-lg transition-colors"
                                                        style={{ color: "#8a9e80", border: "1px solid #e8ebe3" }}
                                                    >
                                                        Cancel
                                                    </button>
                                                </div>
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
                const systemEvents = activeMessages.filter(
                    (m) => m.type === "system_event",
                );

                const dotColor: Record<string, string> = {
                    escalated:     "bg-amber-100 border-amber-300",
                    flag:          "bg-red-100 border-red-300",
                    intercept:     "bg-purple-100 border-purple-300",
                    release:       "bg-blue-100 border-blue-300",
                    transfer:      "bg-indigo-100 border-indigo-300",
                    approve_draft: "bg-green-100 border-green-300",
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
                            {systemEvents.length > 0 && (
                                <span className="w-4 h-4 rounded-full bg-amber-100 border border-amber-300 text-[8px] font-bold text-amber-700 flex items-center justify-center">
                                    {systemEvents.length}
                                </span>
                            )}
                        </button>
                    );
                }

                return (
                    <div
                        className="flex-shrink-0 flex flex-col overflow-hidden"
                        style={{ width: 196, backgroundColor: "#ffffff", borderLeft: "1px solid #edf0ea" }}
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

                        {systemEvents.length === 0 ? (
                            <div className="flex-1 flex items-center justify-center px-3">
                                <p className="text-[11px] text-stone-300 text-center leading-relaxed">
                                    No events yet
                                </p>
                            </div>
                        ) : (
                            <div className="flex-1 overflow-y-auto px-3 py-3 space-y-0">
                                {systemEvents.map((evt, i) => (
                                    <div key={evt.id} className="flex gap-2 pb-3 relative">
                                        {/* Connector line */}
                                        {i < systemEvents.length - 1 && (
                                            <div className="absolute left-[6px] top-4 bottom-0 w-px bg-stone-100" />
                                        )}
                                        {/* Dot */}
                                        <div
                                            className={`w-3.5 h-3.5 rounded-full border flex-shrink-0 mt-0.5 ${dotColor[evt.event_kind ?? ""] ?? "bg-stone-100 border-stone-300"}`}
                                        />
                                        <div className="min-w-0">
                                            <p className="text-[11px] font-medium text-[#1c2917] leading-snug">
                                                {evt.text}
                                            </p>
                                            {evt.agent_name && (
                                                <p className="text-[10px] text-[#b5c9a8] mt-0.5 truncate">
                                                    {evt.agent_name}
                                                </p>
                                            )}
                                            <p className="text-[10px] text-stone-400 mt-0.5">
                                                {timeAgo(evt.created_at)}
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
        </div>
    );
}