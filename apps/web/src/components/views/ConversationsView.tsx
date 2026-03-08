import React, { useState, useRef, useEffect } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { InterceptBadge, ChannelBadge, RoleBadge } from "@/components/ui/Badges";
import { Btn } from "@/components/ui/Btn";
import { Modal } from "@/components/ui/Modal";
import { TextareaField, InputField } from "@/components/ui/FormFields";
import { Toggle } from "@/components/ui/Layout";
import { timeAgo } from "@/lib/utils";
import { AI_DRAFT } from "@/lib/mockData";
import { CHANNEL_CONFIG, ALL_CHANNELS } from "@/lib/channels";
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
}: ConversationsViewProps): React.ReactElement {
    const [activeConvId, setActiveConvId] = useState<string>("c1");
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
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const activeConv = conversations.find((c) => c.id === activeConvId);
    const activeMessages: Message[] = messages[activeConvId] ?? [];

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [activeConvId, messages]);

    // Channel counts for tab badges
    const channelCounts = CHANNEL_TABS.reduce<Record<string, number>>(
        (acc, tab) => {
            acc[tab.id] =
                tab.id === "all"
                    ? conversations
                          .filter((c) => c.unread > 0)
                          .reduce((s, c) => s + c.unread, 0)
                    : conversations
                          .filter((c) => c.channel === tab.id && c.unread > 0)
                          .reduce((s, c) => s + c.unread, 0);
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
            !c.name.toLowerCase().includes(searchQ.toLowerCase()) &&
            !c.last_message_preview
                .toLowerCase()
                .includes(searchQ.toLowerCase())
        )
            return false;
        return true;
    });

    // Actions
    const selectConv = (id: string) => {
        setActiveConvId(id);
        if (isMobile) setMobilePanel("thread");
    };
    const intercept = (id: string) => {
        setConversations((cs) =>
            cs.map((c) =>
                c.id === id
                    ? { ...c, intercept_mode: "human", assigned_agent_id: "a1" }
                    : c,
            ),
        );
        onToast("Conversation intercepted");
    };
    const release = (id: string) => {
        setConversations((cs) =>
            cs.map((c) =>
                c.id === id
                    ? { ...c, intercept_mode: "ai", assigned_agent_id: null }
                    : c,
            ),
        );
        onToast("Released to AI");
    };
    const pause = (id: string) => {
        setConversations((cs) =>
            cs.map((c) =>
                c.id === id ? { ...c, intercept_mode: "paused" } : c,
            ),
        );
        onToast("AI paused");
    };
    const closeConv = (id: string) => {
        setConversations((cs) =>
            cs.map((c) => (c.id === id ? { ...c, status: "closed" } : c)),
        );
        onToast("Conversation closed");
    };

    const transferConv = (agentId: string) => {
        const agent = agents.find((a) => a.id === agentId);
        setConversations((cs) =>
            cs.map((c) =>
                c.id === activeConvId
                    ? {
                          ...c,
                          assigned_agent_id: agentId,
                          intercept_mode: "human",
                      }
                    : c,
            ),
        );
        setTransferModal(false);
        onToast(`Transferred to ${agent?.name ?? agentId}`);
    };

    const sendReply = () => {
        if (!replyText.trim()) return;
        const msg: Message = {
            id: `m${Date.now()}`,
            direction: "outbound",
            sender: "human_agent",
            text: replyText,
            created_at: new Date().toISOString(),
        };
        setMessages((m) => ({
            ...m,
            [activeConvId]: [...(m[activeConvId] ?? []), msg],
        }));
        setConversations((cs) =>
            cs.map((c) =>
                c.id === activeConvId
                    ? {
                          ...c,
                          last_message_preview: replyText,
                          last_message_at: new Date().toISOString(),
                      }
                    : c,
            ),
        );
        setReplyText("");
        onToast("Message sent");
    };

    const approveDraft = () => {
        const msg: Message = {
            id: `m${Date.now()}`,
            direction: "outbound",
            sender: "ai",
            text: AI_DRAFT,
            created_at: new Date().toISOString(),
        };
        setMessages((m) => ({
            ...m,
            [activeConvId]: [...(m[activeConvId] ?? []), msg],
        }));
        setDraftVisible(false);
        onToast("AI draft approved & sent");
    };

    const addNote = () => {
        const msg: Message = {
            id: `m${Date.now()}`,
            direction: "outbound",
            sender: "human_agent",
            text: noteText,
            created_at: new Date().toISOString(),
            isNote: true,
        };
        setMessages((m) => ({
            ...m,
            [activeConvId]: [...(m[activeConvId] ?? []), msg],
        }));
        setNoteModal(false);
        setNoteText("");
        onToast("Internal note saved");
    };

    // ─── List panel ───────────────────────────────────────────────────────────────
    const listPanel = (
        <div
            className="flex flex-col bg-white dark:bg-gray-900 border-r border-gray-100 dark:border-gray-800 flex-shrink-0 overflow-hidden"
            style={{ width: isMobile ? "100%" : 300 }}
        >
            {/* Search + filter row */}
            <div className="px-3 pt-3 pb-2 border-b border-gray-100 dark:border-gray-800 space-y-2">
                <div className="relative">
                    <svg
                        className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
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
                        className="w-full h-9 pl-9 pr-3 text-sm bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                        style={{ fontSize: 16 }}
                    />
                </div>
                {/* Filter pills */}
                <div className="flex items-center gap-1.5">
                    <button
                        onClick={() => setShowFilters((f) => !f)}
                        className={`flex items-center gap-1 px-2.5 h-7 rounded-lg text-xs font-medium transition-colors ${showFilters ? "bg-amber-50 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-800" : "bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 border border-transparent"}`}
                    >
                        <svg
                            className="w-3 h-3"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                        >
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"
                            />
                        </svg>
                        Filter
                    </button>
                    {(["all", "open", "closed"] as const).map((s) => (
                        <button
                            key={s}
                            onClick={() => setStatusFilter(s)}
                            className={`px-2.5 h-7 rounded-lg text-xs font-medium capitalize transition-colors ${statusFilter === s ? "bg-gray-900 dark:bg-white text-white dark:text-gray-900" : "bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400"}`}
                        >
                            {s}
                        </button>
                    ))}
                </div>
                {showFilters && (
                    <div className="flex gap-1 flex-wrap">
                        {(["all", "human", "ai", "paused"] as const).map(
                            (m) => (
                                <button
                                    key={m}
                                    onClick={() => setInterceptFilter(m)}
                                    className={`px-2 h-6 rounded text-[11px] font-medium capitalize transition-colors ${interceptFilter === m ? "bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400 border border-amber-300 dark:border-amber-800" : "bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400"}`}
                                >
                                    {m}
                                </button>
                            ),
                        )}
                    </div>
                )}
            </div>

            {/* Channel tabs — scrollable strip like Facebook Inbox */}
            <div className="flex overflow-x-auto border-b border-gray-100 dark:border-gray-800 scrollbar-none">
                {CHANNEL_TABS.map((tab) => {
                    const isActive = channelTab === tab.id;
                    const count = channelCounts[tab.id] ?? 0;
                    return (
                        <button
                            key={tab.id}
                            onClick={() => setChannelTab(tab.id)}
                            className={`flex items-center gap-1.5 px-3 py-2.5 text-xs font-semibold whitespace-nowrap flex-shrink-0 border-b-2 transition-all ${
                                isActive
                                    ? "border-amber-500 text-amber-600 dark:text-amber-400"
                                    : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:border-gray-300"
                            }`}
                        >
                            {tab.id !== "all" && (
                                <span
                                    style={{
                                        color: CHANNEL_CONFIG[tab.id as Channel]
                                            .color,
                                    }}
                                >
                                    {CHANNEL_CONFIG[tab.id as Channel].icon}
                                </span>
                            )}
                            {tab.label}
                            {count > 0 && (
                                <span className="bg-amber-500 text-white rounded-full text-[10px] font-bold min-w-[16px] h-4 flex items-center justify-center px-1">
                                    {count}
                                </span>
                            )}
                        </button>
                    );
                })}
            </div>

            {/* Conversation list */}
            <div className="flex-1 overflow-y-auto">
                {filteredConvs.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-40 text-sm text-gray-400 dark:text-gray-500 gap-2">
                        <svg
                            className="w-8 h-8 opacity-30"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                        >
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={1.5}
                                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                            />
                        </svg>
                        No conversations found
                    </div>
                ) : (
                    filteredConvs.map((conv) => {
                        const isActive = !isMobile && activeConvId === conv.id;
                        const channelCfg = CHANNEL_CONFIG[conv.channel];
                        return (
                            <button
                                key={conv.id}
                                onClick={() => selectConv(conv.id)}
                                className={`w-full flex items-center gap-3 px-3 py-3 border-b border-gray-50 dark:border-gray-800/60 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors text-left touch-manipulation ${
                                    isActive
                                        ? "bg-amber-50 dark:bg-amber-950/20 border-l-2 border-l-amber-500"
                                        : "border-l-2 border-l-transparent"
                                } ${conv.status === "closed" ? "opacity-60" : ""}`}
                            >
                                {/* Avatar with channel dot */}
                                <div className="relative flex-shrink-0">
                                    <Avatar name={conv.name} size="sm" />
                                    {/* Channel icon dot */}
                                    <span
                                        className="absolute -bottom-0.5 -right-0.5 w-4 h-4 rounded-full flex items-center justify-center ring-2 ring-white dark:ring-gray-900"
                                        style={{
                                            backgroundColor: channelCfg.color,
                                        }}
                                    >
                                        <span
                                            className="text-white"
                                            style={{ fontSize: 8 }}
                                        >
                                            {channelCfg.icon}
                                        </span>
                                    </span>
                                </div>

                                {/* Content */}
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center justify-between gap-1 mb-0.5">
                                        <span
                                            className={`text-sm font-semibold truncate ${isActive ? "text-amber-700 dark:text-amber-300" : "text-gray-900 dark:text-white"}`}
                                        >
                                            {conv.name}
                                        </span>
                                        <span className="text-[10px] text-gray-400 dark:text-gray-500 flex-shrink-0">
                                            {timeAgo(conv.last_message_at)}
                                        </span>
                                    </div>
                                    <div className="flex items-center justify-between gap-1">
                                        <span className="text-xs text-gray-500 dark:text-gray-400 truncate">
                                            {conv.last_message_preview}
                                        </span>
                                        <div className="flex items-center gap-1 flex-shrink-0">
                                            <InterceptBadge
                                                mode={conv.intercept_mode}
                                            />
                                            {conv.unread > 0 && (
                                                <span className="bg-amber-500 text-white text-[10px] font-bold rounded-full w-4 h-4 flex items-center justify-center">
                                                    {conv.unread}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            </button>
                        );
                    })
                )}
            </div>

            {/* Summary footer */}
            <div className="px-3 py-2 border-t border-gray-100 dark:border-gray-800 flex items-center justify-between">
                <span className="text-xs text-gray-400">
                    {filteredConvs.length} conversation
                    {filteredConvs.length !== 1 ? "s" : ""}
                </span>
                <div className="flex items-center gap-2 text-xs text-gray-400">
                    {ALL_CHANNELS.map((ch) => {
                        const n = conversations.filter(
                            (c) => c.channel === ch,
                        ).length;
                        if (!n) return null;
                        return (
                            <span
                                key={ch}
                                className="flex items-center gap-0.5"
                                title={CHANNEL_CONFIG[ch].label}
                            >
                                <span
                                    style={{ color: CHANNEL_CONFIG[ch].color }}
                                >
                                    {CHANNEL_CONFIG[ch].icon}
                                </span>
                                {n}
                            </span>
                        );
                    })}
                </div>
            </div>
        </div>
    );

    // ─── Thread panel ─────────────────────────────────────────────────────────────
    const threadPanel = (
        <div className="flex-1 flex flex-col overflow-hidden bg-gray-50 dark:bg-gray-950">
            {activeConv ? (
                <>
                    {/* Conversation header */}
                    <div className="flex items-center gap-3 px-4 py-3 bg-white dark:bg-gray-900 border-b border-gray-100 dark:border-gray-800 flex-shrink-0">
                        {isMobile && (
                            <button
                                onClick={() => setMobilePanel("list")}
                                className="text-amber-500 hover:text-amber-600 p-1 -ml-1 touch-manipulation"
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
                        <div className="relative flex-shrink-0">
                            <Avatar name={activeConv.name} size="sm" />
                            <span
                                className="absolute -bottom-0.5 -right-0.5 w-4 h-4 rounded-full flex items-center justify-center ring-2 ring-white dark:ring-gray-900"
                                style={{
                                    backgroundColor:
                                        CHANNEL_CONFIG[activeConv.channel]
                                            .color,
                                }}
                            >
                                <span
                                    className="text-white"
                                    style={{ fontSize: 8 }}
                                >
                                    {CHANNEL_CONFIG[activeConv.channel].icon}
                                </span>
                            </span>
                        </div>
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                                <span className="font-semibold text-gray-900 dark:text-white text-sm">
                                    {activeConv.name}
                                </span>
                                <span className="text-xs text-gray-400">
                                    via{" "}
                                    {CHANNEL_CONFIG[activeConv.channel].label}
                                </span>
                            </div>
                            <div className="flex items-center gap-2 text-xs text-gray-400">
                                <span>+{activeConv.wa_id}</span>
                                {activeConv.assigned_agent_id && (
                                    <>
                                        <span>·</span>
                                        <span className="text-amber-600 dark:text-amber-400">
                                            {
                                                agents.find(
                                                    (a) =>
                                                        a.id ===
                                                        activeConv.assigned_agent_id,
                                                )?.name
                                            }
                                        </span>
                                    </>
                                )}
                            </div>
                        </div>
                        <div className="flex items-center gap-2 flex-shrink-0">
                            <InterceptBadge mode={activeConv.intercept_mode} />
                            <span
                                className={`text-xs px-2 py-0.5 rounded border font-medium ${
                                    activeConv.status === "open"
                                        ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800"
                                        : "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400 border-gray-200 dark:border-gray-700"
                                }`}
                            >
                                {activeConv.status}
                            </span>
                        </div>
                    </div>

                    {/* Action toolbar */}
                    <div className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-gray-900 border-b border-gray-100 dark:border-gray-800 flex-shrink-0 overflow-x-auto scrollbar-none">
                        {activeConv.intercept_mode === "ai" && (
                            <Btn
                                size="xs"
                                onClick={() => intercept(activeConv.id)}
                                variant="primary"
                            >
                                ⚡ Intercept
                            </Btn>
                        )}
                        {activeConv.intercept_mode === "human" && (
                            <Btn
                                size="xs"
                                onClick={() => release(activeConv.id)}
                                variant="outline"
                            >
                                ↩ Release to AI
                            </Btn>
                        )}
                        {activeConv.intercept_mode !== "paused" && (
                            <Btn
                                size="xs"
                                onClick={() => pause(activeConv.id)}
                                variant="outline"
                            >
                                ⏸ Pause AI
                            </Btn>
                        )}
                        {activeConv.intercept_mode === "paused" && (
                            <Btn
                                size="xs"
                                onClick={() => release(activeConv.id)}
                                variant="blue"
                            >
                                ▶ Resume AI
                            </Btn>
                        )}
                        <Btn
                            size="xs"
                            onClick={() => setTransferModal(true)}
                            variant="outline"
                        >
                            ⇄ Transfer
                        </Btn>
                        <Btn
                            size="xs"
                            onClick={() => setNoteModal(true)}
                            variant="outline"
                        >
                            📝 Note
                        </Btn>
                        {activeConv.status === "open" && (
                            <Btn
                                size="xs"
                                onClick={() => closeConv(activeConv.id)}
                                variant="danger"
                            >
                                ✓ Close
                            </Btn>
                        )}
                    </div>

                    {/* Messages */}
                    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
                        {activeMessages.map((msg) => {
                            const isOut = msg.direction === "outbound";
                            const isNote = msg.isNote ?? false;
                            const senderLabel: Record<string, string> = {
                                ai: "AI Assistant",
                                human_agent:
                                    agents.find((a) => a.id === "a1")?.name ??
                                    "Agent",
                                user: activeConv.name,
                            };
                            const senderColor: Record<string, string> = {
                                ai: "text-blue-500",
                                human_agent: "text-amber-600",
                                user: "text-gray-400",
                            };

                            return (
                                <div
                                    key={msg.id}
                                    className={`flex flex-col ${isOut ? "items-end" : "items-start"}`}
                                >
                                    <span
                                        className={`text-[11px] mb-1 font-medium ${senderColor[msg.sender] ?? "text-gray-400"}`}
                                    >
                                        {senderLabel[msg.sender] ?? msg.sender}{" "}
                                        · {timeAgo(msg.created_at)}
                                    </span>
                                    <div
                                        className={`max-w-[78%] px-3.5 py-2.5 text-sm leading-relaxed rounded-2xl ${
                                            isNote
                                                ? "bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200 rounded-br-md"
                                                : isOut
                                                  ? "bg-amber-500 text-white rounded-br-md"
                                                  : "bg-white dark:bg-gray-800 text-gray-900 dark:text-white border border-gray-100 dark:border-gray-700 rounded-bl-md shadow-sm"
                                        }`}
                                    >
                                        {isNote && (
                                            <span className="text-xs font-semibold text-amber-600 dark:text-amber-400 block mb-1">
                                                📝 Internal Note
                                            </span>
                                        )}
                                        {msg.text}
                                    </div>
                                </div>
                            );
                        })}

                        {/* AI Draft */}
                        {draftVisible &&
                            activeConv.intercept_mode === "human" && (
                                <div className="flex flex-col items-end">
                                    <span className="text-[11px] mb-1 font-medium text-blue-500">
                                        AI Draft · awaiting approval
                                    </span>
                                    <div className="max-w-[78%] px-3.5 py-3 rounded-2xl rounded-br-md bg-blue-50 dark:bg-blue-950/30 border border-dashed border-blue-300 dark:border-blue-700 text-gray-800 dark:text-gray-200 text-sm leading-relaxed">
                                        {AI_DRAFT}
                                        <div className="flex gap-2 mt-3 pt-3 border-t border-blue-200 dark:border-blue-800">
                                            <Btn
                                                size="xs"
                                                onClick={approveDraft}
                                                variant="blue"
                                            >
                                                ✓ Approve & Send
                                            </Btn>
                                            <Btn
                                                size="xs"
                                                onClick={() =>
                                                    setDraftVisible(false)
                                                }
                                                variant="ghost"
                                            >
                                                Discard
                                            </Btn>
                                        </div>
                                    </div>
                                </div>
                            )}
                        <div ref={messagesEndRef} />
                    </div>

                    {/* Reply composer */}
                    <div className="bg-white dark:bg-gray-900 border-t border-gray-100 dark:border-gray-800 px-4 pt-3 pb-3 flex-shrink-0">
                        {/* Channel indicator */}
                        <div className="flex items-center gap-2 mb-2">
                            <span className="text-xs text-gray-400">
                                Replying via
                            </span>
                            <span
                                className="flex items-center gap-1 text-xs font-medium"
                                style={{
                                    color: CHANNEL_CONFIG[activeConv.channel]
                                        .color,
                                }}
                            >
                                {CHANNEL_CONFIG[activeConv.channel].icon}
                                {CHANNEL_CONFIG[activeConv.channel].label}
                            </span>
                        </div>
                        <div className="flex gap-2 items-end">
                            <textarea
                                value={replyText}
                                onChange={(e) => setReplyText(e.target.value)}
                                placeholder={
                                    activeConv.intercept_mode === "human"
                                        ? `Reply as agent via ${CHANNEL_CONFIG[activeConv.channel].label}…`
                                        : "Intercept conversation to reply manually…"
                                }
                                disabled={
                                    activeConv.intercept_mode !== "human" ||
                                    activeConv.status === "closed"
                                }
                                onKeyDown={(e) => {
                                    if (e.key === "Enter" && !e.shiftKey) {
                                        e.preventDefault();
                                        sendReply();
                                    }
                                }}
                                rows={2}
                                className="flex-1 px-3 py-2.5 text-sm bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-500 resize-none disabled:opacity-40 disabled:cursor-not-allowed"
                                style={{ fontSize: 16 }}
                            />
                            <Btn
                                onClick={sendReply}
                                disabled={
                                    activeConv.intercept_mode !== "human" ||
                                    activeConv.status === "closed"
                                }
                                variant="primary"
                                size="sm"
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
                                        d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
                                    />
                                </svg>
                                Send
                            </Btn>
                        </div>
                        {!isMobile && (
                            <p className="text-[11px] text-gray-400 mt-1.5">
                                Enter to send · Shift+Enter for new line
                            </p>
                        )}
                    </div>
                </>
            ) : (
                <div className="flex-1 flex flex-col items-center justify-center text-gray-400 gap-3">
                    <div className="w-16 h-16 rounded-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center">
                        <svg
                            className="w-8 h-8 opacity-40"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                        >
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={1.5}
                                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                            />
                        </svg>
                    </div>
                    <p className="text-sm font-medium">
                        Select a conversation to start
                    </p>
                </div>
            )}
        </div>
    );

    return (
        <>
            <div className="flex flex-1 overflow-hidden">
                {isMobile ? (
                    mobilePanel === "list" ? (
                        listPanel
                    ) : (
                        threadPanel
                    )
                ) : (
                    <>
                        {listPanel}
                        {threadPanel}
                    </>
                )}
            </div>

            {/* Transfer modal */}
            <Modal
                show={transferModal}
                onClose={() => setTransferModal(false)}
                title="Transfer Conversation"
            >
                <div className="space-y-2">
                    {agents
                        .filter((a) => a.id !== "a1" && a.is_available)
                        .map((agent) => (
                            <button
                                key={agent.id}
                                onClick={() => transferConv(agent.id)}
                                className="w-full flex items-center gap-3 p-3 rounded-xl border border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors text-left touch-manipulation"
                            >
                                <div className="relative">
                                    <Avatar name={agent.name} size="sm" />
                                    <div
                                        className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full ring-2 ring-white dark:ring-gray-900 ${agent.is_available ? "bg-emerald-500" : "bg-gray-400"}`}
                                    />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="text-sm font-semibold text-gray-900 dark:text-white">
                                        {agent.name}
                                    </div>
                                    <div className="text-xs text-gray-400">
                                        {agent.active_convs} active
                                        conversations
                                    </div>
                                </div>
                                <RoleBadge role={agent.role} />
                            </button>
                        ))}
                </div>
            </Modal>

            {/* Note modal */}
            <Modal
                show={noteModal}
                onClose={() => setNoteModal(false)}
                title="Add Internal Note"
            >
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                    Notes are visible to agents only and will not be sent to the
                    customer.
                </p>
                <InputField
                    label="Note"
                    value={noteText}
                    onChange={setNoteText}
                    placeholder="Write your internal note…"
                />
                <div className="flex gap-2 mt-2">
                    <Btn onClick={addNote} variant="primary">
                        Save Note
                    </Btn>
                    <Btn onClick={() => setNoteModal(false)} variant="outline">
                        Cancel
                    </Btn>
                </div>
            </Modal>
        </>
    );
}