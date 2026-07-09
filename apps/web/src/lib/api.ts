import axios from "axios";
import type {
    Conversation,
    Channel,
    Message,
    SystemEventKind,
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

/**
 * Build auth headers.
 *
 * Token resolution order:
 *  1. window.__neema_token  (set synchronously in page.tsx render body)
 *  2. getSession() fallback (for edge cases where window cache is cold)
 */
async function authHeaders(): Promise<HeadersInit> {
    let token: string | undefined;

    if (typeof window !== "undefined") {
        token = (window as any).__neema_token;
    }

    if (!token) {
        try {
            const { getSession } = await import("next-auth/react");
            const session = await getSession();
            token = (session as any)?.accessToken;
            if (token && typeof window !== "undefined") {
                (window as any).__neema_token = token;
            }
        } catch {
            // Not in browser context — proceed unauthenticated
        }
    }

    return {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
}

/** Token only — no Content-Type header, for multipart FormData requests. */
async function authToken(): Promise<string | undefined> {
    if (typeof window !== "undefined" && (window as any).__neema_token) {
        return (window as any).__neema_token;
    }
    try {
        const { getSession } = await import("next-auth/react");
        const session = await getSession();
        return (session as any)?.accessToken;
    } catch {
        return undefined;
    }
}

async function req<T>(
    method: string,
    path: string,
    body?: unknown,
): Promise<T> {
    const headers = await authHeaders();
    const res = await fetch(`${BASE}${path}`, {
        method,
        headers,
        credentials: "include",
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });

    // ── 401 → fire session-expired event instead of throwing generically ──────
    if (res.status === 401) {
        if (typeof window !== "undefined") {
            delete (window as any).__neema_token;
            delete (window as any).__neema_refresh_token;
            window.dispatchEvent(new CustomEvent("neema:session-expired"));
        }
        throw new Error(`${method} ${path} → 401: Session expired`);
    }

    if (!res.ok) {
        const err = await res.text();
        throw new Error(`${method} ${path} → ${res.status}: ${err}`);
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
    avatar_url?: string | null;
    channel?: string;
    unread?: number;
    country?: string | null;
    country_iso?: string;
    flag_url?: string;
    tags?: string[];
}

/**
 * Raw shape returned by GET /admin/conversations/{id}/messages.
 * The backend merges regular messages and system-event rows into one
 * sorted list, distinguished by the `type` field.
 */
export interface ApiThreadItem {
    id: string;
    type: "message" | "system_event";
    direction: "inbound" | "outbound";
    sender: "user" | "ai" | "human_agent";
    text: string;
    created_at: string;
    // Message-specific
    isNote?: boolean;
    agent_name?: string | null;
    media_type?: string | null;
    media_id?: string | null;
    media_url?: string | null;
    media_caption?: string | null;
    mime_type?: string | null;
    filename?: string | null;
    // System-event-specific
    event_kind?: SystemEventKind | null;
    event_reason?: string | null;
}

/** Map a raw thread item from the API to the shared Message type. */
function mapThreadItem(raw: ApiThreadItem): Message {
    return {
        id:            raw.id,
        type:          raw.type ?? "message",
        direction:     raw.direction,
        sender:        raw.sender,
        text:          raw.text ?? "",
        created_at:    raw.created_at,
        isNote:        raw.isNote ?? false,
        agent_name:    raw.agent_name ?? undefined,
        // System event fields — undefined for regular messages
        event_kind:    raw.event_kind ?? undefined,
        event_reason:  raw.event_reason ?? undefined,
        // Media
        media_type:    (raw.media_type as Message["media_type"]) ?? null,
        media_id:      raw.media_id ?? null,
        media_url:     raw.media_url ?? null,
        media_caption: raw.media_caption ?? null,
        mime_type:     raw.mime_type ?? null,
        filename:      raw.filename ?? null,
    };
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

    /** Fetch the merged message + system-event timeline for a conversation. */
    messages: async (id: string): Promise<Message[]> => {
        const raw = await get<ApiThreadItem[]>(
            `/admin/conversations/${id}/messages`,
        );
        return raw.map(mapThreadItem);
    },

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
    clearHistory: (id: string) =>
        del<{ ok: boolean }>(`/admin/conversations/${id}/messages`),

    /**
     * Upload a file (image / document / video / audio) from the agent's
     * device and send it to the customer via WABA.
     * Uses multipart/form-data — bypasses the JSON req() helper.
     */
    uploadMedia: async (
        convId: string,
        file: File,
        caption?: string,
    ): Promise<Message> => {
        const token = await authToken();
        const form  = new FormData();
        form.append("file", file);
        if (caption) form.append("caption", caption);

        const res = await fetch(
            `${BASE}/admin/conversations/${convId}/upload-media`,
            {
                method: "POST",
                headers: token ? { Authorization: `Bearer ${token}` } : {},
                credentials: "include",
                body: form,
            },
        );
        if (res.status === 401) {
            if (typeof window !== "undefined") {
                delete (window as any).__neema_token;
                window.dispatchEvent(new CustomEvent("neema:session-expired"));
            }
            throw new Error("upload-media → 401: Session expired");
        }
        if (!res.ok) {
            const err = await res.text();
            throw new Error(`upload-media → ${res.status}: ${err}`);
        }
        return res.json();
    },

    /**
     * Send a media message by supplying an existing public URL
     * (e.g. already on S3 / CDN).
     */
    sendMediaUrl: (
        convId: string,
        media_url: string,
        media_type: "image" | "document" | "video" | "audio",
        caption?: string,
        filename?: string,
    ) =>
        post<Message>(`/admin/conversations/${convId}/reply-media`, {
            media_url,
            media_type,
            caption,
            filename,
        }),
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
    custom_role_id:    string | null;
    custom_permissions: string[] | null;
    role_name:         string | null;
    role_color:        string | null;
    role_permissions:  string[] | null;
}

export const agentsApi = {
    list: () => get<ApiAgent[]>("/admin/agents"),
    create: (body: { name: string; email: string; password: string; role?: string }) =>
        post<ApiAgent>("/admin/agents", body),
    update: (id: string, body: Partial<ApiAgent> & { password?: string }) =>
        patch<ApiAgent>(`/admin/agents/${id}`, body),
    delete: (id: string) => del<{ ok: boolean }>(`/admin/agents/${id}`),
    setAvailable: (id: string, is_available: boolean) =>
        patch<ApiAgent>(`/admin/agents/${id}`, { is_available }),
    toggleAvailable: (id: string, is_available: boolean) =>
        patch<ApiAgent>(`/admin/agents/${id}`, { is_available }),
};

// ── Catalog ───────────────────────────────────────────────────────────────────

export interface ApiCatalogItem {
    // Local-table rows have `id`; hub-sourced rows carry `hub_product_id` instead.
    id?: string;
    hub_product_id?: number | null;
    available_qty?: number | null;
    sku: string;
    name: string;
    aliases?: string[];
    price: number;
    unit?: string | null;
    category: string | null;
    description: string | null;
    in_stock: boolean;
    updated_at?: string;
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


// ── Custom Roles ──────────────────────────────────────────────────────────────

export interface CustomRole {
    id:          string;
    name:        string;
    description: string;
    color:       string;
    permissions: string[];
    protected:   boolean;
    created_at?: string;
}

export const rolesApi = {
    list:   ()                                     => get<CustomRole[]>("/admin/roles"),
    create: (r: Omit<CustomRole, "protected" | "created_at">) =>
                post<CustomRole>("/admin/roles", r),
    update: (id: string, r: Partial<Omit<CustomRole, "id" | "protected" | "created_at">>) =>
                patch<CustomRole>(`/admin/roles/${id}`, r),
    delete: (id: string)                           => del<{ ok: boolean }>(`/admin/roles/${id}`),
    assignToAgent: (agentId: string, roleId: string) =>
                patch<{ ok: boolean; permissions: string[] }>(
                    `/admin/agents/${agentId}/role`,
                    { custom_role_id: roleId }
                ),
};

// ── Data mappers (API → UI types) ─────────────────────────────────────────────

export function mapConversation(c: ApiConversation): Conversation {
    return {
        id: c.id,
        wa_id: c.wa_id,
        name: c.name ?? null,
        contact_name: c.name ?? null,
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
        country_iso: c.country_iso,
        country:     c.country     ?? null,
        flag_url:    c.flag_url,
        tags:        c.tags        ?? [],
    };
}

export function mapAgent(a: ApiAgent): Agent {
    const permissions: string[] =
        a.custom_permissions ?? a.role_permissions ?? [];

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
        permissions,
        custom_role_id:   a.custom_role_id   ?? null,
        custom_permissions: a.custom_permissions ?? null,
        role_name:        a.role_name        ?? null,
        role_color:       a.role_color       ?? null,
        role_permissions: a.role_permissions ?? null,
        department: "",
    };
}

export function mapCatalogItem(c: ApiCatalogItem): CatalogItem {
    return {
        // Hub rows have no local `id` — synthesise a stable one for React keys.
        id: c.id ?? String(c.hub_product_id ?? c.sku),
        sku: c.sku,
        name: c.name,
        aliases: c.aliases ?? [],
        price: c.price,
        unit: c.unit ?? "",
        category: c.category ?? "General",
        description: c.description ?? "",
        in_stock: c.in_stock,
        hub_product_id: c.hub_product_id ?? null,
        available_qty: c.available_qty ?? null,
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