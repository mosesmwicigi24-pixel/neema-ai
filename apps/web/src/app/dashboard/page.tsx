"use client";
import React, { useState, useCallback, useEffect } from "react";

import {
    MOCK_CONVERSATIONS,
    MOCK_MESSAGES,
    MOCK_AGENTS,
    MOCK_ORDERS,
    MOCK_CATALOG,
} from "@/lib/mockData";
import { useIsMobile } from "@/hooks/useIsMobile";

import { Toast } from "@/components/ui/Toast";
import { Sidebar } from "@/components/ui/Sidebar";
import { MobileHeader, MobileBottomNav } from "@/components/ui/MobileNav";

import { ConversationsView } from "@/components/views/ConversationsView";
import { OrdersView } from "@/components/views/OrdersView";
import { AgentsView } from "@/components/views/AgentsView";
import { CatalogView } from "@/components/views/CatalogView";
import { OverviewView } from "@/components/views/OverviewView";
import { ProfileView } from "@/components/views/ProfileView";
import { SettingsView } from "@/components/views/SettingsView";

import type {
    Conversation,
    MessagesMap,
    Agent,
    Order,
    CatalogItem,
    ToastState,
    Session,
    NavItem,
    ViewId,
    ThemeMode,
    ToastType,
} from "@/types";

// ── Nav icons ─────────────────────────────────────────────────────────────────
const Icon = ({ d }: { d: string }) => (
    <svg
        className="w-5 h-5"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
    >
        <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.8}
            d={d}
        />
    </svg>
);

export default function NeemaDashboard(): React.ReactElement {
    const [theme, setTheme] = useState<ThemeMode>("light");
    const [view, setView] = useState<ViewId>("conversations");
    const [conversations, setConversations] =
        useState<Conversation[]>(MOCK_CONVERSATIONS);
    const [messages, setMessages] = useState<MessagesMap>(MOCK_MESSAGES);
    const [agents, setAgents] = useState<Agent[]>(MOCK_AGENTS);
    const [orders, setOrders] = useState<Order[]>(MOCK_ORDERS);
    const [catalog, setCatalog] = useState<CatalogItem[]>(MOCK_CATALOG);
    const [toast, setToast] = useState<ToastState | null>(null);
    const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(false);
    const isMobile = useIsMobile();

    // Apply dark mode class to html element
    useEffect(() => {
        const root = document.documentElement;
        if (theme === "dark") root.classList.add("dark");
        else root.classList.remove("dark");
    }, [theme]);

    const session: Session = {
        user: { email: "priya@neema.co", name: "Priya Sharma", role: "admin" },
    };
    const isAdmin = session.user.role === "admin";

    const showToast = useCallback(
        (msg: string, type: ToastType = "success"): void => {
            setToast({ msg, type });
            setTimeout(() => setToast(null), 3500);
        },
        [],
    );

    const humanConvs = conversations.filter(
        (c) => c.intercept_mode === "human",
    ).length;
    const pendingOrders = orders.filter((o) => o.status === "pending").length;

    const baseNavItems: NavItem[] = [
        {
            id: "conversations",
            icon: (
                <Icon d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            ),
            label: "Inbox",
            badge: humanConvs || null,
        },
        {
            id: "orders",
            icon: (
                <Icon d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
            ),
            label: "Orders",
            badge: pendingOrders || null,
        },
        ...(isAdmin
            ? [
                  {
                      id: "overview" as ViewId,
                      icon: (
                          <Icon d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                      ),
                      label: "Analytics",
                  },
                  {
                      id: "catalog" as ViewId,
                      icon: <Icon d="M4 6h16M4 10h16M4 14h16M4 18h16" />,
                      label: "Catalog",
                  },
                  {
                      id: "agents" as ViewId,
                      icon: (
                          <Icon d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
                      ),
                      label: "Team",
                  },
              ]
            : []),
        {
            id: "profile",
            icon: (
                <Icon d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            ),
            label: "Profile",
        },
    ];

    const desktopNavItems: NavItem[] = [
        ...baseNavItems.slice(0, -1),
        ...(isAdmin
            ? [
                  {
                      id: "settings" as ViewId,
                      icon: (
                          <Icon d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      ),
                      label: "Settings",
                  },
              ]
            : []),
        baseNavItems[baseNavItems.length - 1],
    ];

    const viewProps = { onToast: showToast, isMobile };

    const viewComponents: Record<ViewId, React.ReactElement> = {
        conversations: (
            <ConversationsView
                conversations={conversations}
                setConversations={setConversations}
                messages={messages}
                setMessages={setMessages}
                agents={agents}
                {...viewProps}
            />
        ),
        orders: (
            <OrdersView orders={orders} setOrders={setOrders} {...viewProps} />
        ),
        agents: (
            <AgentsView agents={agents} setAgents={setAgents} {...viewProps} />
        ),
        catalog: (
            <CatalogView
                catalog={catalog}
                setCatalog={setCatalog}
                {...viewProps}
            />
        ),
        overview: (
            <OverviewView
                conversations={conversations}
                agents={agents}
                orders={orders}
                catalog={catalog}
                {...viewProps}
            />
        ),
        profile: (
            <ProfileView
                session={session}
                agents={agents}
                setAgents={setAgents}
                theme={theme}
                setTheme={setTheme}
                {...viewProps}
            />
        ),
        settings: <SettingsView {...viewProps} />,
    };

    return (
        <div className="flex h-dvh overflow-hidden bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-white">
            {/* Global styles */}
            <style>{`
        @keyframes slideInDown { from { opacity:0; transform:translateY(-8px); } to { opacity:1; transform:translateY(0); } }
        .scrollbar-none::-webkit-scrollbar { display: none; }
        .scrollbar-none { scrollbar-width: none; }
        .h-dvh { height: 100dvh; }
        .pb-safe { padding-bottom: env(safe-area-inset-bottom, 0px); }
        @keyframes fadeIn { from { opacity:0; } to { opacity:1; } }
        .animate-in { animation: fadeIn 0.2s ease; }
      `}</style>
            <link
                href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
                rel="stylesheet"
            />

            <Toast toast={toast} isMobile={isMobile} />

            {/* Desktop sidebar */}
            {!isMobile && (
                <Sidebar
                    navItems={desktopNavItems}
                    view={view}
                    setView={setView}
                    collapsed={sidebarCollapsed}
                    setCollapsed={setSidebarCollapsed}
                    session={session}
                    theme={theme}
                    setTheme={setTheme}
                />
            )}

            {/* Main area */}
            <div className="flex flex-col flex-1 overflow-hidden">
                {isMobile && (
                    <MobileHeader
                        navItems={baseNavItems}
                        view={view}
                        theme={theme}
                        setTheme={setTheme}
                    />
                )}

                <main
                    className="flex flex-1 overflow-hidden"
                    style={{ marginTop: isMobile ? 56 : 0 }}
                >
                    {viewComponents[view]}
                </main>

                {isMobile && (
                    <MobileBottomNav
                        navItems={baseNavItems}
                        view={view}
                        setView={setView}
                    />
                )}
            </div>
        </div>
    );
}