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
import { timeAgo } from "@/lib/utils";
import { CHANNEL_CONFIG, ALL_CHANNELS } from "@/lib/channels";
import { conversationsApi } from "@/lib/api";
import type {
    Conversation,
    Message,
    MessagesMap,
    Agent,
    Channel,
    SharedViewProps,
} from "@/types";

type MobilePanel = "list" | "thread";

interface ConversationsViewProps extends SharedViewProps {
    conversations: Conversation[];
    setConversations: React.Dispatch<React.SetStateAction<Conversation[]>>;
    messages: MessagesMap;
    setMessages: React.Dispatch<React.SetStateAction<MessagesMap>>;
    agents: Agent[];
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
    onToast,
    isMobile,
    refetchConversations,
}: ConversationsViewProps): React.ReactElement {
    const [activeConvId, setActiveConvId] = useState<string>("");
    const [mobilePanel, setMobilePanel] = useState<MobilePanel>("list");
    const [channelTab, setChannelTab] = useState<"all" | Channel>("all");
    const [statusFilter, setStatusFilter] = useState<"all" | "open" | "closed">(
        "all",
    );
    const [interceptFilter, setInterceptFilter] = useState<
        "all" | "human" | "ai" | "paused"
    >("all");
    const [searchQ, setSearchQ] = useState<string>("");
    const [replyText, setReplyText] = useState<string>("");
    const [draftVisible, setDraftVisible] = useState<boolean>(true);
    const [transferModal, setTransferModal] = useState<boolean>(false);
    const [noteModal, setNoteModal] = useState<boolean>(false);
    const [noteText, setNoteText] = useState<string>("");
    const [showFilters, setShowFilters] = useState<boolean>(false);
    const [threadLoading, setThreadLoading] = useState(false);
    const [sending, setSending] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    // Set first conversation as active when data loads
    useEffect(() => {
        if (conversations.length > 0 && !activeConvId) {
            setActiveConvId(conversations[0].id);
        }
    }, [conversations, activeConvId]);

    const activeConv = conversations.find((c) => c.id === activeConvId);
    const activeMessages: Message[] = messages[activeConvId] ?? [];

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [activeConvId, messages]);

    // Load messages when switching conversations
    const loadMessages = useCallback(
        async (convId: string) => {
            if (messages[convId]) return; // already loaded
            setThreadLoading(true);
            try {
                const msgs = await conversationsApi.messages(convId);
                setMessages((m) => ({ ...m, [convId]: msgs }));
            } catch {
                onToast("Failed to load messages", "error");
            } finally {
                setThreadLoading(false);
            }
        },
        [messages, setMessages, onToast],
    );

    const handleSelectConv = (id: string) => {
        setActiveConvId(id);
        loadMessages(id);
        if (isMobile) setMobilePanel("thread");
    };

    // ── Actions ───────────────────────────────────────────────────────────────

    const intercept = async (convId: string) => {
        try {
            await conversationsApi.intercept(convId);
            refetchConversations?.();
            onToast("Conversation intercepted — you now control replies");
        } catch {
            onToast("Failed to intercept", "error");
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
        try {
            const msg = await conversationsApi.sendReply(
                activeConvId,
                replyText,
            );
            setMessages((m) => ({
                ...m,
                [activeConvId]: [...(m[activeConvId] ?? []), msg],
            }));
            setReplyText("");
            refetchConversations?.();
            onToast("Message sent");
        } catch {
            onToast("Failed to send message", "error");
        } finally {
            setSending(false);
        }
    };

    const approveDraft = async () => {
        if (!activeConvId) return;
        try {
            await conversationsApi.approveDraft(activeConvId);
            setDraftVisible(false);
            refetchConversations?.();
            onToast("AI draft approved & sent");
        } catch {
            onToast("Failed to approve draft", "error");
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

    // ── Filters ───────────────────────────────────────────────────────────────

    const channelCounts = CHANNEL_TABS.reduce<Record<string, number>>(
        (acc, tab) => {
            acc[tab.id] =
                tab.id === "all"
                    ? conversations
                          .filter((c) => (c as any).unread > 0)
                          .reduce((s, c) => s + ((c as any).unread ?? 0), 0)
                    : conversations
                          .filter(
                              (c) =>
                                  c.channel === tab.id && (c as any).unread > 0,
                          )
                          .reduce((s, c) => s + ((c as any).unread ?? 0), 0);
            return acc;
        },
        {},
    );

    const filteredConvs = conversations.filter((c) => {
        if (channelTab !== "all" && c.channel !== channelTab) return false;
        if (statusFilter !== "all" && c.status !== statusFilter) return false;
        if (interceptFilter !== "all" && c.intercept_mode !== interceptFilter)
            return false;
        if (
            searchQ &&
            !(c as any).name?.toLowerCase().includes(searchQ.toLowerCase()) &&
            !c.last_message?.toLowerCase().includes(searchQ.toLowerCase())
        )
            return false;
        return true;
    });

    const humanCount = conversations.filter(
        (c) => c.intercept_mode === "human",
    ).length;

    // ── Render ────────────────────────────────────────────────────────────────

    const ConvList = (
        <div
            className="flex flex-col h-full border-r border-stone-100 bg-white"
            style={{
                width: isMobile ? "100%" : 320,
                minWidth: isMobile ? "100%" : 280,
            }}
        >
            {/* Header */}
            <div className="px-4 pt-5 pb-3 border-b border-stone-100">
                <div className="flex items-center justify-between mb-3">
                    <h1 className="text-base font-bold text-stone-800">
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
                            className={`w-7 h-7 rounded-lg flex items-center justify-center transition-colors ${showFilters ? "bg-stone-800 text-white" : "bg-stone-100 text-stone-500 hover:bg-stone-200"}`}
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
                        className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-stone-300"
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
                        className="w-full h-8 pl-8 pr-3 text-xs bg-stone-50 border border-stone-200 rounded-lg text-stone-800 placeholder-stone-300 focus:outline-none focus:ring-1 focus:ring-green-600"
                        style={{ fontSize: 14 }}
                    />
                </div>

                {/* Channel tabs */}
                <div className="flex gap-1 overflow-x-auto scrollbar-none pb-1">
                    {CHANNEL_TABS.map((tab) => (
                        <button
                            key={tab.id}
                            onClick={() => setChannelTab(tab.id)}
                            className={`flex-shrink-0 h-6 px-2.5 rounded-md text-xs font-medium transition-colors relative ${channelTab === tab.id ? "bg-stone-800 text-white" : "text-stone-500 hover:bg-stone-100"}`}
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
                        {(["all", "open", "closed"] as const).map((s) => (
                            <button
                                key={s}
                                onClick={() => setStatusFilter(s)}
                                className={`h-6 px-2.5 rounded-md text-xs font-medium capitalize transition-colors ${statusFilter === s ? "bg-green-700 text-white" : "bg-stone-100 text-stone-500"}`}
                            >
                                {s}
                            </button>
                        ))}
                        <div className="w-full" />
                        {(["all", "ai", "human", "paused"] as const).map(
                            (m) => (
                                <button
                                    key={m}
                                    onClick={() => setInterceptFilter(m)}
                                    className={`h-6 px-2.5 rounded-md text-xs font-medium capitalize transition-colors ${interceptFilter === m ? "bg-green-700 text-white" : "bg-stone-100 text-stone-500"}`}
                                >
                                    {m}
                                </button>
                            ),
                        )}
                    </div>
                )}
            </div>

            {/* Conversation list */}
            <div className="flex-1 overflow-y-auto scrollbar-none divide-y divide-stone-50">
                {filteredConvs.length === 0 && (
                    <div className="py-16 text-center">
                        <p className="text-sm text-stone-400">
                            No conversations found
                        </p>
                    </div>
                )}
                {filteredConvs.map((conv) => {
                    const isActive = conv.id === activeConvId;
                    const cfg = conv.channel
                        ? CHANNEL_CONFIG[conv.channel as Channel]
                        : null;
                    return (
                        <button
                            key={conv.id}
                            onClick={() => handleSelectConv(conv.id)}
                            className={`w-full text-left px-4 py-3 transition-colors hover:bg-stone-50 ${isActive ? "bg-stone-50 border-l-2 border-l-green-700" : ""}`}
                        >
                            <div className="flex items-start gap-3">
                                <div className="relative flex-shrink-0">
                                    <Avatar
                                        name={(conv as any).name ?? conv.wa_id}
                                        size={38}
                                    />
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
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center justify-between mb-0.5">
                                        <span className="text-sm font-semibold text-stone-800 truncate">
                                            {(conv as any).name ?? conv.wa_id}
                                        </span>
                                        <span className="text-[10px] text-stone-400 flex-shrink-0 ml-2">
                                            {conv.last_message_at
                                                ? timeAgo(conv.last_message_at)
                                                : ""}
                                        </span>
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <p className="text-xs text-stone-500 truncate flex-1">
                                            {conv.last_message ??
                                                "No messages yet"}
                                        </p>
                                        <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                                            {conv.intercept_mode !== "ai" && (
                                                <InterceptBadge
                                                    mode={conv.intercept_mode}
                                                />
                                            )}
                                            {(conv as any).unread > 0 && (
                                                <span className="w-4 h-4 bg-green-700 text-white text-[9px] font-bold rounded-full flex items-center justify-center">
                                                    {(conv as any).unread}
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
        <div className="flex flex-col flex-1 overflow-hidden bg-white">
            {!activeConv ? (
                <div className="flex-1 flex items-center justify-center text-stone-400">
                    <div className="text-center">
                        <div className="text-4xl mb-2">💬</div>
                        <p className="text-sm">Select a conversation</p>
                    </div>
                </div>
            ) : (
                <>
                    {/* Thread header */}
                    <div className="px-5 py-3 border-b border-stone-100 bg-white flex items-center gap-3">
                        {isMobile && (
                            <button
                                onClick={() => setMobilePanel("list")}
                                className="text-stone-500 hover:text-stone-800 mr-1"
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
                            name={(activeConv as any).name ?? activeConv.wa_id}
                            size={36}
                        />
                        <div className="flex-1 min-w-0">
                            <div className="text-sm font-semibold text-stone-800">
                                {(activeConv as any).name ?? activeConv.wa_id}
                            </div>
                            <div className="text-xs text-stone-400 font-mono">
                                +{activeConv.wa_id}
                            </div>
                        </div>
                        <InterceptBadge mode={activeConv.intercept_mode} />
                        {activeConv.assigned_agent_id && (
                            <span className="text-xs text-stone-400 hidden sm:block">
                                →{" "}
                                {
                                    agents.find(
                                        (a) =>
                                            a.id ===
                                            activeConv.assigned_agent_id,
                                    )?.name
                                }
                            </span>
                        )}
                        {/* Action buttons */}
                        <div className="flex items-center gap-1.5">
                            {activeConv.intercept_mode === "ai" && (
                                <Btn
                                    key="intercept"
                                    small
                                    onClick={() => intercept(activeConv.id)}
                                    variant="primary"
                                >
                                    ⚡ Intercept
                                </Btn>
                            )}
                            {activeConv.intercept_mode === "human" && (
                                <Btn
                                    key="release"
                                    small
                                    onClick={() => release(activeConv.id)}
                                    variant="secondary"
                                >
                                    ↩ Release
                                </Btn>
                            )}
                            {activeConv.intercept_mode !== "paused" && (
                                <Btn
                                    key="pause"
                                    small
                                    onClick={() => release(activeConv.id)}
                                    variant="secondary"
                                >
                                    ⏸ Pause
                                </Btn>
                            )}
                            {activeConv.intercept_mode === "paused" && (
                                <Btn
                                    key="resume"
                                    small
                                    onClick={() => release(activeConv.id)}
                                    variant="primary"
                                >
                                    ▶ Resume
                                </Btn>
                            )}
                            <Btn
                                key="transfer"
                                small
                                onClick={() => setTransferModal(true)}
                                variant="secondary"
                            >
                                ⇄
                            </Btn>
                            <Btn
                                key="note"
                                small
                                onClick={() => setNoteModal(true)}
                                variant="secondary"
                            >
                                📝
                            </Btn>
                            {activeConv.status === "open" && (
                                <Btn
                                    key="close"
                                    small
                                    onClick={() => closeConv(activeConv.id)}
                                    variant="danger"
                                >
                                    ✓
                                </Btn>
                            )}
                        </div>
                    </div>

                    {/* Messages */}
                    <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3 bg-stone-50">
                        {threadLoading && (
                            <div className="flex justify-center py-8">
                                <div className="w-5 h-5 border-2 border-green-700 border-t-transparent rounded-full animate-spin" />
                            </div>
                        )}
                        {!threadLoading && activeMessages.length === 0 && (
                            <div className="text-center py-12 text-stone-400">
                                <p className="text-sm">No messages yet</p>
                            </div>
                        )}
                        {activeMessages.map((msg, idx) => {
                            const isInbound = msg.direction === "inbound";
                            return (
                                <div
                                    key={msg.id ?? `msg-${idx}`}
                                    className={`flex ${isInbound ? "justify-start" : "justify-end"}`}
                                >
                                    <div
                                        className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-sm ${
                                            isInbound
                                                ? "bg-white border border-stone-200 text-stone-800 rounded-tl-sm"
                                                : msg.sender === "ai"
                                                  ? "bg-blue-600 text-white rounded-tr-sm"
                                                  : "bg-green-700 text-white rounded-tr-sm"
                                        }`}
                                    >
                                        {!isInbound && (
                                            <div className="text-[10px] opacity-70 mb-1 font-medium uppercase tracking-wide">
                                                {msg.sender === "ai"
                                                    ? "AI"
                                                    : "Agent"}
                                            </div>
                                        )}
                                        <p className="leading-relaxed whitespace-pre-wrap">
                                            {msg.text}
                                        </p>
                                        <div
                                            className={`text-[10px] mt-1 ${isInbound ? "text-stone-400" : "opacity-60"}`}
                                        >
                                            {msg.created_at
                                                ? timeAgo(msg.created_at)
                                                : ""}
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                        <div ref={messagesEndRef} />
                    </div>

                    {/* Reply box — only shown when agent is in control */}
                    {activeConv.intercept_mode === "human" && (
                        <div className="border-t border-stone-100 px-4 py-3 bg-white">
                            {draftVisible &&
                                activeConv.intercept_mode === "human" && (
                                    <div className="mb-2 p-3 rounded-xl bg-blue-50 border border-blue-200 flex items-start gap-2">
                                        <span className="text-blue-500 text-sm mt-0.5">
                                            🤖
                                        </span>
                                        <div className="flex-1 min-w-0">
                                            <p className="text-xs font-semibold text-blue-700 mb-1">
                                                AI Draft
                                            </p>
                                            <p className="text-xs text-blue-700">
                                                AI has a reply ready — approve
                                                or write your own.
                                            </p>
                                        </div>
                                        <Btn
                                            small
                                            onClick={approveDraft}
                                            variant="primary"
                                        >
                                            Approve
                                        </Btn>
                                        <Btn
                                            small
                                            onClick={() =>
                                                setDraftVisible(false)
                                            }
                                            variant="secondary"
                                        >
                                            Dismiss
                                        </Btn>
                                    </div>
                                )}
                            <div className="flex gap-2 items-end">
                                <textarea
                                    value={replyText}
                                    onChange={(e) =>
                                        setReplyText(e.target.value)
                                    }
                                    onKeyDown={(e) => {
                                        if (e.key === "Enter" && !e.shiftKey) {
                                            e.preventDefault();
                                            sendReply();
                                        }
                                    }}
                                    placeholder="Type a reply… (Enter to send)"
                                    rows={2}
                                    className="flex-1 resize-none px-3 py-2 text-sm bg-stone-50 border border-stone-200 rounded-xl text-stone-800 placeholder-stone-300 focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent"
                                />
                                <button
                                    onClick={sendReply}
                                    disabled={!replyText.trim() || sending}
                                    className="h-10 w-10 rounded-xl bg-green-700 hover:bg-green-600 disabled:opacity-50 flex items-center justify-center text-white transition-colors"
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
                        </div>
                    )}
                </>
            )}
        </div>
    );

    // Transfer modal
    const TransferModalEl = (
        <Modal
            show={transferModal}
            onClose={() => setTransferModal(false)}
            title="Transfer Conversation"
        >
            <p className="text-sm text-stone-500 mb-3">
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
                            className="w-full flex items-center gap-3 p-3 rounded-xl hover:bg-stone-50 border border-stone-100 transition-colors"
                        >
                            <Avatar name={a.name} size={32} />
                            <div className="text-left">
                                <div className="text-sm font-semibold text-stone-800">
                                    {a.name}
                                </div>
                                <div className="text-xs text-stone-400">
                                    {a.active_convs} active conversations
                                </div>
                            </div>
                        </button>
                    ))}
                {agents.filter((a) => a.is_available).length === 0 && (
                    <p className="text-sm text-stone-400 text-center py-4">
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
                    onClick={() => {
                        onToast("Note saved");
                        setNoteModal(false);
                        setNoteText("");
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

    if (isMobile) {
        return (
            <div className="flex-1 overflow-hidden flex flex-col">
                {mobilePanel === "list" ? ConvList : ThreadPanel}
                {TransferModalEl}
                {NoteModalEl}
            </div>
        );
    }

    return (
        <div className="flex flex-1 overflow-hidden">
            {ConvList}
            {ThreadPanel}
            {TransferModalEl}
            {NoteModalEl}
        </div>
    );
}