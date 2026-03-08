// ── Channel types ─────────────────────────────────────────────────────────────
export type Channel = "whatsapp" | "messenger" | "instagram" | "email" | "sms";

// ── Domain models ─────────────────────────────────────────────────────────────
export type InterceptMode = "ai" | "human" | "paused";
export type ConversationStatus = "open" | "closed";
export type OrderStatus = "pending" | "confirmed" | "delivered" | "cancelled";
export type PaymentMethod = "mpesa" | "cod";
export type AgentRole = "admin" | "agent" | "readonly" | "supervisor";
export type ToastType = "success" | "error";
export type ThemeMode = "light" | "dark";

export interface Conversation {
    id: string;
    wa_id: string;
    name: string;
    channel: Channel;
    intercept_mode: InterceptMode;
    status: ConversationStatus;
    last_message_preview: string;
    last_message_at: string;
    assigned_agent_id: string | null;
    unread: number;
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
    total: number;
}

export interface Order {
    id: string;
    wa_id: string;
    customer_name: string;
    items: OrderItem[];
    subtotal: number;
    status: OrderStatus;
    payment: PaymentMethod;
    created_at: string;
}

export interface Agent {
    id: string;
    name: string;
    email: string;
    role: AgentRole;
    permissions: string[];
    is_available: boolean;
    active_convs: number;
    last_seen_at: string | null;
    joined_at: string;
    department: string;
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
    | "agents"
    | "catalog"
    | "overview"
    | "profile"
    | "settings";

export interface SharedViewProps {
    onToast: (msg: string, type?: ToastType) => void;
    isMobile: boolean;
}