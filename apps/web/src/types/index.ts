// ── Channel types ─────────────────────────────────────────────────────────────
export type Channel = "whatsapp" | "messenger" | "instagram" | "email" | "sms";

// ── Domain models ─────────────────────────────────────────────────────────────
export type InterceptMode = "ai" | "human" | "paused";
export type ConversationStatus = "open" | "closed";
export type OrderStatus = "pending" | "confirmed" | "delivered" | "cancelled";
export type PaymentMethod = "mpesa" | "cod";
export type AgentRole = "admin" | "agent" | "readonly" | "supervisor";
export type ToastType = "success" | "error" | "warning";
export type ThemeMode = "light" | "dark";

export interface Conversation {
    id: string;
    wa_id: string;
    name: string | null;
    channel: Channel;
    intercept_mode: InterceptMode;
    status: ConversationStatus;
    last_message_preview: string;
    last_message: string;
    last_message_at: string;
    assigned_agent_id: string | null;
    assigned_agent_name?: string | null;
    unread: number;
    unread_count: number;
    contact_name: string | null;
    contact_phone: string;
}

export interface Message {
    id: string;
    direction: "inbound" | "outbound";
    sender: "user" | "ai" | "human_agent";
    text: string;
    created_at: string;
    isNote?: boolean;
}

export type MessagesMap = Record<string, Message[]>;

export interface OrderItem {
    name: string;
    qty: number;
    quantity: number;
    unit: number;
    unit_price: number;
    total: number;
    catalog_item_id?: string;
    sku?: string;
}

export interface Order {
    id: string;
    wa_id: string;
    customer_name: string;
    contact_name: string;
    contact_phone: string;
    items: OrderItem[];
    subtotal: number;
    total: number;
    status: OrderStatus;
    payment: PaymentMethod;
    currency: string;
    notes?: string;
    created_at: string;
}

export interface Agent {
    id: string;
    name: string;
    email: string;
    role: AgentRole;
    permissions?: string[];
    is_available: boolean;
    is_superuser: boolean;
    active_convs: number;
    avatar_url: string | null;
    last_seen_at: string | null;
    created_at: string;
    joined_at: string;
    department?: string;
}

export interface CatalogItem {
    id: string;
    sku: string;
    name: string;
    category: string;
    price: number;
    in_stock: boolean;
    description: string;
}

export interface ActivityEntry {
    id: number;
    user: string;
    action: string;
    target: string;
    at: string;
}

export interface RoleDefinition {
    label: string;
    color: string;
    description: string;
    permissions: string[];
}

export type RoleDefinitions = Record<AgentRole, RoleDefinition>;

export interface PermissionDef {
    key: string;
    label: string;
    group: string;
}

// ── UI / App models ──────────────────────────────────────────────────────────
export interface ToastState {
    msg: string;
    type: ToastType;
}

export interface Session {
    user: {
        email: string;
        name: string;
        role: AgentRole;
    };
}

export interface NavItem {
    id: string;
    icon: React.ReactNode;
    label: string;
    badge?: number | null;
}

export type ViewId =
    | "conversations"
    | "orders"
    | "leads"
    | "reports"
    | "agents"
    | "catalog"
    | "overview"
    | "profile"
    | "settings";

export interface SharedViewProps {
    onToast: (msg: string, type?: ToastType) => void;
    isMobile: boolean;
}