"use client";
import {
    createContext,
    useContext,
    useEffect,
    useRef,
    useCallback,
    ReactNode,
} from "react";
import { useSession } from "next-auth/react";
import type { Message, SystemEventKind } from "@/types";

// ── Native WebSocket wrapper ──────────────────────────────────────────────────
// The backend is a plain FastAPI WebSocket endpoint at /ws/{agent_id}.
// It is NOT a Socket.IO server — using socket.io-client here would fail the
// handshake silently.  We use the browser's native WebSocket instead.

interface NativeWs {
    send: (data: string) => void;
    on: (event: string, handler: (data: any) => void) => void;
    off: (event: string, handler: (data: any) => void) => void;
    close: () => void;
}

function createNativeWs(url: string): NativeWs {
    const listeners: Record<string, Set<(data: any) => void>> = {};
    let ws: WebSocket | null = null;
    let closed = false;
    let pingInterval: ReturnType<typeof setInterval> | null = null;

    function connect() {
        if (closed) return;
        ws = new WebSocket(url);

        ws.onopen = () => {
            emit("connect", null);
            // Send pings every 25s to keep the connection alive
            pingInterval = setInterval(() => {
                if (ws?.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: "ping" }));
                }
            }, 25_000);
        };

        ws.onmessage = (msg) => {
            try {
                const data = JSON.parse(msg.data);
                emit("event", data);
            } catch {
                // ignore malformed frames
            }
        };

        ws.onerror = () => emit("error", null);

        ws.onclose = () => {
            if (pingInterval) clearInterval(pingInterval);
            emit("disconnect", null);
            // Reconnect after 2s unless explicitly closed
            if (!closed) setTimeout(connect, 2_000);
        };
    }

    function emit(event: string, data: any) {
        listeners[event]?.forEach((h) => h(data));
    }

    connect();

    return {
        send: (data) => {
            if (ws?.readyState === WebSocket.OPEN) ws.send(data);
        },
        on: (event, handler) => {
            if (!listeners[event]) listeners[event] = new Set();
            listeners[event].add(handler);
        },
        off: (event, handler) => {
            listeners[event]?.delete(handler);
        },
        close: () => {
            closed = true;
            if (pingInterval) clearInterval(pingInterval);
            ws?.close();
        },
    };
}

// ── Context ───────────────────────────────────────────────────────────────────
const WsContext = createContext<NativeWs | null>(null);

export function WsProvider({ children }: { children: ReactNode }) {
    const { data: session } = useSession();
    const wsRef = useRef<NativeWs | null>(null);

    useEffect(() => {
        const agentId = (session as any)?.user?.id;
        if (!agentId) return;

        const base = (process.env.NEXT_PUBLIC_WS_URL ?? "").replace(/^http/, "ws");
        const url = `${base}/ws/${agentId}`;

        const ws = createNativeWs(url);
        wsRef.current = ws;

        ws.on("connect",    () => console.log("[WS] connected"));
        ws.on("disconnect", () => console.log("[WS] disconnected"));
        ws.on("error",      () => console.warn("[WS] error — will reconnect"));

        return () => {
            ws.close();
            wsRef.current = null;
        };
    }, [(session as any)?.user?.id]);

    return (
        <WsContext.Provider value={wsRef.current}>
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
    const ws = useWs();

    useEffect(() => {
        if (!ws || !conversationId) return;
        ws.on("event", onEvent);
        return () => {
            ws.off("event", onEvent);
        };
    }, [ws, conversationId, onEvent]);
}

/**
 * Build a synthetic `system_event` Message from an `intercept_changed`
 * WebSocket broadcast. Lets ConversationsView inject a live divider pill
 * into the thread without waiting for the next full thread reload.
 *
 * Returns `null` for broadcasts that don't need a visual event bubble.
 */
export function buildSystemEventFromWs(wsEvent: any): Message | null {
    const kind = wsEvent.eventKind as SystemEventKind | undefined;
    if (!kind) return null;

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
// Covers all event types the backend can send to ws:channel:agents:*
export interface AgentNotification {
    event: "notification";
    type:
        | "new_conversation"
        | "human_transfer"
        | "media_escalation"   // n8n /escalate endpoint
        | "intercept"          // agent pickup / AI escalation
        | "order_update"
        | "transfer"
        | "system"
        | "daily_summary"
        | string;              // forward-compat: don't drop unknown types
    title: string;
    body: string;
    wa_id?: string;
    conversationId?: string;
    conv_id?: string;
    ts?: string;
    data?: Record<string, unknown>;
}

// ── Hook: subscribe to agent-level notifications ──────────────────────────────
export function useAgentNotifications(
    onNotification: (n: AgentNotification) => void,
) {
    const ws = useWs();

    // Stable handler ref so adding/removing the listener doesn't thrash on re-renders
    const cbRef = useRef(onNotification);
    useEffect(() => { cbRef.current = onNotification; }, [onNotification]);

    const handler = useCallback((e: any) => {
        if (e?.event === "notification") cbRef.current(e as AgentNotification);
    }, []);

    useEffect(() => {
        if (!ws) return;
        ws.on("event", handler);
        return () => ws.off("event", handler);
    }, [ws, handler]);
}