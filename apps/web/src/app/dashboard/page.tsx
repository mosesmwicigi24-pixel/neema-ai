"use client";
import React, { useState, useCallback, useEffect, useRef } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";

import { useIsMobile } from "@/hooks/useIsMobile";
import { usePolling } from "@/hooks/useApi";

import {
    conversationsApi,
    agentsApi,
    catalogApi,
    ordersApi,
    profileApi,
    mapConversation,
    mapAgent,
    mapCatalogItem,
    mapOrder,
} from "@/lib/api";

import { Toast } from "@/components/ui/Toast";
import { Sidebar } from "@/components/ui/Sidebar";
import { MobileHeader, MobileBottomNav } from "@/components/ui/MobileNav";
import { SessionExpiredModal } from "@/components/ui/SessionExpiredModal";
import { pushNotification } from "@/components/ui/Notifications";

import { ConversationsView } from "@/components/views/ConversationsView";
import { OrdersView } from "@/components/views/OrdersView";
import { AgentsView } from "@/components/views/AgentsView";
import { CatalogView } from "@/components/views/CatalogView";
import { OverviewView } from "@/components/views/OverviewView";
import { LeadsView } from "@/components/views/LeadsView";
import { ReportsView } from "@/components/views/ReportsView";
import { ProfileView } from "@/components/views/ProfileView";
import { SettingsView } from "@/components/views/SettingsView";

import { getAgentPermissions, PERMS } from "@/lib/permissions";

// ── Notification hook ─────────────────────────────────────────────────────────
import {
    useAgentNotifications,
    type AgentNotification,
} from "@/lib/websocket";

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

function LoadingScreen() {
    return (
        <div className="flex h-screen items-center justify-center" style={{ backgroundColor: "#f7f8f5" }}>
            <div className="text-center">
                <div
                    className="w-8 h-8 border-2 border-t-transparent rounded-full animate-spin mx-auto mb-3"
                    style={{ borderColor: "#589b31", borderTopColor: "transparent" }}
                />
                <p className="text-sm" style={{ color: "#8a9e80", fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                    Loading Neema…
                </p>
            </div>
        </div>
    );
}

export default function NeemaDashboard(): React.ReactElement {
    const { data: nextAuthSession, status: authStatus, update: updateSession } = useSession();
    const router = useRouter();

    const [theme, setTheme] = useState<ThemeMode>("light");
    const [view, setView] = useState<ViewId>("conversations");
    const [messages, setMessages] = useState<MessagesMap>({});
    const [toast, setToast] = useState<ToastState | null>(null);
    // ── Sidebar collapsed by default — icon-rail mode ─────────────────────────
    const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(true);
    const [sessionExpired, setSessionExpired] = useState(false);
    const [localConversations, setLocalConversations] = useState<Conversation[]>([]);
    const isMobile = useIsMobile();

    // ── Notification state ────────────────────────────────────────────────────
    const [notifications, setNotifications] = useState<AgentNotification[]>([]);
    const [unreadCount, setUnreadCount] = useState(0);

    // ── Logged-in agent profile (name + email from /api/admin/me) ─────────────
    const [agentProfile, setAgentProfile] = useState<{ name: string; email: string } | null>(null);

    // Ref guard — prevents parallel 401s from re-triggering the modal
    const sessionExpiredRef = useRef(false);
    // Snapshot of the expired token so the modal can detect when a genuinely new one arrives
    const expiredTokenRef = useRef<string | undefined>(undefined);

    // Update page title
    useEffect(() => {
        const labels: Record<string, string> = {
            conversations: "Inbox", orders: "Orders", leads: "Leads",
            overview: "Analytics", catalog: "Catalog", agents: "Team",
            profile: "Profile", settings: "Settings", reports: "Reports",
        };
        document.title = `${labels[view] ?? view} | Neema`;
    }, [view]);

    // ── Redirect if unauthenticated ───────────────────────────────────────────
    useEffect(() => {
        if (authStatus === "unauthenticated") router.push("/login");
    }, [authStatus, router]);

    // ── Theme ─────────────────────────────────────────────────────────────────
    useEffect(() => {
        const root = document.documentElement;
        if (theme === "dark") root.classList.add("dark");
        else root.classList.remove("dark");
    }, [theme]);

    // ── Write BOTH tokens synchronously in the render body ───────────────────
    const accessToken  = (nextAuthSession as any)?.accessToken  as string | undefined;
    const refreshToken = (nextAuthSession as any)?.refreshToken as string | undefined;
    if (typeof window !== "undefined") {
        if (accessToken)  (window as any).__neema_token         = accessToken;
        if (refreshToken) (window as any).__neema_refresh_token = refreshToken;
    }
    const hasToken = Boolean(accessToken);

    // ── Fetch the logged-in agent's name + email from /api/admin/me ──────────
    // NextAuth's login response only returns tokens + role — not name/email.
    // We call /me as soon as the token is ready to populate the sidebar/popup.
    useEffect(() => {
        if (!hasToken) return;
        let cancelled = false;
        const fetchProfile = (attempt = 1) => {
            profileApi
                .me()
                .then((data: any) => {
                    if (!cancelled) {
                        setAgentProfile({
                            name:  data.name  || "",
                            email: data.email || "",
                        });
                    }
                })
                .catch(() => {
                    // Retry up to 3 times with backoff (token may not be flushed yet)
                    if (!cancelled && attempt < 3) {
                        setTimeout(() => fetchProfile(attempt + 1), attempt * 500);
                    }
                });
        };
        fetchProfile();
        return () => { cancelled = true; };
    }, [hasToken]);

    // ── Listen for session-expired events dispatched by api.ts ───────────────
    useEffect(() => {
        const handler = () => {
            if (!sessionExpiredRef.current) {
                sessionExpiredRef.current = true;
                expiredTokenRef.current = typeof window !== "undefined"
                    ? (window as any).__neema_token
                    : undefined;
                setSessionExpired(true);
            }
        };
        window.addEventListener("neema:session-expired", handler);
        return () => window.removeEventListener("neema:session-expired", handler);
    }, []);

    // ── Detect NextAuth-level refresh failures ────────────────────────────────
    useEffect(() => {
        const err = (nextAuthSession as any)?.error;
        if (err === "RefreshTokenExpired" || err === "RefreshTokenMissing") {
            if (!sessionExpiredRef.current) {
                sessionExpiredRef.current = true;
                expiredTokenRef.current = accessToken;
                setSessionExpired(true);
            }
        }
    }, [nextAuthSession, accessToken]);

    // ── Live data polling — gated on hasToken ─────────────────────────────────
    const { data: rawConversations, refetch: refetchConversations } =
        usePolling(
            () => hasToken ? conversationsApi.list() : Promise.resolve(null),
            8000,
            [hasToken],
        );

    const { data: rawAgents, refetch: refetchAgents } = usePolling(
        () => (hasToken ? agentsApi.list() : Promise.resolve(null)),
        15000,
        [hasToken],
    );

    const { data: rawCatalog, refetch: refetchCatalog } = usePolling(
        () => (hasToken ? catalogApi.list() : Promise.resolve(null)),
        30000,
        [hasToken],
    );

    const { data: rawOrders, refetch: refetchOrders } = usePolling(
        () => (hasToken ? ordersApi.list() : Promise.resolve(null)),
        10000,
        [hasToken],
    );

    // ── Map API data to UI types ──────────────────────────────────────────────
    const mappedConversations: Conversation[] = (rawConversations ?? []).map(mapConversation);
    const agents: Agent[]        = (rawAgents ?? []).map(mapAgent);
    const catalog: CatalogItem[] = (rawCatalog ?? []).map(mapCatalogItem);
    const orders: Order[]        = (rawOrders ?? []).map(mapOrder);

    // Sync local conversations whenever polling brings fresh data
    useEffect(() => {
        if (mappedConversations.length > 0) {
            setLocalConversations(mappedConversations);
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [rawConversations]);

    const conversations = localConversations.length > 0
        ? localConversations
        : mappedConversations;

    // ── Setters ───────────────────────────────────────────────────────────────
    const setConversations = useCallback(
        (updater: React.SetStateAction<Conversation[]>) => {
            setLocalConversations((prev) =>
                typeof updater === "function" ? updater(prev) : updater,
            );
            setTimeout(refetchConversations, 2000);
        },
        [refetchConversations],
    );

    const setAgents = useCallback(
        (_updater: React.SetStateAction<Agent[]>) => {
            setTimeout(refetchAgents, 1000);
        },
        [refetchAgents],
    );
    const setCatalog = useCallback(
        (_updater: React.SetStateAction<CatalogItem[]>) => {
            setTimeout(refetchCatalog, 1000);
        },
        [refetchCatalog],
    );
    const setOrders = useCallback(
        (_updater: React.SetStateAction<Order[]>) => {
            setTimeout(refetchOrders, 1000);
        },
        [refetchOrders],
    );

    // ── Toast ─────────────────────────────────────────────────────────────────
    const showToast = useCallback(
        (msg: string, type: ToastType = "success"): void => {
            setToast({ msg, type });
            setTimeout(() => setToast(null), 3500);
        },
        [],
    );

    // ── Agent notifications via WebSocket ─────────────────────────────────────
    useAgentNotifications(
        useCallback(
            (n: AgentNotification) => {
                // Keep the last 50 notifications, newest first
                setNotifications((prev) => [n, ...prev].slice(0, 50));
                setUnreadCount((c) => c + 1);

                // Push into the Notifications bell via the custom event bus
                pushNotification({
                    type: (n.type as any) ?? "system",
                    title: n.title,
                    body: n.body,
                    convId: (n as any).convId,
                });

                // Show an in-app toast as well
                showToast(`${n.title}: ${n.body}`, "info");

                // Browser push notification (only if permission already granted)
                if (
                    typeof Notification !== "undefined" &&
                    Notification.permission === "granted"
                ) {
                    new Notification(n.title, {
                        body: n.body,
                        icon: "/favicon.ico",
                    });
                }
            },
            [showToast],
        ),
    );

    // ── Re-auth success ───────────────────────────────────────────────────────
    const handleReauthSuccess = useCallback(async (freshToken: string) => {
        if (typeof window !== "undefined") {
            (window as any).__neema_token = freshToken;
        }
        await updateSession();
        expiredTokenRef.current = undefined;
        sessionExpiredRef.current = false;
        setSessionExpired(false);
        refetchConversations();
        refetchAgents();
        refetchOrders();
        refetchCatalog();
    }, [updateSession, refetchConversations, refetchAgents, refetchOrders, refetchCatalog]);

    // ── Session ───────────────────────────────────────────────────────────────
    // Prefer agentProfile (fetched from /me) over NextAuth session fields,
    // since the login response doesn't include name/email in the JWT.
    const session: Session = {
        user: {
            email: agentProfile?.email || (nextAuthSession?.user?.email as string) || "",
            name:  agentProfile?.name  || (nextAuthSession?.user?.name  as string) || "",
            role:  ((nextAuthSession as any)?.role ?? "agent") as "admin" | "agent",
        },
    };

    const currentAgent = agents.find((a) => a.email === session.user.email);

    const can = (perm: string): boolean =>
        currentAgent ? getAgentPermissions(currentAgent as any).includes(perm) : false;

    const isAdmin =
        session.user.role === "admin" ||
        currentAgent?.role === "admin" ||
        (currentAgent as any)?.is_superuser === true ||
        can(PERMS.MANAGE_AGENTS);

    // ── Badges ────────────────────────────────────────────────────────────────
    const humanConvs    = conversations.filter((c) => c.intercept_mode === "human").length;
    const pendingOrders = orders.filter((o) => o.status === "pending").length;

    if (authStatus === "loading") return <LoadingScreen />;

    // ── Nav ───────────────────────────────────────────────────────────────────
    const baseNavItems: NavItem[] = [
        {
            id: "conversations",
            icon: <Icon d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />,
            label: "Inbox",
            badge: humanConvs || null,
        },
        {
            id: "orders",
            icon: <Icon d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />,
            label: "Orders",
            badge: pendingOrders || null,
        },
        ...(can(PERMS.VIEW_REPORTS)
            ? [{
                id: "reports" as ViewId,
                icon: <Icon d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />,
                label: "Reports",
                badge: null,
            }] : []),
        ...(can(PERMS.VIEW_LEADS)
            ? [{
                id: "leads" as ViewId,
                icon: <Icon d="M3 21v-4m0 0V5a2 2 0 012-2h6.5l1 1H21l-3 6 3 6h-8.5l-1-1H5a2 2 0 00-2 2zm9-13.5V9" />,
                label: "Leads",
                badge: null,
            }] : []),
        ...(can(PERMS.VIEW_ANALYTICS)
            ? [{
                id: "overview" as ViewId,
                icon: <Icon d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />,
                label: "Analytics",
            }] : []),
        ...(can(PERMS.VIEW_CATALOG)
            ? [{
                id: "catalog" as ViewId,
                icon: <Icon d="M4 6h16M4 10h16M4 14h16M4 18h16" />,
                label: "Catalog",
            }] : []),
        ...(can(PERMS.MANAGE_AGENTS)
            ? [{
                id: "agents" as ViewId,
                icon: <Icon d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />,
                label: "Team",
            }] : []),
        {
            id: "profile",
            icon: <Icon d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />,
            label: "Profile",
        },
    ];

    const desktopNavItems: NavItem[] = [
        ...baseNavItems.slice(0, -1),
        ...(can(PERMS.MANAGE_SETTINGS)
            ? [{
                id: "settings" as ViewId,
                icon: <Icon d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" />,
                label: "Settings",
            }] : []),
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
                orders={orders}
                refetchConversations={refetchConversations}
                {...viewProps}
            />
        ),
        orders: (
            <OrdersView
                orders={orders}
                setOrders={setOrders}
                refetchOrders={refetchOrders}
                {...viewProps}
            />
        ),
        leads: <LeadsView {...viewProps} />,
        reports: (
            <ReportsView
                conversations={conversations}
                agents={agents}
                orders={orders}
                {...viewProps}
            />
        ),
        agents: (
            <AgentsView
                agents={agents}
                setAgents={setAgents}
                refetchAgents={refetchAgents}
                {...viewProps}
            />
        ),
        catalog: (
            <CatalogView
                catalog={catalog}
                setCatalog={setCatalog}
                refetchCatalog={refetchCatalog}
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
                refetchAgents={refetchAgents}
                {...viewProps}
            />
        ),
        settings: <SettingsView {...viewProps} />,
    };

    return (
        <div
            className="flex h-dvh overflow-hidden text-stone-900"
            style={{ backgroundColor: "#f7f8f5", fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif" }}
        >
            <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&family=JetBrains+Mono:wght@400;500&display=swap');
        * { font-family: 'Plus Jakarta Sans', system-ui, sans-serif; }
        :root {
            --accent: #589b31;
            --accent-hover: #427425;
            --surface: #ffffff;
            --border: #e8ebe3;
            --text: #1c2917;
            --text-muted: #8a9e80;
        }
        .scrollbar-none::-webkit-scrollbar { display: none; }
        .scrollbar-none { scrollbar-width: none; }
        .h-dvh { height: 100dvh; }
        .pb-safe { padding-bottom: env(safe-area-inset-bottom, 0px); }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        .animate-in { animation: fadeIn 0.18s ease; }
        *:focus-visible { outline: 2px solid #589b31; outline-offset: 2px; border-radius: 6px; }
        input, textarea, select { font-family: inherit; }
        button { transition: background-color 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease; }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #dde4d6; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #c5d0bc; }
      `}</style>

            <Toast toast={toast} isMobile={isMobile} />

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
                    notificationCount={unreadCount}
                    notifications={notifications}
                    onClearNotifications={() => setUnreadCount(0)}
                />
            )}

            <div className="flex flex-col flex-1 overflow-hidden">
                {isMobile && (
                    <MobileHeader
                        navItems={baseNavItems}
                        view={view}
                        theme={theme}
                        setTheme={setTheme}
                        notificationCount={unreadCount}
                        onClearNotifications={() => setUnreadCount(0)}
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

            {/* Session-expired modal — overlay on live dashboard, no redirect */}
            {sessionExpired && (
                <SessionExpiredModal
                    email={(nextAuthSession?.user?.email as string) ?? ""}
                    onSuccess={handleReauthSuccess}
                    expiredToken={expiredTokenRef.current}
                />
            )}
        </div>
    );
}