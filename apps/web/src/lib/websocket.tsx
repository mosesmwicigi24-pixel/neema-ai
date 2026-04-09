"use client";
import { createContext, useContext, useEffect, useRef, ReactNode } from "react";
import { io, Socket } from "socket.io-client";
import { useSession } from "next-auth/react";
import type { Message, SystemEventKind } from "@/types";

const WsContext = createContext<Socket | null>(null);

export function WsProvider({ children }: { children: ReactNode }) {
    const { data: session } = useSession();
    const socketRef = useRef<Socket | null>(null);

    useEffect(() => {
        if (!session?.user?.id) return;

        const socket = io(process.env.NEXT_PUBLIC_WS_URL!, {
            path: "/ws",
            query: { agentId: session.user.id },
            auth: { token: session.accessToken },
            transports: ["websocket"],
        });

        socket.on("connect", () => console.log("[WS] connected"));
        socket.on("disconnect", () => console.log("[WS] disconnected"));
        socketRef.current = socket;

        return () => {
            socket.disconnect();
        };
    }, [session?.user?.id]);

    return (
        <WsContext.Provider value={socketRef.current}>
            {children}
        </WsContext.Provider>
    );
}

export const useWs = () => useContext(WsContext);

// ── Hook: subscribe to live events for a specific conversation ────────────────
export function useConversationEvents(
    conversationId: string,
    onEvent: (event: any) => void,
) {
    const socket = useWs();

    useEffect(() => {
        if (!socket || !conversationId) return;
        socket.emit("join_conversation", { conversationId });
        socket.on("event", onEvent);
        return () => {
            socket.off("event", onEvent);
        };
    }, [socket, conversationId, onEvent]);
}

/**
 * Build a synthetic `system_event` Message from an `intercept_changed`
 * WebSocket broadcast.  This lets ConversationsView inject a live divider
 * pill into the thread without waiting for the next full thread reload.
 *
 * Returns `null` for broadcasts that don't need a visual event bubble
 * (e.g. simple mode changes with no eventKind payload).
 */
export function buildSystemEventFromWs(wsEvent: any): Message | null {
    const kind = wsEvent.eventKind as SystemEventKind | undefined;
    if (!kind) return null;

    // Human-readable pill text — mirrors the backend ACTION_LABEL map
    const labelMap: Record<SystemEventKind, string> = {
        escalated:     "Escalated — needs human",
        flag:          "Flagged: Needs Attention",
        intercept:     wsEvent.eventAgentName
                           ? `Picked up by ${wsEvent.eventAgentName}`
                           : "Picked up by agent",
        release:       wsEvent.eventAgentName
                           ? `Released to AI by ${wsEvent.eventAgentName}`
                           : "Released to AI",
        transfer:      wsEvent.eventNote
                           ? `Transferred — ${wsEvent.eventNote}`
                           : "Transferred",
        approve_draft: "AI draft approved",
    };

    return {
        // Prefix with "live-" so the thread dedup check ignores it until a
        // real reload confirms the persisted DB id
        id:           `live-evt-${Date.now()}`,
        type:         "system_event",
        direction:    "outbound",
        sender:       "ai",
        text:         labelMap[kind] ?? kind,
        created_at:   new Date().toISOString(),
        event_kind:   kind,
        event_reason: wsEvent.eventReason ?? null,
        agent_name:   wsEvent.eventAgentName ?? null,
    };
}

// ── Agent notification type ───────────────────────────────────────────────────
export interface AgentNotification {
    event: "notification";
    type:
        | "new_conversation"
        | "human_transfer"
        | "order_update"
        | "daily_summary";
    title: string;
    body: string;
    wa_id?: string;
    ts: string;
    data: Record<string, unknown>;
}

// ── Hook: subscribe to agent-level notifications ──────────────────────────────
export function useAgentNotifications(
    onNotification: (n: AgentNotification) => void,
) {
    const socket = useWs();

    useEffect(() => {
        if (!socket) return;
        const handler = (e: any) => {
            if (e.event === "notification") onNotification(e);
        };
        socket.on("event", handler);
        return () => {
            socket.off("event", handler);
        };
    }, [socket, onNotification]);
}