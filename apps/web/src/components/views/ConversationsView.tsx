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
import { useConversationEvents } from "@/lib/websocket";
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
    const [clearConfirm, setClearConfirm] = useState(false);
    const [clearing, setClearing] = useState(false);
    const [mobileCrmOpen, setMobileCrmOpen] = useState(false);
    // Tracks unread count at the moment a thread is opened — used to place the "N new" divider
    const [unreadSnapshot, setUnreadSnapshot] = useState<Record<string, number>>({});

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
                if (existing.some((x) => x.id === msg.id)) return m;
                return { ...m, [activeConvId]: [...existing, msg] };
            });
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
        new Set(
            conversations.flatMap((c) => (c as any).tags ?? [])
        )
    ).sort() as string[];

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
            className="flex flex-col h-full border-r border-[#e6f3d8] bg-white"
            style={{
                width: isMobile ? "100%" : 288,
                minWidth: isMobile ? "100%" : 288,
            }}
        >
            {/* Header */}
            <div className="px-4 pt-5 pb-3 border-b border-[#e6f3d8]">
                <div className="flex items-center justify-between mb-3">
                    <h1 className="text-base font-bold text-[#16270c]">
                        Inbox
                    </h1>
                    <div className="flex items-center gap-2">
                        {humanCount > 0 && (
                            <span className="text-xs bg-amber-100 text-amber-700 font-semibold px-2 py-0.5 rounded-full">
                                {humanCount} live
                            </span>
                        )}
                        <button
                            onClick={() => setShowFilters((f) => !f)}
                            className={`w-7 h-7 rounded-lg flex items-center justify-center transition-colors ${showFilters ? "bg-stone-800 text-white" : "bg-[#e6f3d8] text-[#699a32] hover:bg-[#cee6b2]"}`}
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

                {/* Search */}
                <div className="relative mb-2">
                    <svg
                        className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#b5da8b]"
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
                        placeholder="Search conversations…"
                        className="w-full h-8 pl-8 pr-3 text-xs bg-[#f3f9ec] border border-[#cee6b2] rounded-lg text-[#16270c] placeholder-stone-300 focus:outline-none focus:ring-1 focus:ring-[#589b31]"
                        style={{ fontSize: 14 }}
                    />
                </div>

                {/* Channel tabs */}
                <div className="flex gap-1 overflow-x-auto scrollbar-none pb-1">
                    {CHANNEL_TABS.map((tab) => (
                        <button
                            key={tab.id}
                            onClick={() => setChannelTab(tab.id)}
                            className={`flex-shrink-0 h-6 px-2.5 rounded-md text-xs font-medium transition-colors relative ${channelTab === tab.id ? "bg-stone-800 text-white" : "text-[#699a32] hover:bg-[#e6f3d8]"}`}
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
                                    style={tagFilter === "all" ? { backgroundColor: "#589b31" } : undefined}
                                >
                                    All tags
                                </button>
                                {allTags.map((tag) => (
                                    <button
                                        key={tag}
                                        onClick={() => setTagFilter(tag === tagFilter ? "all" : tag)}
                                        className={`h-6 px-2.5 rounded-md text-xs font-medium transition-colors ${tagFilter === tag ? "text-white" : "bg-[#e6f3d8] text-[#699a32]"}`}
                                        style={tagFilter === tag ? { backgroundColor: "#589b31" } : undefined}
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
            <div className={`flex-1 overflow-y-auto scrollbar-none divide-y divide-[#f0f9ec] ${isMobile ? "pb-16" : ""}`}>
                {filteredConvs.length === 0 && (
                    <div className="py-16 text-center">
                        <p className="text-sm text-[#9ccd65]">
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
                            className={`w-full text-left px-4 py-3 transition-colors border-l-2 ${
                                isActive
                                    ? "bg-[#f3f9ec] border-l-[#589b31]"
                                    : hasUnread
                                      ? "bg-[#f8fcf3] border-l-[#427425] hover:bg-[#f3f9ec]"
                                      : "border-l-transparent hover:bg-[#f3f9ec]"
                            }`}
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
                                        <span className={`text-sm truncate ${hasUnread ? "font-bold text-[#16270c]" : "font-semibold text-[#16270c]"}`}>
                                            {displayName(conv.name, conv.wa_id)}
                                        </span>
                                        <span className={`text-[10px] flex-shrink-0 ml-2 ${hasUnread ? "font-semibold text-[#427425]" : "text-[#9ccd65]"}`}>
                                            {conv.last_message_at
                                                ? timeAgo(conv.last_message_at)
                                                : ""}
                                        </span>
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <p className={`text-xs truncate flex-1 ${hasUnread ? "text-[#16270c] font-medium" : "text-[#699a32]"}`}>
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
                                                <span className="min-w-[20px] h-5 px-1.5 bg-[#427425] text-white text-[10px] font-bold rounded-full flex items-center justify-center">
                                                    {conv.unread > 99 ? "99+" : conv.unread}
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
            <div className="flex flex-col flex-1 overflow-hidden bg-white relative">
                {!activeConv ? (
                    <div className="flex-1 flex items-center justify-center text-[#9ccd65]">
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
                                className="absolute top-3 right-3 z-20 w-8 h-8 rounded-full bg-white border border-[#cee6b2] shadow-sm flex items-center justify-center text-[#427425] hover:bg-[#f3f9ec] transition-colors"
                            >
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                                </svg>
                            </button>
                        )}
                        {/* Thread header */}
                        <div className="px-4 py-3 border-b border-[#e6f3d8] bg-white flex items-center gap-2 flex-wrap">
                            {isMobile && (
                                <button
                                    onClick={() => setMobilePanel("list")}
                                    className="text-[#699a32] hover:text-[#16270c] mr-1 flex-shrink-0"
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
                                <div className="text-sm font-semibold text-[#16270c] truncate">
                                    {displayName(
                                        activeConv.name,
                                        activeConv.wa_id,
                                    )}
                                </div>
                                <div className="text-xs text-[#9ccd65] font-mono truncate">
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
                                        <span className="text-xs text-[#9ccd65] hidden lg:block">
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

                        {/* Media escalation notice */}
                        {activeConv.intercept_mode === "human" &&
                            activeMessages.some(
                                (m) =>
                                    (m as any).media_type &&
                                    (m as any).media_type !== "note" &&
                                    m.direction === "inbound",
                            ) && (
                                <div className="mx-4 mt-2 px-3 py-2 rounded-xl bg-amber-50 border border-amber-200 flex items-center gap-2">
                                    <span className="text-amber-500 text-sm flex-shrink-0">
                                        📎
                                    </span>
                                    <p className="text-xs font-medium text-amber-700">
                                        Customer sent media — conversation was
                                        auto-escalated for your review.
                                    </p>
                                </div>
                            )}

                        {/* Messages */}
                        <div
                            className="flex-1 overflow-y-auto px-5 py-4 space-y-3"
                            style={{ backgroundColor: "#f8fbf4" }}
                        >
                            {threadLoading && (
                                <div className="flex justify-center py-8">
                                    <div className="w-5 h-5 border-2 border-[#427425] border-t-transparent rounded-full animate-spin" />
                                </div>
                            )}
                            {!threadLoading && activeMessages.length === 0 && (
                                <div className="text-center py-12 text-[#9ccd65]">
                                    <p className="text-sm">No messages yet</p>
                                </div>
                            )}
                            {(() => {
                                // How many messages were unread when this thread was opened
                                const snap = unreadSnapshot[activeConvId] ?? 0;
                                // The divider sits before the first unread message
                                const dividerIdx = snap > 0 ? Math.max(0, activeMessages.length - snap) : -1;
                                return activeMessages.map((msg, idx) => {
                                const isInbound = msg.direction === "inbound";
                                const isNote = msg.isNote;
                                const showDivider = idx === dividerIdx && snap > 0;

                                if (isNote) {
                                    return (
                                        <React.Fragment key={msg.id ?? `msg-${idx}`}>
                                            {showDivider && (
                                                <div className="flex items-center gap-2 my-1">
                                                    <div className="flex-1 h-px bg-[#427425]/30" />
                                                    <span className="text-[10px] font-semibold text-[#427425] bg-[#e6f3d8] px-2 py-0.5 rounded-full whitespace-nowrap">
                                                        {snap} new {snap === 1 ? "message" : "messages"}
                                                    </span>
                                                    <div className="flex-1 h-px bg-[#427425]/30" />
                                                </div>
                                            )}
                                            <div
                                                className="flex justify-center"
                                            >
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
                                    <React.Fragment key={msg.id ?? `msg-${idx}`}>
                                        {showDivider && (
                                            <div className="flex items-center gap-2 my-1">
                                                <div className="flex-1 h-px bg-[#427425]/30" />
                                                <span className="text-[10px] font-semibold text-[#427425] bg-[#e6f3d8] px-2 py-0.5 rounded-full whitespace-nowrap">
                                                    {snap} new {snap === 1 ? "message" : "messages"}
                                                </span>
                                                <div className="flex-1 h-px bg-[#427425]/30" />
                                            </div>
                                        )}
                                        <div
                                        className={`flex ${isInbound ? "justify-start" : "justify-end"}`}
                                    >
                                        <div
                                            className={`rounded-2xl text-xs ${
                                                (msg as any).media_type &&
                                                (msg as any).media_type !==
                                                    "note" &&
                                                (msg as any).media_url &&
                                                (msg as any).media_type
                                                    .startsWith
                                                    ? "p-1.5 max-w-[65%]"
                                                    : "px-4 py-2.5 max-w-[75%]"
                                            } ${
                                                isInbound
                                                    ? "bg-white border border-[#cee6b2] text-[#16270c] rounded-tl-sm"
                                                    : msg.sender === "ai"
                                                      ? "bg-blue-600 text-white rounded-tr-sm"
                                                      : "bg-[#427425] text-white rounded-tr-sm"
                                            }`}
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
                                                    mt.startsWith?.("image/")
                                                ) {
                                                    return (
                                                        <div className="space-y-1">
                                                            <a
                                                                href={mu}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                            >
                                                                <img
                                                                    src={mu}
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
                                                    mt.startsWith?.("video/")
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
                                                    mt.startsWith?.("audio/")
                                                ) {
                                                    return (
                                                        <audio
                                                            src={mu}
                                                            controls
                                                            className="w-full"
                                                        />
                                                    );
                                                }
                                                const fileName =
                                                    msg.text ||
                                                    mu.split("/").pop() ||
                                                    "file";
                                                return (
                                                    <a
                                                        href={mu}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className={`flex items-center gap-2 px-3 py-2 rounded-xl border transition-opacity hover:opacity-80 ${
                                                            isInbound
                                                                ? "bg-[#f3f9ec] border-[#cee6b2] text-[#16270c]"
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
                                                                strokeWidth={2}
                                                                d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                                                            />
                                                        </svg>
                                                    </a>
                                                );
                                            })()}
                                            <div
                                                className={`text-[10px] mt-1 ${isInbound ? "text-[#9ccd65]" : "opacity-60"}`}
                                            >
                                                {msg.created_at
                                                    ? timeAgo(msg.created_at)
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
                                <div className="border-t border-[#e6f3d8] px-4 py-3 bg-white">
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
                                            className="flex-1 resize-none px-3 py-2 text-sm bg-[#f3f9ec] border border-[#cee6b2] rounded-xl text-[#16270c] placeholder-stone-300 focus:outline-none focus:ring-2 focus:ring-[#589b31] focus:border-transparent"
                                        />
                                        <button
                                            onClick={sendReply}
                                            disabled={
                                                !replyText.trim() || sending
                                            }
                                            className="h-10 w-10 rounded-xl bg-[#427425] hover:bg-[#589b31] disabled:opacity-50 flex items-center justify-center text-white transition-colors"
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
                                        <div className="mt-2 p-2.5 rounded-xl bg-[#f3f9ec] border border-[#cee6b2] flex items-start gap-2">
                                            {mediaPreviewUrl ? (
                                                <img
                                                    src={mediaPreviewUrl}
                                                    alt="preview"
                                                    className="w-14 h-14 rounded-lg object-cover border border-[#cee6b2] flex-shrink-0"
                                                />
                                            ) : (
                                                <div className="w-14 h-14 rounded-lg bg-[#e6f3d8] flex items-center justify-center flex-shrink-0">
                                                    <svg
                                                        className="w-6 h-6 text-[#699a32]"
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
                                                <p className="text-xs font-medium text-[#16270c] truncate">
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
                                                    className="w-full px-2 py-1 text-xs bg-white border border-[#cee6b2] rounded-lg text-[#16270c] placeholder-stone-300 focus:outline-none focus:ring-1 focus:ring-[#589b31]"
                                                />
                                                <div className="flex gap-1.5">
                                                    <button
                                                        onClick={sendMedia}
                                                        disabled={
                                                            uploadingMedia
                                                        }
                                                        className="flex items-center gap-1 h-7 px-3 bg-[#427425] hover:bg-[#589b31] disabled:opacity-50 text-white text-xs font-medium rounded-lg transition-colors"
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
                                                        className="h-7 px-3 text-xs text-[#699a32] hover:text-[#16270c] rounded-lg border border-[#cee6b2] transition-colors"
                                                    >
                                                        Cancel
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}

                        {/* Lock banner — shown to regular agents when another agent owns the conv.
                            Admin/superuser never see this banner. */}
                        {activeConv.intercept_mode === "human" &&
                        activeConv.assigned_agent_id &&
                        activeConv.assigned_agent_id !== currentAgentId &&
                        !isAdminOrSuper ? (
                            <div className="border-t border-[#e6f3d8] px-4 py-4 bg-[#f3f9ec] flex items-center justify-center gap-2">
                                <span className="text-base">🔒</span>
                                <p className="text-xs text-[#699a32]">
                                    Handled by{" "}
                                    <strong className="text-[#427425]">
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
                        className="flex-shrink-0 w-8 border-l border-[#e6f3d8] bg-white flex flex-col items-center justify-center gap-1 hover:bg-[#f3f9ec] transition-colors"
                    >
                        <svg
                            className="w-4 h-4 text-[#9ccd65]"
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
                            className="text-[9px] text-[#9ccd65] font-semibold uppercase tracking-widest"
                            style={{
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
            <p className="text-sm text-[#699a32] mb-3">
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
                            className="w-full flex items-center gap-3 p-3 rounded-xl hover:bg-[#f3f9ec] border border-[#e6f3d8] transition-colors"
                        >
                            <Avatar name={a.name} size={32} />
                            <div className="text-left">
                                <div className="text-sm font-semibold text-[#16270c]">
                                    {a.name}
                                </div>
                                <div className="text-xs text-[#9ccd65]">
                                    {a.active_convs} active conversations
                                </div>
                            </div>
                        </button>
                    ))}
                {agents.filter((a) => a.is_available).length === 0 && (
                    <p className="text-sm text-[#9ccd65] text-center py-4">
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
                <div className="flex flex-col flex-1 overflow-hidden" style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
                    {mobilePanel === "list" ? ConvList : (
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
                            <div className="flex items-center justify-between px-4 pt-4 pb-3 border-b border-[#e6f3d8] flex-shrink-0">
                                <h2 className="text-sm font-bold text-[#16270c]">Customer Profile</h2>
                                <button
                                    onClick={() => setMobileCrmOpen(false)}
                                    className="w-7 h-7 rounded-full bg-[#f3f9ec] flex items-center justify-center text-[#699a32] hover:bg-[#e6f3d8]"
                                >
                                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
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
                                                    ? { ...c, name: newName, contact_name: newName }
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