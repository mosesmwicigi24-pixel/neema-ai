import axios from "axios";
import type {
    Conversation,
    Channel,
    Message,
    Agent,
    Order,
    OrderStatus,
    CatalogItem,
    MessagesMap,
    PaymentMethod,
} from "@/types";

export const api = axios.create({
    baseURL: process.env.NEXT_PUBLIC_API_URL,
    withCredentials: true,
});

// ── Base ──────────────────────────────────────────────────────────────────────

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

// ── Token helpers ─────────────────────────────────────────────────────────────

function getStoredToken(): string | undefined {
    if (typeof window === "undefined") return undefined;
    return (window as any).__neema_token as string | undefined;
}
function setStoredToken(t: string) {
    if (typeof window !== "undefined") (window as any).__neema_token = t;
}
function getStoredRefreshToken(): string | undefined {
    if (typeof window === "undefined") return undefined;
    return (window as any).__neema_refresh_token as string | undefined;
}
function setStoredRefreshToken(t: string) {
    if (typeof window !== "undefined") (window as any).__neema_refresh_token = t;
}

/** Dispatch a DOM event so the UI can show a "session expired" screen. */
function emitSessionExpired() {
    if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("neema:session-expired"));
    }
}

// ── Silent token refresh ──────────────────────────────────────────────────────

// Shared promise so concurrent 401s only trigger one refresh request
let refreshPromise: Promise<string | null> | null = null;

async function silentRefresh(): Promise<string | null> {
    if (refreshPromise) return refreshPromise;

    refreshPromise = (async () => {
        const refreshToken = getStoredRefreshToken();
        if (!refreshToken) return null;
        try {
            const res = await fetch(`${BASE}/auth/refresh`, {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify({ refresh_token: refreshToken }),
            });
            if (!res.ok) return null;
            const data = await res.json();
            setStoredToken(data.access_token);
            setStoredRefreshToken(data.refresh_token);
            // Nudge NextAuth so useSession() reflects the new token too
            try {
                const { getSession } = await import("next-auth/react");
                await getSession();
            } catch { /* fine — window tokens already updated */ }
            return data.access_token as string;
        } catch {
            return null;
        } finally {
            refreshPromise = null;
        }
    })();

    return refreshPromise;
}

// ── Auth headers ──────────────────────────────────────────────────────────────

async function authHeaders(token?: string): Promise<HeadersInit> {
    const t = token ?? getStoredToken();

    // Fallback: call getSession() if window cache is cold (e.g. hard refresh)
    if (!t) {
        try {
            const { getSession } = await import("next-auth/react");
            const session = await getSession();
            const sessionToken = (session as any)?.accessToken as string | undefined;
            if (sessionToken) {
                setStoredToken(sessionToken);
                const refresh = (session as any)?.refreshToken as string | undefined;
                if (refresh) setStoredRefreshToken(refresh);
                return {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${sessionToken}`,
                };
            }
        } catch { /* not in browser context */ }
    }

    return {
        "Content-Type": "application/json",
        ...(t ? { Authorization: `Bearer ${t}` } : {}),
    };
}

// ── Core request ──────────────────────────────────────────────────────────────

async function req<T>(
    method: string,
    path: string,
    body?: unknown,
    _retrying = false,
): Promise<T> {
    const headers = await authHeaders();
    const res = await fetch(`${BASE}${path}`, {
        method,
        headers,
        credentials: "include",
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });

    // On 401: attempt a silent token refresh, then retry once
    if (res.status === 401 && !_retrying) {
        const newToken = await silentRefresh();
        if (newToken) {
            const retryRes = await fetch(`${BASE}${path}`, {
                method,
                headers: await authHeaders(newToken),
                credentials: "include",
                ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
            });
            if (retryRes.ok) {
                if (retryRes.status === 204) return undefined as T;
                return retryRes.json();
            }
        }
        // Refresh failed — session is truly dead
        emitSessionExpired();
        throw new Error("Session expired. Please sign in again.");
    }

    if (!res.ok) {
        const err = await res.text().catch(() => String(res.status));
        let detail = err;
        try { detail = JSON.parse(err)?.detail ?? err; } catch {}
        if (detail === "Token expired" || res.status === 401) {
            emitSessionExpired();
            throw new Error("Session expired. Please sign in again.");
        }
        throw new Error(`${method} ${path} → ${res.status}: ${detail}`);
    }

    if (res.status === 204) return undefined as T;
    return res.json();
}

const get = <T>(path: string) => req<T>("GET", path);
const post = <T>(path: string, body: unknown) => req<T>("POST", path, body);
const patch = <T>(path: string, body: unknown) => req<T>("PATCH", path, body);
const del = <T>(path: string) => req<T>("DELETE", path);

// ── Conversations ─────────────────────────────────────────────────────────────

export interface ApiConversation {
    id: string;
    wa_id: string;
    intercept_mode: "ai" | "human" | "paused";
    assigned_agent_id: string | null;
    assigned_agent_name?: string | null;
    intercept_since: string | null;
    last_message_at: string | null;
    last_message_preview: string | null;
    status: "open" | "closed";
    created_at: string;
    updated_at: string;
    name?: string;
    channel?: string;
    unread?: number;
}

export const conversationsApi = {
    list: (params?: { mode?: string; status?: string }) => {
        const q = params
            ? "?" +
              new URLSearchParams(params as Record<string, string>).toString()
            : "";
        return get<ApiConversation[]>(`/admin/conversations${q}`);
    },
    get: (id: string) => get<ApiConversation>(`/admin/conversations/${id}`),
    messages: (id: string) =>
        get<Message[]>(`/admin/conversations/${id}/messages`),
    intercept: (id: string) =>
        post<ApiConversation>(`/admin/conversations/${id}/intercept`, {}),
    release: (id: string) =>
        post<ApiConversation>(`/admin/conversations/${id}/release`, {}),
    transfer: (id: string, agentId: string) =>
        post<ApiConversation>(`/admin/conversations/${id}/transfer`, {
            agent_id: agentId,
        }),
    sendReply: (id: string, text: string) =>
        post<Message>(`/admin/conversations/${id}/reply`, { text }),
    approveDraft: (id: string, text?: string) =>
        post<{ ok: boolean }>(`/admin/conversations/${id}/approve-draft`, {
            text: text ?? null,
        }),
    latestDraft: (id: string) =>
        get<{ draft: string | null }>(
            `/admin/conversations/${id}/latest-draft`,
        ),
    generateDraft: (id: string) =>
        post<{ draft: string }>(
            `/admin/conversations/${id}/generate-draft`,
            {},
        ),
    addNote: (id: string, text: string) =>
        post<Message>(`/admin/conversations/${id}/note`, { text }),
    close: (id: string) =>
        post<{ ok: boolean }>(`/admin/conversations/${id}/release`, {}),
};

// ── Agents ────────────────────────────────────────────────────────────────────

export interface ApiAgent {
    id: string;
    name: string;
    email: string;
    role: "admin" | "agent" | "readonly";
    is_available: boolean;
    is_superuser: boolean;
    active_convs: number;
    avatar_url: string | null;
    created_at: string;
    last_seen_at: string | null;
}

export interface CreateAgentPayload {
    name: string;
    email: string;
    password: string;
    role: "admin" | "agent" | "readonly";
}

export const agentsApi = {
    list: () => get<ApiAgent[]>("/admin/agents"),
    get: (id: string) => get<ApiAgent>(`/admin/agents/${id}`),
    create: (p: CreateAgentPayload) => post<ApiAgent>("/admin/agents", p),
    update: (id: string, p: Partial<ApiAgent & { password?: string }>) =>
        patch<ApiAgent>(`/admin/agents/${id}`, p),
    delete: (id: string) => del<void>(`/admin/agents/${id}`),
    toggleAvailable: (id: string, is_available: boolean) =>
        patch<ApiAgent>(`/admin/agents/${id}`, { is_available }),
};

// ── Catalog ───────────────────────────────────────────────────────────────────

export interface ApiCatalogItem {
    id: string;
    sku: string;
    name: string;
    aliases: string[];
    price: number;
    unit: string | null;
    category: string | null;
    description: string | null;
    in_stock: boolean;
    updated_at: string;
}

export interface CreateCatalogPayload {
    sku: string;
    name: string;
    price: number;
    unit?: string;
    category?: string;
    description?: string;
    aliases?: string[];
    in_stock?: boolean;
}

export const catalogApi = {
    list: (params?: { category?: string; search?: string }) => {
        const q = params
            ? "?" +
              new URLSearchParams(params as Record<string, string>).toString()
            : "";
        return get<ApiCatalogItem[]>(`/admin/catalog${q}`);
    },
    create: (p: CreateCatalogPayload) =>
        post<ApiCatalogItem>("/admin/catalog", p),
    update: (id: string, p: Partial<CreateCatalogPayload>) =>
        patch<ApiCatalogItem>(`/admin/catalog/${id}`, p),
    toggleStock: (id: string, in_stock: boolean) =>
        patch<ApiCatalogItem>(`/admin/catalog/${id}`, { in_stock }),
    delete: (id: string) => del<void>(`/admin/catalog/${id}`),
};

// ── Orders ────────────────────────────────────────────────────────────────────

export interface ApiOrder {
    id: string;
    wa_id: string;
    session_id: string | null;
    event_type: string | null;
    items: OrderItem[];
    subtotal: number;
    currency: string;
    status: "open" | "pending" | "confirmed" | "delivered" | "cancelled";
    payment_status: string;
    fulfillment_status: string;
    reply_text: string | null;
    channel: string;
    state: Record<string, unknown>;
    created_at: string;
    updated_at: string;
    contact_name?: string;
    contact_phone?: string;
}

export interface OrderItem {
    name: string;
    qty: number;
    unit: number;
    total: number;
    sku?: string;
}

export const ordersApi = {
    list: (params?: { status?: string; wa_id?: string }) => {
        const q = params
            ? "?" +
              new URLSearchParams(params as Record<string, string>).toString()
            : "";
        return get<ApiOrder[]>(`/admin/orders${q}`);
    },
    get: (id: string) => get<ApiOrder>(`/admin/orders/${id}`),
    updateStatus: (
        id: string,
        status: string,
        payment_status?: string,
        fulfillment_status?: string,
    ) =>
        patch<ApiOrder>(`/admin/orders/${id}`, {
            status,
            payment_status,
            fulfillment_status,
        }),
};

// ── Stats ─────────────────────────────────────────────────────────────────────

export interface ApiStats {
    open_conversations: number;
    human_conversations: number;
    ai_conversations: number;
    active_agents: number;
    total_agents: number;
    total_revenue: number;
    total_orders: number;
    pending_orders: number;
    delivered_orders: number;
    confirmed_orders: number;
    cancelled_orders: number;
    in_stock_items: number;
    total_items: number;
    channel_breakdown: { channel: Channel; count: number; open: number }[];
}

export const statsApi = {
    overview: () => get<ApiStats>("/admin/stats"),
};

// ── Profile ───────────────────────────────────────────────────────────────────

export const profileApi = {
    me: () => get<ApiAgent>("/admin/me"),
    update: (p: { name?: string; email?: string; password?: string }) =>
        patch<ApiAgent>("/admin/me", p),
};

// ── Data mappers (API → UI types) ─────────────────────────────────────────────

export function mapConversation(c: ApiConversation): Conversation {
    return {
        id: c.id,
        wa_id: c.wa_id,
        name: c.name ?? c.wa_id,
        contact_name: c.name ?? c.wa_id,
        contact_phone: c.wa_id,
        channel: (c.channel ?? "whatsapp") as Channel,
        intercept_mode: c.intercept_mode,
        status: c.status,
        last_message_preview: c.last_message_preview ?? "",
        last_message: c.last_message_preview ?? "",
        last_message_at: c.last_message_at ?? c.created_at,
        assigned_agent_id: c.assigned_agent_id,
        assigned_agent_name: c.assigned_agent_name ?? null,
        unread: c.unread ?? 0,
        unread_count: c.unread ?? 0,
    };
}

export function mapAgent(a: ApiAgent): Agent {
    return {
        id: a.id,
        name: a.name,
        email: a.email,
        role: a.role,
        is_available: a.is_available,
        is_superuser: a.is_superuser,
        active_convs: a.active_convs,
        avatar_url: a.avatar_url,
        created_at: a.created_at,
        joined_at: a.created_at,
        last_seen_at: a.last_seen_at,
        permissions: [],
        department: "",
    };
}

export function mapCatalogItem(c: ApiCatalogItem): CatalogItem {
    return {
        id: c.id,
        sku: c.sku,
        name: c.name,
        aliases: c.aliases,
        price: c.price,
        unit: c.unit ?? "",
        category: c.category ?? "General",
        description: c.description ?? "",
        in_stock: c.in_stock,
    };
}

export function mapOrder(o: ApiOrder): Order {
    return {
        id: o.id,
        wa_id: o.wa_id,
        customer_name: o.contact_name ?? o.wa_id,
        contact_name: o.contact_name ?? o.wa_id,
        contact_phone: o.wa_id,
        channel: o.channel,
        items: (o.items ?? []).map((i) => ({
            catalog_item_id: i.sku ?? "",
            sku: i.sku ?? "",
            name: i.name,
            qty: i.qty,
            quantity: i.qty,
            unit: i.unit,
            unit_price: i.unit,
            total: i.total,
        })),
        total: o.subtotal,
        subtotal: o.subtotal,
        status: (o.status === "open" ? "pending" : o.status) as OrderStatus,
        payment: "mpesa" as PaymentMethod,
        currency: o.currency,
        created_at: o.created_at,
        notes: o.reply_text ?? undefined,
    };
}