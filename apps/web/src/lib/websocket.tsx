"use client";
import {
    createContext,
    useContext,
    useEffect,
    useRef,
    useState,
    useCallback,
    ReactNode,
} from "react";
import { useSession } from "next-auth/react";
import type { Message, SystemEventKind } from "@/types";

// ── Native WebSocket wrapper ──────────────────────────────────────────────────
// The backend is a plain FastAPI WebSocket endpoint at /ws/{agent_id}.
// It is NOT a Socket.IO server — socket.io-client would fail the handshake.

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

    function emit(event: string, data: any) {
        listeners[event]?.forEach((h) => h(data));
    }

    function connect() {
        if (closed) return;
        ws = new WebSocket(url);

        ws.onopen = () => {
            emit("connect", null);
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
            if (pingInterval) { clearInterval(pingInterval); pingInterval = null; }
            emit("disconnect", null);
            if (!closed) setTimeout(connect, 2_000);
        };
    }

    connect();

    return {
        send: (data) => { if (ws?.readyState === WebSocket.OPEN) ws.send(data); },
        on: (event, handler) => {
            if (!listeners[event]) listeners[event] = new Set();
            listeners[event].add(handler);
        },
        off: (event, handler) => { listeners[event]?.delete(handler); },
        close: () => {
            closed = true;
            if (pingInterval) { clearInterval(pingInterval); pingInterval = null; }
            ws?.close();
        },
    };
}

// ── Derive a valid ws:// / wss:// URL from env ────────────────────────────────
function resolveWsUrl(agentId: string): string | null {
    // Try NEXT_PUBLIC_API_URL first, fall back to NEXT_PUBLIC_WS_URL, then same-origin.
    const raw =
        process.env.NEXT_PUBLIC_API_URL ||
        process.env.NEXT_PUBLIC_WS_URL ||
        (typeof window !== "undefined" ? window.location.origin : "");

    if (!raw) return null;

    const wsBase = raw
        .replace(/^https:\/\//, "wss://")
        .replace(/^http:\/\//, "ws://")
        .replace(/\/$/, "");

    // Guard: must start with ws:// or wss:// after replacement
    if (!wsBase.startsWith("ws://") && !wsBase.startsWith("wss://")) {
        console.warn("[WS] Could not derive a ws:// URL from:", raw);
        return null;
    }

    // Strip any /api path suffix — the WebSocket endpoint is at /ws/{id},
    // not /api/ws/{id}. NEXT_PUBLIC_API_URL often includes /api.
    const cleanBase = wsBase.replace(/\/api\/?$/, "");

    return `${cleanBase}/ws/${agentId}`;
}

// ── Context ───────────────────────────────────────────────────────────────────
const WsContext = createContext<NativeWs | null>(null);

export function WsProvider({ children }: { children: ReactNode }) {
    const { data: session } = useSession();
    // State (not a ref) so the socket PROPAGATES to context consumers the moment
    // it's created — otherwise components that don't re-render on their own (the
    // softphone) never see it and never attach their listeners.
    const [ws, setWs] = useState<NativeWs | null>(null);

    useEffect(() => {
        const agentId = (session as any)?.user?.id;
        if (!agentId) return;

        const url = resolveWsUrl(agentId);
        if (!url) {
            console.warn("[WS] No valid WebSocket URL — set NEXT_PUBLIC_API_URL");
            return;
        }

        const conn = createNativeWs(url);
        conn.on("connect",    () => console.log("[WS] connected →", url));
        conn.on("disconnect", () => console.log("[WS] disconnected"));
        conn.on("error",      () => console.warn("[WS] error — will reconnect"));
        setWs(conn);

        return () => {
            conn.close();
            setWs(null);
        };
    }, [(session as any)?.user?.id]);

    return (
        <WsContext.Provider value={ws}>
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
        return () => { ws.off("event", onEvent); };
    }, [ws, conversationId, onEvent]);
}

/**
 * Build a synthetic `system_event` Message from an `intercept_changed`
 * WebSocket broadcast. Lets ConversationsView inject a live divider pill
 * into the thread without waiting for the next full thread reload.
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
export interface AgentNotification {
    event: "notification";
    type:
        | "new_conversation"
        | "human_transfer"
        | "media_escalation"
        | "intercept"
        | "order_update"
        | "transfer"
        | "system"
        | "daily_summary"
        | string;
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