import type React from "react";

export type ThemeMode = "light" | "dark";
export type ToastType = "success" | "error" | "warning" | "info";
export type InterceptMode = "ai" | "human" | "paused";
export type OrderStatus = "pending" | "confirmed" | "delivered" | "cancelled";
export type AgentRole = "admin" | "agent";
export type Channel = "whatsapp" | "sms" | "email";
export type ViewId =
    | "conversations"
    | "orders"
    | "agents"
    | "catalog"
    | "overview"
    | "profile"
    | "settings";

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
    id: ViewId;
    icon: React.ReactElement;
    label: string;
    badge?: number | null;
}

export interface Conversation {
    id: string;
    contact_name: string;
    contact_phone: string;
    last_message: string;
    last_message_at: string;
    intercept_mode: InterceptMode;
    status: "open" | "closed" | "pending";
    unread_count?: number;
    assigned_agent_id?: string | null;
    channel?: Channel;
}

export type MessagesMap = Record<string, Message[]>;

export interface Message {
    id: string;
    conversation_id: string;
    body: string;
    direction: "inbound" | "outbound";
    sender: "ai" | "human" | "customer";
    created_at: string;
}

export interface Agent {
    id: string;
    name: string;
    email: string;
    role: AgentRole;
    is_available: boolean;
    active_convs: number;
    avatar_url?: string | null;
    created_at: string;
    last_seen_at?: string | null;
}

export interface Order {
    id: string;
    contact_name: string;
    contact_phone: string;
    items: OrderItem[];
    total: number;
    status: OrderStatus;
    created_at: string;
    notes?: string;
}

export interface OrderItem {
    catalog_item_id: string;
    name: string;
    quantity: number;
    unit_price: number;
}

export interface CatalogItem {
    id: string;
    sku: string;
    name: string;
    aliases: string[];
    price: number;
    unit: string;
    category: string;
    description?: string;
    in_stock: boolean;
}