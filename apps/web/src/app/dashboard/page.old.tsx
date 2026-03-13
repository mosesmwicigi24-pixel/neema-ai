"use client";
import { useState, useEffect, useRef, useCallback } from "react";

// ── MOCK DATA ──────────────────────────────────────────────────────────────────
const MOCK_CONVERSATIONS = [
    {
        id: "c1",
        wa_id: "254712001001",
        name: "Amara Osei",
        intercept_mode: "human",
        status: "open",
        last_message_preview: "I want to add plantain to my order",
        last_message_at: new Date(Date.now() - 2 * 60000).toISOString(),
        assigned_agent_id: "a1",
        unread: 3,
    },
    {
        id: "c2",
        wa_id: "254712002002",
        name: "Kofi Mensah",
        intercept_mode: "ai",
        status: "open",
        last_message_preview: "What's the delivery time?",
        last_message_at: new Date(Date.now() - 8 * 60000).toISOString(),
        assigned_agent_id: null,
        unread: 0,
    },
    {
        id: "c3",
        wa_id: "254712003003",
        name: "Zara Diallo",
        intercept_mode: "human",
        status: "open",
        last_message_preview: "Can I pay cash on delivery?",
        last_message_at: new Date(Date.now() - 15 * 60000).toISOString(),
        assigned_agent_id: "a2",
        unread: 1,
    },
    {
        id: "c4",
        wa_id: "254712004004",
        name: "Nana Acheampong",
        intercept_mode: "paused",
        status: "open",
        last_message_preview: "I didn't receive my order",
        last_message_at: new Date(Date.now() - 45 * 60000).toISOString(),
        assigned_agent_id: null,
        unread: 0,
    },
    {
        id: "c5",
        wa_id: "254712005005",
        name: "Esi Boateng",
        intercept_mode: "ai",
        status: "open",
        last_message_preview: "Hi, I'd like to order jollof rice",
        last_message_at: new Date(Date.now() - 90 * 60000).toISOString(),
        assigned_agent_id: null,
        unread: 0,
    },
    {
        id: "c6",
        wa_id: "254712006006",
        name: "Kweku Asante",
        intercept_mode: "human",
        status: "closed",
        last_message_preview: "Thanks, order confirmed!",
        last_message_at: new Date(Date.now() - 3 * 3600000).toISOString(),
        assigned_agent_id: "a1",
        unread: 0,
    },
];

const MOCK_MESSAGES = {
    c1: [
        {
            id: "m1",
            direction: "inbound",
            sender: "user",
            text: "Hello, I want to order some food",
            created_at: new Date(Date.now() - 20 * 60000).toISOString(),
        },
        {
            id: "m2",
            direction: "outbound",
            sender: "ai",
            text: "Hello Amara! 🌟 Welcome to Neema. What would you like to order today? Check out our menu below.",
            created_at: new Date(Date.now() - 19 * 60000).toISOString(),
        },
        {
            id: "m3",
            direction: "inbound",
            sender: "user",
            text: "I'll take the Jollof rice combo x2",
            created_at: new Date(Date.now() - 18 * 60000).toISOString(),
        },
        {
            id: "m4",
            direction: "outbound",
            sender: "ai",
            text: "Great choice! 2x Jollof Rice Combo added. Subtotal: KES 800. What's your delivery address?",
            created_at: new Date(Date.now() - 17 * 60000).toISOString(),
        },
        {
            id: "m5",
            direction: "inbound",
            sender: "user",
            text: "Westlands, near the Shell station",
            created_at: new Date(Date.now() - 10 * 60000).toISOString(),
        },
        {
            id: "m6",
            direction: "outbound",
            sender: "human_agent",
            text: "Hi Amara, I'm Sarah your agent. I've noted your address. Can you be more specific? Which road?",
            created_at: new Date(Date.now() - 8 * 60000).toISOString(),
        },
        {
            id: "m7",
            direction: "inbound",
            sender: "user",
            text: "I want to add plantain to my order",
            created_at: new Date(Date.now() - 2 * 60000).toISOString(),
        },
    ],
    c2: [
        {
            id: "m1",
            direction: "inbound",
            sender: "user",
            text: "What's the delivery time?",
            created_at: new Date(Date.now() - 8 * 60000).toISOString(),
        },
        {
            id: "m2",
            direction: "outbound",
            sender: "ai",
            text: "Delivery usually takes 30–45 minutes depending on your location. Would you like to place an order?",
            created_at: new Date(Date.now() - 7 * 60000).toISOString(),
        },
    ],
};

const AI_DRAFT =
    "I'd be happy to add fried plantain to your order! That will be an additional KES 150. Your updated total is KES 950. Shall I confirm?";

const MOCK_AGENTS = [
    {
        id: "a1",
        name: "Sarah Kamau",
        email: "sarah@neema.co",
        role: "agent",
        is_available: true,
        active_convs: 3,
        last_seen_at: new Date(Date.now() - 5 * 60000).toISOString(),
    },
    {
        id: "a2",
        name: "James Otieno",
        email: "james@neema.co",
        role: "agent",
        is_available: true,
        active_convs: 1,
        last_seen_at: new Date(Date.now() - 2 * 60000).toISOString(),
    },
    {
        id: "a3",
        name: "Moses Mwicigi",
        email: "mwicigi@bethanyhouse.co.ke",
        role: "admin",
        is_available: false,
        active_convs: 0,
        last_seen_at: new Date(Date.now() - 2 * 3600000).toISOString(),
    },
    {
        id: "a4",
        name: "David Mwangi",
        email: "david@neema.co",
        role: "readonly",
        is_available: true,
        active_convs: 0,
        last_seen_at: new Date(Date.now() - 30 * 60000).toISOString(),
    },
];

const MOCK_ORDERS = [
    {
        id: "o1",
        wa_id: "254712001001",
        customer_name: "Amara Osei",
        items: [{ name: "Jollof Rice Combo", qty: 2, total: 800 }],
        subtotal: 800,
        status: "pending",
        payment: "mpesa",
        created_at: new Date(Date.now() - 18 * 60000).toISOString(),
    },
    {
        id: "o2",
        wa_id: "254712003003",
        customer_name: "Zara Diallo",
        items: [
            { name: "Egusi Soup", qty: 1, total: 450 },
            { name: "Puff Puff", qty: 3, total: 150 },
        ],
        subtotal: 600,
        status: "confirmed",
        payment: "cod",
        created_at: new Date(Date.now() - 35 * 60000).toISOString(),
    },
    {
        id: "o3",
        wa_id: "254712006006",
        customer_name: "Kweku Asante",
        items: [{ name: "Fufu Combo", qty: 2, total: 960 }],
        subtotal: 960,
        status: "delivered",
        payment: "mpesa",
        created_at: new Date(Date.now() - 3 * 3600000).toISOString(),
    },
    {
        id: "o4",
        wa_id: "254712007007",
        customer_name: "Akosua Frimpong",
        items: [{ name: "Waakye Special", qty: 1, total: 380 }],
        subtotal: 380,
        status: "confirmed",
        payment: "mpesa",
        created_at: new Date(Date.now() - 60 * 60000).toISOString(),
    },
];

const MOCK_CATALOG = [
    {
        id: "cat1",
        sku: "JRC-001",
        name: "Jollof Rice Combo",
        category: "Mains",
        price: 400,
        in_stock: true,
        description: "Smoky jollof rice with chicken and salad",
    },
    {
        id: "cat2",
        sku: "EGS-002",
        name: "Egusi Soup",
        category: "Mains",
        price: 450,
        in_stock: true,
        description: "Rich egusi soup with assorted fish",
    },
    {
        id: "cat3",
        sku: "FUF-003",
        name: "Fufu Combo",
        category: "Mains",
        price: 480,
        in_stock: true,
        description: "Cassava fufu with goat light soup",
    },
    {
        id: "cat4",
        sku: "WAK-004",
        name: "Waakye Special",
        category: "Mains",
        price: 380,
        in_stock: true,
        description: "Rice and beans with all toppings",
    },
    {
        id: "cat5",
        sku: "PLT-005",
        name: "Fried Plantain",
        category: "Sides",
        price: 150,
        in_stock: true,
        description: "Sweet golden fried plantain",
    },
    {
        id: "cat6",
        sku: "PUF-006",
        name: "Puff Puff",
        category: "Snacks",
        price: 50,
        in_stock: false,
        description: "Fluffy deep-fried dough balls",
    },
];

// ── UTILS ──────────────────────────────────────────────────────────────────────
function timeAgo(iso) {
    const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}
function initials(name) {
    return (
        name
            ?.split(" ")
            .map((w) => w[0])
            .join("")
            .slice(0, 2)
            .toUpperCase() || "?"
    );
}
function fmtCurrency(n) {
    return `KES ${n?.toLocaleString() ?? 0}`;
}

// ── COMPONENTS ────────────────────────────────────────────────────────────────
function Avatar({ name, size = 36, color }) {
    const colors = [
        "#c9a84c",
        "#5b9cf0",
        "#4caf7d",
        "#e05555",
        "#e8a84c",
        "#9b72d0",
    ];
    const bg = color || colors[name?.charCodeAt(0) % colors.length];
    return (
        <div
            style={{
                width: size,
                height: size,
                borderRadius: "50%",
                background: bg,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: size * 0.36,
                fontFamily: "var(--font-mono)",
                color: "#0f0e0d",
                fontWeight: 600,
                flexShrink: 0,
            }}
        >
            {initials(name)}
        </div>
    );
}

function Badge({ type }) {
    const map = {
        ai: { label: "AI", bg: "var(--blue-dim)", color: "var(--blue)" },
        human: {
            label: "HUMAN",
            bg: "var(--amber-dim)",
            color: "var(--amber)",
        },
        paused: {
            label: "PAUSED",
            bg: "rgba(140,130,121,0.12)",
            color: "var(--text-dim)",
        },
    };
    const s = map[type] || map.ai;
    return (
        <span
            style={{
                fontSize: 10,
                fontFamily: "var(--font-mono)",
                background: s.bg,
                color: s.color,
                padding: "2px 7px",
                borderRadius: 4,
                letterSpacing: "0.06em",
            }}
        >
            {s.label}
        </span>
    );
}

function StatusBadge({ status }) {
    const map = {
        pending: "#e8a84c",
        confirmed: "#5b9cf0",
        delivered: "#4caf7d",
        cancelled: "#e05555",
    };
    return (
        <span
            style={{
                fontSize: 10,
                fontFamily: "var(--font-mono)",
                color: map[status] || "var(--text-dim)",
                background: `${map[status]}18`,
                padding: "2px 7px",
                borderRadius: 4,
                letterSpacing: "0.05em",
                textTransform: "uppercase",
            }}
        >
            {status}
        </span>
    );
}

function Modal({ show, onClose, title, children }) {
    if (!show) return null;
    return (
        <div
            style={{
                position: "fixed",
                inset: 0,
                zIndex: 100,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
            }}
            onClick={onClose}
        >
            <div
                style={{
                    position: "absolute",
                    inset: 0,
                    background: "rgba(0,0,0,0.7)",
                    backdropFilter: "blur(4px)",
                }}
            />
            <div
                style={{
                    position: "relative",
                    background: "var(--bg2)",
                    border: "1px solid var(--border2)",
                    borderRadius: 12,
                    padding: 28,
                    width: 480,
                    maxWidth: "90vw",
                    maxHeight: "80vh",
                    overflowY: "auto",
                }}
                onClick={(e) => e.stopPropagation()}
            >
                <div
                    style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        marginBottom: 20,
                    }}
                >
                    <h3
                        style={{
                            fontFamily: "var(--font-serif)",
                            fontSize: 20,
                            color: "var(--gold2)",
                        }}
                    >
                        {title}
                    </h3>
                    <button
                        onClick={onClose}
                        style={{
                            background: "none",
                            border: "none",
                            color: "var(--text-dim)",
                            fontSize: 20,
                            cursor: "pointer",
                            lineHeight: 1,
                        }}
                    >
                        ×
                    </button>
                </div>
                {children}
            </div>
        </div>
    );
}

function InputField({ label, value, onChange, type = "text", placeholder }) {
    return (
        <div style={{ marginBottom: 16 }}>
            <label
                style={{
                    fontSize: 11,
                    fontFamily: "var(--font-mono)",
                    color: "var(--text-dim)",
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    display: "block",
                    marginBottom: 6,
                }}
            >
                {label}
            </label>
            <input
                type={type}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                placeholder={placeholder}
                style={{
                    width: "100%",
                    background: "var(--bg3)",
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                    padding: "10px 12px",
                    color: "var(--text)",
                    fontSize: 14,
                    fontFamily: "var(--font-body)",
                    outline: "none",
                }}
            />
        </div>
    );
}

function Btn({ onClick, children, variant = "primary", small, disabled }) {
    const styles = {
        primary: {
            background: "var(--gold)",
            color: "#0f0e0d",
            border: "none",
        },
        secondary: {
            background: "transparent",
            color: "var(--text-dim)",
            border: "1px solid var(--border)",
        },
        danger: {
            background: "var(--red-dim)",
            color: "var(--red)",
            border: "1px solid #e0555533",
        },
        success: {
            background: "var(--green-dim)",
            color: "var(--green)",
            border: "1px solid #4caf7d33",
        },
        blue: {
            background: "var(--blue-dim)",
            color: "var(--blue)",
            border: "1px solid #5b9cf033",
        },
    };
    return (
        <button
            onClick={onClick}
            disabled={disabled}
            style={{
                ...styles[variant],
                padding: small ? "6px 14px" : "9px 18px",
                borderRadius: 6,
                fontSize: small ? 12 : 13,
                fontFamily: "var(--font-mono)",
                cursor: disabled ? "not-allowed" : "pointer",
                opacity: disabled ? 0.5 : 1,
                transition: "opacity 0.15s",
                letterSpacing: "0.04em",
            }}
        >
            {children}
        </button>
    );
}

// ── MAIN DASHBOARD ────────────────────────────────────────────────────────────
export default function NeemaDashboard() {
    // Auth/session simulation
    const session = {
        user: { email: "mwicigi@bethanyhouse.co.ke", name: "Moses Mwicigi", role: "admin" },
    };

    // State
    const [view, setView] = useState("conversations");
    const [conversations, setConversations] = useState(MOCK_CONVERSATIONS);
    const [messages, setMessages] = useState(MOCK_MESSAGES);
    const [agents, setAgents] = useState(MOCK_AGENTS);
    const [orders, setOrders] = useState(MOCK_ORDERS);
    const [catalog, setCatalog] = useState(MOCK_CATALOG);
    const [activeConvId, setActiveConvId] = useState("c1");
    const [convFilter, setConvFilter] = useState("all");
    const [replyText, setReplyText] = useState("");
    const [agentModal, setAgentModal] = useState(null); // null | "create" | {agent}
    const [catalogModal, setCatalogModal] = useState(null);
    const [toast, setToast] = useState(null);
    const [draftVisible, setDraftVisible] = useState(true);
    const [orderFilter, setOrderFilter] = useState("all");
    const [newAgentForm, setNewAgentForm] = useState({
        name: "",
        email: "",
        role: "agent",
        password: "",
    });
    const [newCatalogForm, setNewCatalogForm] = useState({
        sku: "",
        name: "",
        category: "",
        price: "",
        in_stock: true,
        description: "",
    });
    const [transferModal, setTransferModal] = useState(false);
    const [noteModal, setNoteModal] = useState(false);
    const [noteText, setNoteText] = useState("");
    const messagesEndRef = useRef(null);

    const isAdmin = session.user.role === "admin";
    const activeConv = conversations.find((c) => c.id === activeConvId);
    const activeMessages = messages[activeConvId] || [];

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [activeConvId, messages]);

    const showToast = (msg, type = "success") => {
        setToast({ msg, type });
        setTimeout(() => setToast(null), 3000);
    };

    // ── Actions ──
    const intercept = (convId) => {
        setConversations((cs) =>
            cs.map((c) =>
                c.id === convId
                    ? { ...c, intercept_mode: "human", assigned_agent_id: "a1" }
                    : c,
            ),
        );
        showToast("Conversation intercepted — you now control replies");
    };

    const release = (convId) => {
        setConversations((cs) =>
            cs.map((c) =>
                c.id === convId
                    ? { ...c, intercept_mode: "ai", assigned_agent_id: null }
                    : c,
            ),
        );
        showToast("Conversation released back to AI");
    };

    const pause = (convId) => {
        setConversations((cs) =>
            cs.map((c) =>
                c.id === convId ? { ...c, intercept_mode: "paused" } : c,
            ),
        );
        showToast("AI paused — no messages will send");
    };

    const sendReply = () => {
        if (!replyText.trim()) return;
        const msg = {
            id: `m${Date.now()}`,
            direction: "outbound",
            sender: "human_agent",
            text: replyText,
            created_at: new Date().toISOString(),
        };
        setMessages((m) => ({
            ...m,
            [activeConvId]: [...(m[activeConvId] || []), msg],
        }));
        setConversations((cs) =>
            cs.map((c) =>
                c.id === activeConvId
                    ? {
                          ...c,
                          last_message_preview: replyText,
                          last_message_at: new Date().toISOString(),
                      }
                    : c,
            ),
        );
        setReplyText("");
        showToast("Message sent via WhatsApp");
    };

    const approveDraft = () => {
        const msg = {
            id: `m${Date.now()}`,
            direction: "outbound",
            sender: "ai",
            text: AI_DRAFT,
            created_at: new Date().toISOString(),
        };
        setMessages((m) => ({
            ...m,
            [activeConvId]: [...(m[activeConvId] || []), msg],
        }));
        setDraftVisible(false);
        showToast("AI draft approved & sent");
    };

    const transferConv = (agentId) => {
        const agent = agents.find((a) => a.id === agentId);
        setConversations((cs) =>
            cs.map((c) =>
                c.id === activeConvId
                    ? {
                          ...c,
                          assigned_agent_id: agentId,
                          intercept_mode: "human",
                      }
                    : c,
            ),
        );
        setTransferModal(false);
        showToast(`Transferred to ${agent?.name}`);
    };

    const closeConv = (convId) => {
        setConversations((cs) =>
            cs.map((c) => (c.id === convId ? { ...c, status: "closed" } : c)),
        );
        showToast("Conversation closed");
    };

    const createAgent = () => {
        const ag = {
            id: `a${Date.now()}`,
            ...newAgentForm,
            is_available: true,
            active_convs: 0,
            last_seen_at: null,
        };
        setAgents((as) => [...as, ag]);
        setAgentModal(null);
        setNewAgentForm({ name: "", email: "", role: "agent", password: "" });
        showToast("Agent created successfully");
    };

    const toggleAgentAvailable = (id) => {
        setAgents((as) =>
            as.map((a) =>
                a.id === id ? { ...a, is_available: !a.is_available } : a,
            ),
        );
    };

    const deleteAgent = (id) => {
        setAgents((as) => as.filter((a) => a.id !== id));
        showToast("Agent removed", "error");
    };

    const createCatalogItem = () => {
        const item = {
            id: `cat${Date.now()}`,
            ...newCatalogForm,
            price: parseInt(newCatalogForm.price) || 0,
        };
        setCatalog((cs) => [...cs, item]);
        setCatalogModal(null);
        setNewCatalogForm({
            sku: "",
            name: "",
            category: "",
            price: "",
            in_stock: true,
            description: "",
        });
        showToast("Catalog item added");
    };

    const toggleStock = (id) => {
        setCatalog((cs) =>
            cs.map((c) => (c.id === id ? { ...c, in_stock: !c.in_stock } : c)),
        );
    };

    const updateOrderStatus = (id, status) => {
        setOrders((os) => os.map((o) => (o.id === id ? { ...o, status } : o)));
        showToast(`Order marked as ${status}`);
    };

    const addNote = () => {
        const msg = {
            id: `m${Date.now()}`,
            direction: "outbound",
            sender: "human_agent",
            text: `📝 Internal note: ${noteText}`,
            created_at: new Date().toISOString(),
            isNote: true,
        };
        setMessages((m) => ({
            ...m,
            [activeConvId]: [...(m[activeConvId] || []), msg],
        }));
        setNoteModal(false);
        setNoteText("");
        showToast("Note saved");
    };

    // ── Filtered views ──
    const filteredConvs = conversations.filter((c) => {
        if (convFilter === "human") return c.intercept_mode === "human";
        if (convFilter === "ai") return c.intercept_mode === "ai";
        if (convFilter === "paused") return c.intercept_mode === "paused";
        if (convFilter === "open") return c.status === "open";
        return true;
    });

    const filteredOrders =
        orderFilter === "all"
            ? orders
            : orders.filter((o) => o.status === orderFilter);

    // Stats
    const stats = {
        openConvs: conversations.filter((c) => c.status === "open").length,
        humanConvs: conversations.filter((c) => c.intercept_mode === "human")
            .length,
        activeAgents: agents.filter((a) => a.is_available).length,
        totalOrders: orders.length,
        revenue: orders
            .filter((o) => o.status !== "cancelled")
            .reduce((s, o) => s + o.subtotal, 0),
        pendingOrders: orders.filter((o) => o.status === "pending").length,
    };

    // ── VIEWS ──────────────────────────────────────────────────────────────────
    const navItems = [
        {
            id: "conversations",
            icon: "💬",
            label: "Conversations",
            badge: stats.humanConvs,
        },
        {
            id: "orders",
            icon: "📦",
            label: "Orders",
            badge: stats.pendingOrders,
        },
        ...(isAdmin
            ? [
                  { id: "agents", icon: "👥", label: "Agents" },
                  { id: "catalog", icon: "🍽", label: "Catalog" },
                  { id: "overview", icon: "📊", label: "Overview" },
              ]
            : []),
    ];

    return (
        <div
            style={{
                display: "flex",
                height: "100vh",
                background: "var(--bg)",
                color: "var(--text)",
                fontFamily: "var(--font-body)",
                overflow: "hidden",
            }}
        >
            <style>{`
        :root {
          --bg: #0f0e0d; --bg2: #181614; --bg3: #201e1b; --bg4: #161412;
          --border: #2d2a26; --border2: #3a3530;
          --gold: #c9a84c; --gold2: #e8c96a; --gold-dim: rgba(201,168,76,0.12); --gold-glow: rgba(201,168,76,0.06);
          --text: #f0ece4; --text-dim: #8c8279; --text-mid: #b8b0a4;
          --green: #4caf7d; --green-dim: rgba(76,175,125,0.12);
          --red: #e05555; --red-dim: rgba(224,85,85,0.12);
          --blue: #5b9cf0; --blue-dim: rgba(91,156,240,0.12);
          --amber: #e8a84c; --amber-dim: rgba(232,168,76,0.12);
          --font-body: 'DM Sans', sans-serif; --font-mono: 'DM Mono', monospace; --font-serif: 'DM Serif Display', serif;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 5px; } ::-webkit-scrollbar-track { background: transparent; } ::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 3px; }
        input:focus, textarea:focus { border-color: var(--gold) !important; outline: none; }
        button { transition: opacity 0.15s; }
        button:hover:not(:disabled) { opacity: 0.85; }
        select { background: var(--bg3); border: 1px solid var(--border); border-radius: 6px; color: var(--text); padding: 8px 12px; font-size: 13px; font-family: var(--font-body); outline: none; cursor: pointer; }
      `}</style>
            <link
                href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@300;400;500&family=DM+Sans:wght@300;400;500;600&display=swap"
                rel="stylesheet"
            />

            {/* Toast */}
            {toast && (
                <div
                    style={{
                        position: "fixed",
                        top: 20,
                        right: 20,
                        zIndex: 999,
                        background:
                            toast.type === "error"
                                ? "var(--red-dim)"
                                : "var(--green-dim)",
                        border: `1px solid ${toast.type === "error" ? "#e0555533" : "#4caf7d33"}`,
                        color:
                            toast.type === "error"
                                ? "var(--red)"
                                : "var(--green)",
                        borderRadius: 8,
                        padding: "12px 20px",
                        fontSize: 13,
                        fontFamily: "var(--font-mono)",
                        animation: "fadeIn 0.2s ease",
                    }}
                >
                    {toast.msg}
                </div>
            )}

            {/* Sidebar */}
            <div
                style={{
                    width: 220,
                    background: "var(--bg2)",
                    borderRight: "1px solid var(--border)",
                    display: "flex",
                    flexDirection: "column",
                    flexShrink: 0,
                }}
            >
                <div
                    style={{
                        padding: "20px 18px 16px",
                        borderBottom: "1px solid var(--border)",
                    }}
                >
                    <div
                        style={{
                            fontFamily: "var(--font-serif)",
                            fontSize: 22,
                            color: "var(--gold2)",
                            lineHeight: 1,
                        }}
                    >
                        Neema
                    </div>
                    <div
                        style={{
                            fontSize: 10,
                            color: "var(--text-dim)",
                            fontFamily: "var(--font-mono)",
                            letterSpacing: "0.1em",
                            marginTop: 4,
                            textTransform: "uppercase",
                        }}
                    >
                        Agent Console
                    </div>
                </div>
                <nav style={{ flex: 1, padding: "12px 10px" }}>
                    {navItems.map((item) => (
                        <button
                            key={item.id}
                            onClick={() => setView(item.id)}
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 10,
                                width: "100%",
                                padding: "10px 12px",
                                borderRadius: 7,
                                border: "none",
                                cursor: "pointer",
                                background:
                                    view === item.id
                                        ? "var(--gold-glow)"
                                        : "transparent",
                                color:
                                    view === item.id
                                        ? "var(--gold2)"
                                        : "var(--text-mid)",
                                fontSize: 13,
                                fontFamily: "var(--font-body)",
                                textAlign: "left",
                                marginBottom: 2,
                                borderLeft:
                                    view === item.id
                                        ? "2px solid var(--gold)"
                                        : "2px solid transparent",
                            }}
                        >
                            <span style={{ fontSize: 16 }}>{item.icon}</span>
                            <span style={{ flex: 1 }}>{item.label}</span>
                            {item.badge ? (
                                <span
                                    style={{
                                        fontSize: 10,
                                        background: "var(--amber-dim)",
                                        color: "var(--amber)",
                                        borderRadius: 10,
                                        padding: "1px 7px",
                                        fontFamily: "var(--font-mono)",
                                    }}
                                >
                                    {item.badge}
                                </span>
                            ) : null}
                        </button>
                    ))}
                </nav>
                <div
                    style={{
                        padding: "14px 16px",
                        borderTop: "1px solid var(--border)",
                    }}
                >
                    <div
                        style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 10,
                        }}
                    >
                        <Avatar
                            name={session.user.name}
                            size={30}
                            color="var(--gold)"
                        />
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div
                                style={{
                                    fontSize: 12,
                                    color: "var(--text)",
                                    fontWeight: 500,
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                    whiteSpace: "nowrap",
                                }}
                            >
                                {session.user.name}
                            </div>
                            <div
                                style={{
                                    fontSize: 10,
                                    color: "var(--text-dim)",
                                    fontFamily: "var(--font-mono)",
                                    textTransform: "uppercase",
                                }}
                            >
                                {session.user.role}
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Main content */}
            <div
                style={{
                    flex: 1,
                    display: "flex",
                    flexDirection: "column",
                    overflow: "hidden",
                }}
            >
                {/* ── CONVERSATIONS VIEW ── */}
                {view === "conversations" && (
                    <div
                        style={{ display: "flex", flex: 1, overflow: "hidden" }}
                    >
                        {/* Conv List */}
                        <div
                            style={{
                                width: 300,
                                background: "var(--bg2)",
                                borderRight: "1px solid var(--border)",
                                display: "flex",
                                flexDirection: "column",
                            }}
                        >
                            <div
                                style={{
                                    padding: "14px 16px",
                                    borderBottom: "1px solid var(--border)",
                                }}
                            >
                                <div
                                    style={{
                                        fontFamily: "var(--font-mono)",
                                        fontSize: 11,
                                        color: "var(--text-dim)",
                                        letterSpacing: "0.08em",
                                        textTransform: "uppercase",
                                        marginBottom: 10,
                                    }}
                                >
                                    Conversations
                                </div>
                                <div
                                    style={{
                                        display: "flex",
                                        gap: 6,
                                        flexWrap: "wrap",
                                    }}
                                >
                                    {[
                                        "all",
                                        "human",
                                        "ai",
                                        "paused",
                                        "open",
                                    ].map((f) => (
                                        <button
                                            key={f}
                                            onClick={() => setConvFilter(f)}
                                            style={{
                                                padding: "4px 10px",
                                                borderRadius: 4,
                                                border: "1px solid",
                                                borderColor:
                                                    convFilter === f
                                                        ? "var(--gold)"
                                                        : "var(--border)",
                                                background:
                                                    convFilter === f
                                                        ? "var(--gold-dim)"
                                                        : "transparent",
                                                color:
                                                    convFilter === f
                                                        ? "var(--gold2)"
                                                        : "var(--text-dim)",
                                                fontSize: 11,
                                                fontFamily: "var(--font-mono)",
                                                cursor: "pointer",
                                                textTransform: "uppercase",
                                                letterSpacing: "0.04em",
                                            }}
                                        >
                                            {f}
                                        </button>
                                    ))}
                                </div>
                            </div>
                            <div style={{ flex: 1, overflowY: "auto" }}>
                                {filteredConvs.map((conv) => (
                                    <div
                                        key={conv.id}
                                        onClick={() => setActiveConvId(conv.id)}
                                        style={{
                                            padding: "13px 16px",
                                            borderBottom:
                                                "1px solid var(--border)",
                                            cursor: "pointer",
                                            background:
                                                activeConvId === conv.id
                                                    ? "var(--gold-glow)"
                                                    : "transparent",
                                            borderLeft:
                                                conv.intercept_mode === "human"
                                                    ? "3px solid var(--amber)"
                                                    : conv.intercept_mode ===
                                                        "paused"
                                                      ? "3px solid var(--text-dim)"
                                                      : "3px solid var(--blue)",
                                            transition: "background 0.1s",
                                        }}
                                    >
                                        <div
                                            style={{
                                                display: "flex",
                                                alignItems: "center",
                                                gap: 10,
                                            }}
                                        >
                                            <Avatar
                                                name={conv.name}
                                                size={34}
                                            />
                                            <div
                                                style={{ flex: 1, minWidth: 0 }}
                                            >
                                                <div
                                                    style={{
                                                        display: "flex",
                                                        alignItems: "center",
                                                        gap: 6,
                                                        marginBottom: 3,
                                                    }}
                                                >
                                                    <span
                                                        style={{
                                                            fontSize: 13,
                                                            fontWeight: 500,
                                                            color: "var(--text)",
                                                        }}
                                                    >
                                                        {conv.name}
                                                    </span>
                                                    {conv.unread > 0 && (
                                                        <span
                                                            style={{
                                                                fontSize: 10,
                                                                background:
                                                                    "var(--amber)",
                                                                color: "#0f0e0d",
                                                                borderRadius: 10,
                                                                padding:
                                                                    "0 5px",
                                                                fontFamily:
                                                                    "var(--font-mono)",
                                                                fontWeight: 700,
                                                            }}
                                                        >
                                                            {conv.unread}
                                                        </span>
                                                    )}
                                                </div>
                                                <div
                                                    style={{
                                                        fontSize: 11,
                                                        color: "var(--text-dim)",
                                                        overflow: "hidden",
                                                        textOverflow:
                                                            "ellipsis",
                                                        whiteSpace: "nowrap",
                                                    }}
                                                >
                                                    {conv.last_message_preview}
                                                </div>
                                            </div>
                                            <div
                                                style={{
                                                    display: "flex",
                                                    flexDirection: "column",
                                                    alignItems: "flex-end",
                                                    gap: 4,
                                                }}
                                            >
                                                <span
                                                    style={{
                                                        fontSize: 10,
                                                        color: "var(--text-dim)",
                                                        fontFamily:
                                                            "var(--font-mono)",
                                                    }}
                                                >
                                                    {timeAgo(
                                                        conv.last_message_at,
                                                    )}
                                                </span>
                                                <Badge
                                                    type={conv.intercept_mode}
                                                />
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Thread Panel */}
                        <div
                            style={{
                                flex: 1,
                                display: "flex",
                                flexDirection: "column",
                                overflow: "hidden",
                            }}
                        >
                            {/* Conv header */}
                            {activeConv && (
                                <div
                                    style={{
                                        padding: "12px 20px",
                                        borderBottom: "1px solid var(--border)",
                                        background: "var(--bg2)",
                                        display: "flex",
                                        alignItems: "center",
                                        gap: 14,
                                    }}
                                >
                                    <Avatar name={activeConv.name} size={38} />
                                    <div style={{ flex: 1 }}>
                                        <div
                                            style={{
                                                fontSize: 15,
                                                fontWeight: 600,
                                            }}
                                        >
                                            {activeConv.name}
                                        </div>
                                        <div
                                            style={{
                                                fontSize: 11,
                                                color: "var(--text-dim)",
                                                fontFamily: "var(--font-mono)",
                                            }}
                                        >
                                            +{activeConv.wa_id} ·{" "}
                                            {activeConv.wa_id}
                                        </div>
                                    </div>
                                    <Badge type={activeConv.intercept_mode} />
                                    {activeConv.assigned_agent_id && (
                                        <span
                                            style={{
                                                fontSize: 11,
                                                color: "var(--text-dim)",
                                            }}
                                        >
                                            →{" "}
                                            {
                                                agents.find(
                                                    (a) =>
                                                        a.id ===
                                                        activeConv.assigned_agent_id,
                                                )?.name
                                            }
                                        </span>
                                    )}
                                    {/* Controls */}
                                    <div style={{ display: "flex", gap: 8 }}>
                                        {activeConv.intercept_mode === "ai" && (
                                            <Btn
                                                small
                                                onClick={() =>
                                                    intercept(activeConv.id)
                                                }
                                                variant="primary"
                                            >
                                                ⚡ Intercept
                                            </Btn>
                                        )}
                                        {activeConv.intercept_mode ===
                                            "human" && (
                                            <Btn
                                                small
                                                onClick={() =>
                                                    release(activeConv.id)
                                                }
                                                variant="secondary"
                                            >
                                                ↩ Release
                                            </Btn>
                                        )}
                                        {activeConv.intercept_mode !==
                                            "paused" && (
                                            <Btn
                                                small
                                                onClick={() =>
                                                    pause(activeConv.id)
                                                }
                                                variant="secondary"
                                            >
                                                ⏸ Pause AI
                                            </Btn>
                                        )}
                                        {activeConv.intercept_mode ===
                                            "paused" && (
                                            <Btn
                                                small
                                                onClick={() =>
                                                    release(activeConv.id)
                                                }
                                                variant="blue"
                                            >
                                                ▶ Resume AI
                                            </Btn>
                                        )}
                                        <Btn
                                            small
                                            onClick={() =>
                                                setTransferModal(true)
                                            }
                                            variant="secondary"
                                        >
                                            ⇄ Transfer
                                        </Btn>
                                        <Btn
                                            small
                                            onClick={() => setNoteModal(true)}
                                            variant="secondary"
                                        >
                                            📝 Note
                                        </Btn>
                                        {activeConv.status === "open" && (
                                            <Btn
                                                small
                                                onClick={() =>
                                                    closeConv(activeConv.id)
                                                }
                                                variant="danger"
                                            >
                                                ✓ Close
                                            </Btn>
                                        )}
                                    </div>
                                </div>
                            )}

                            {/* Messages */}
                            <div
                                style={{
                                    flex: 1,
                                    overflowY: "auto",
                                    padding: "20px 24px",
                                    display: "flex",
                                    flexDirection: "column",
                                    gap: 14,
                                }}
                            >
                                {activeMessages.map((msg) => {
                                    const isInbound =
                                        msg.direction === "inbound";
                                    const senderColor = {
                                        ai: "var(--blue)",
                                        human_agent: "var(--amber)",
                                        user: "var(--text-dim)",
                                    }[msg.sender];
                                    return (
                                        <div
                                            key={msg.id}
                                            style={{
                                                display: "flex",
                                                flexDirection: isInbound
                                                    ? "row"
                                                    : "row-reverse",
                                                gap: 10,
                                            }}
                                        >
                                            <Avatar
                                                name={
                                                    isInbound
                                                        ? activeConv?.name
                                                        : msg.sender === "ai"
                                                          ? "AI"
                                                          : session.user.name
                                                }
                                                size={30}
                                                color={
                                                    isInbound
                                                        ? undefined
                                                        : senderColor
                                                }
                                            />
                                            <div style={{ maxWidth: "65%" }}>
                                                <div
                                                    style={{
                                                        display: "flex",
                                                        alignItems: "center",
                                                        gap: 6,
                                                        marginBottom: 4,
                                                        flexDirection: isInbound
                                                            ? "row"
                                                            : "row-reverse",
                                                    }}
                                                >
                                                    <span
                                                        style={{
                                                            fontSize: 10,
                                                            fontFamily:
                                                                "var(--font-mono)",
                                                            color:
                                                                senderColor ||
                                                                "var(--text-dim)",
                                                            textTransform:
                                                                "uppercase",
                                                            letterSpacing:
                                                                "0.06em",
                                                        }}
                                                    >
                                                        {msg.sender}
                                                    </span>
                                                    <span
                                                        style={{
                                                            fontSize: 10,
                                                            color: "var(--text-dim)",
                                                            fontFamily:
                                                                "var(--font-mono)",
                                                        }}
                                                    >
                                                        {timeAgo(
                                                            msg.created_at,
                                                        )}
                                                    </span>
                                                </div>
                                                <div
                                                    style={{
                                                        background: isInbound
                                                            ? "var(--bg3)"
                                                            : msg.sender ===
                                                                "ai"
                                                              ? "var(--blue-dim)"
                                                              : "var(--amber-dim)",
                                                        border: `1px solid ${isInbound ? "var(--border)" : msg.sender === "ai" ? "#5b9cf033" : "#e8a84c33"}`,
                                                        borderRadius: isInbound
                                                            ? "4px 12px 12px 12px"
                                                            : "12px 4px 12px 12px",
                                                        padding: "10px 14px",
                                                        fontSize: 13.5,
                                                        color: "var(--text)",
                                                        lineHeight: 1.55,
                                                    }}
                                                >
                                                    {msg.text}
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })}
                                <div ref={messagesEndRef} />
                            </div>

                            {/* AI Draft */}
                            {activeConv?.intercept_mode === "human" &&
                                draftVisible && (
                                    <div
                                        style={{
                                            margin: "0 24px 12px",
                                            background: "var(--blue-dim)",
                                            border: "1px solid #5b9cf033",
                                            borderRadius: 10,
                                            padding: "12px 16px",
                                        }}
                                    >
                                        <div
                                            style={{
                                                display: "flex",
                                                alignItems: "center",
                                                gap: 8,
                                                marginBottom: 8,
                                            }}
                                        >
                                            <span
                                                style={{
                                                    fontSize: 10,
                                                    fontFamily:
                                                        "var(--font-mono)",
                                                    color: "var(--blue)",
                                                    textTransform: "uppercase",
                                                    letterSpacing: "0.06em",
                                                }}
                                            >
                                                🤖 AI Draft (held)
                                            </span>
                                            <button
                                                onClick={() =>
                                                    setDraftVisible(false)
                                                }
                                                style={{
                                                    marginLeft: "auto",
                                                    background: "none",
                                                    border: "none",
                                                    color: "var(--text-dim)",
                                                    fontSize: 14,
                                                    cursor: "pointer",
                                                }}
                                            >
                                                ×
                                            </button>
                                        </div>
                                        <div
                                            style={{
                                                fontSize: 13,
                                                color: "var(--text-mid)",
                                                marginBottom: 12,
                                                lineHeight: 1.5,
                                                fontStyle: "italic",
                                            }}
                                        >
                                            "{AI_DRAFT}"
                                        </div>
                                        <div
                                            style={{ display: "flex", gap: 8 }}
                                        >
                                            <Btn
                                                small
                                                onClick={approveDraft}
                                                variant="success"
                                            >
                                                ✓ Approve & Send
                                            </Btn>
                                            <Btn
                                                small
                                                onClick={() =>
                                                    setDraftVisible(false)
                                                }
                                                variant="secondary"
                                            >
                                                Edit manually
                                            </Btn>
                                        </div>
                                    </div>
                                )}

                            {/* Reply Composer */}
                            {activeConv?.intercept_mode === "human" && (
                                <div
                                    style={{
                                        padding: "12px 20px 16px",
                                        borderTop: "1px solid var(--border)",
                                        background: "var(--bg2)",
                                    }}
                                >
                                    <div
                                        style={{
                                            display: "flex",
                                            gap: 10,
                                            alignItems: "flex-end",
                                        }}
                                    >
                                        <textarea
                                            value={replyText}
                                            onChange={(e) =>
                                                setReplyText(e.target.value)
                                            }
                                            placeholder="Type reply to send via WhatsApp…"
                                            onKeyDown={(e) => {
                                                if (
                                                    e.key === "Enter" &&
                                                    !e.shiftKey
                                                ) {
                                                    e.preventDefault();
                                                    sendReply();
                                                }
                                            }}
                                            style={{
                                                flex: 1,
                                                background: "var(--bg3)",
                                                border: "1px solid var(--border)",
                                                borderRadius: 8,
                                                padding: "10px 14px",
                                                color: "var(--text)",
                                                fontSize: 14,
                                                fontFamily: "var(--font-body)",
                                                resize: "none",
                                                height: 70,
                                                lineHeight: 1.5,
                                            }}
                                        />
                                        <Btn
                                            onClick={sendReply}
                                            disabled={!replyText.trim()}
                                            variant="primary"
                                        >
                                            Send ↗
                                        </Btn>
                                    </div>
                                    <div
                                        style={{
                                            fontSize: 11,
                                            color: "var(--text-dim)",
                                            marginTop: 6,
                                            fontFamily: "var(--font-mono)",
                                        }}
                                    >
                                        Enter to send · Shift+Enter for newline
                                    </div>
                                </div>
                            )}
                            {activeConv?.intercept_mode !== "human" && (
                                <div
                                    style={{
                                        padding: "14px 20px",
                                        borderTop: "1px solid var(--border)",
                                        background: "var(--bg2)",
                                        display: "flex",
                                        alignItems: "center",
                                        gap: 10,
                                    }}
                                >
                                    <div
                                        style={{
                                            flex: 1,
                                            fontSize: 12,
                                            color: "var(--text-dim)",
                                            fontFamily: "var(--font-mono)",
                                        }}
                                    >
                                        {activeConv?.intercept_mode === "paused"
                                            ? "⏸ AI paused — no messages are being sent"
                                            : "🤖 AI is handling this conversation"}
                                    </div>
                                    {activeConv?.intercept_mode === "ai" && (
                                        <Btn
                                            small
                                            onClick={() =>
                                                intercept(activeConv?.id)
                                            }
                                            variant="primary"
                                        >
                                            ⚡ Take Over
                                        </Btn>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {/* ── ORDERS VIEW ── */}
                {view === "orders" && (
                    <div style={{ flex: 1, overflowY: "auto", padding: 28 }}>
                        <div
                            style={{
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "space-between",
                                marginBottom: 20,
                            }}
                        >
                            <div>
                                <h2
                                    style={{
                                        fontFamily: "var(--font-serif)",
                                        fontSize: 22,
                                        color: "var(--gold2)",
                                    }}
                                >
                                    Orders
                                </h2>
                                <p
                                    style={{
                                        fontSize: 12,
                                        color: "var(--text-dim)",
                                        fontFamily: "var(--font-mono)",
                                        marginTop: 2,
                                    }}
                                >
                                    {orders.length} total ·{" "}
                                    {fmtCurrency(stats.revenue)} revenue
                                </p>
                            </div>
                            <select
                                value={orderFilter}
                                onChange={(e) => setOrderFilter(e.target.value)}
                            >
                                {[
                                    "all",
                                    "pending",
                                    "confirmed",
                                    "delivered",
                                    "cancelled",
                                ].map((s) => (
                                    <option key={s} value={s}>
                                        {s.charAt(0).toUpperCase() + s.slice(1)}
                                    </option>
                                ))}
                            </select>
                        </div>
                        <div
                            style={{
                                display: "flex",
                                flexDirection: "column",
                                gap: 12,
                            }}
                        >
                            {filteredOrders.map((order) => (
                                <div
                                    key={order.id}
                                    style={{
                                        background: "var(--bg2)",
                                        border: "1px solid var(--border)",
                                        borderRadius: 10,
                                        padding: "16px 20px",
                                    }}
                                >
                                    <div
                                        style={{
                                            display: "flex",
                                            alignItems: "flex-start",
                                            gap: 14,
                                        }}
                                    >
                                        <div style={{ flex: 1 }}>
                                            <div
                                                style={{
                                                    display: "flex",
                                                    alignItems: "center",
                                                    gap: 10,
                                                    marginBottom: 8,
                                                }}
                                            >
                                                <span
                                                    style={{
                                                        fontWeight: 600,
                                                        fontSize: 14,
                                                    }}
                                                >
                                                    {order.customer_name}
                                                </span>
                                                <span
                                                    style={{
                                                        fontSize: 11,
                                                        color: "var(--text-dim)",
                                                        fontFamily:
                                                            "var(--font-mono)",
                                                    }}
                                                >
                                                    +{order.wa_id}
                                                </span>
                                                <StatusBadge
                                                    status={order.status}
                                                />
                                                <span
                                                    style={{
                                                        marginLeft: "auto",
                                                        fontSize: 11,
                                                        color: "var(--text-dim)",
                                                        fontFamily:
                                                            "var(--font-mono)",
                                                    }}
                                                >
                                                    {timeAgo(order.created_at)}
                                                </span>
                                            </div>
                                            <div
                                                style={{
                                                    display: "flex",
                                                    gap: 8,
                                                    flexWrap: "wrap",
                                                }}
                                            >
                                                {order.items.map((item, i) => (
                                                    <span
                                                        key={i}
                                                        style={{
                                                            fontSize: 12,
                                                            background:
                                                                "var(--bg3)",
                                                            border: "1px solid var(--border)",
                                                            borderRadius: 6,
                                                            padding: "4px 10px",
                                                            color: "var(--text-mid)",
                                                        }}
                                                    >
                                                        {item.qty}× {item.name}{" "}
                                                        ·{" "}
                                                        {fmtCurrency(
                                                            item.total,
                                                        )}
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                        <div style={{ textAlign: "right" }}>
                                            <div
                                                style={{
                                                    fontFamily:
                                                        "var(--font-serif)",
                                                    fontSize: 20,
                                                    color: "var(--gold2)",
                                                    marginBottom: 8,
                                                }}
                                            >
                                                {fmtCurrency(order.subtotal)}
                                            </div>
                                            <div
                                                style={{
                                                    fontSize: 11,
                                                    color: "var(--text-dim)",
                                                    fontFamily:
                                                        "var(--font-mono)",
                                                    marginBottom: 10,
                                                }}
                                            >
                                                via{" "}
                                                {order.payment.toUpperCase()}
                                            </div>
                                            {order.status === "pending" && (
                                                <div
                                                    style={{
                                                        display: "flex",
                                                        gap: 6,
                                                    }}
                                                >
                                                    <Btn
                                                        small
                                                        onClick={() =>
                                                            updateOrderStatus(
                                                                order.id,
                                                                "confirmed",
                                                            )
                                                        }
                                                        variant="success"
                                                    >
                                                        Confirm
                                                    </Btn>
                                                    <Btn
                                                        small
                                                        onClick={() =>
                                                            updateOrderStatus(
                                                                order.id,
                                                                "cancelled",
                                                            )
                                                        }
                                                        variant="danger"
                                                    >
                                                        Cancel
                                                    </Btn>
                                                </div>
                                            )}
                                            {order.status === "confirmed" && (
                                                <Btn
                                                    small
                                                    onClick={() =>
                                                        updateOrderStatus(
                                                            order.id,
                                                            "delivered",
                                                        )
                                                    }
                                                    variant="blue"
                                                >
                                                    Mark Delivered
                                                </Btn>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            ))}
                            {filteredOrders.length === 0 && (
                                <div
                                    style={{
                                        textAlign: "center",
                                        color: "var(--text-dim)",
                                        padding: 60,
                                        fontFamily: "var(--font-mono)",
                                        fontSize: 13,
                                    }}
                                >
                                    No orders found
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {/* ── AGENTS VIEW (Admin only) ── */}
                {view === "agents" && isAdmin && (
                    <div style={{ flex: 1, overflowY: "auto", padding: 28 }}>
                        <div
                            style={{
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "space-between",
                                marginBottom: 20,
                            }}
                        >
                            <div>
                                <h2
                                    style={{
                                        fontFamily: "var(--font-serif)",
                                        fontSize: 22,
                                        color: "var(--gold2)",
                                    }}
                                >
                                    Agents
                                </h2>
                                <p
                                    style={{
                                        fontSize: 12,
                                        color: "var(--text-dim)",
                                        fontFamily: "var(--font-mono)",
                                        marginTop: 2,
                                    }}
                                >
                                    {
                                        agents.filter((a) => a.is_available)
                                            .length
                                    }{" "}
                                    online · {agents.length} total
                                </p>
                            </div>
                            <Btn
                                onClick={() => setAgentModal("create")}
                                variant="primary"
                            >
                                + New Agent
                            </Btn>
                        </div>
                        <div
                            style={{
                                display: "grid",
                                gridTemplateColumns:
                                    "repeat(auto-fill, minmax(280px, 1fr))",
                                gap: 14,
                            }}
                        >
                            {agents.map((agent) => (
                                <div
                                    key={agent.id}
                                    style={{
                                        background: "var(--bg2)",
                                        border: "1px solid var(--border)",
                                        borderRadius: 10,
                                        padding: 20,
                                    }}
                                >
                                    <div
                                        style={{
                                            display: "flex",
                                            alignItems: "center",
                                            gap: 12,
                                            marginBottom: 14,
                                        }}
                                    >
                                        <div style={{ position: "relative" }}>
                                            <Avatar
                                                name={agent.name}
                                                size={44}
                                            />
                                            <span
                                                style={{
                                                    position: "absolute",
                                                    bottom: 1,
                                                    right: 1,
                                                    width: 10,
                                                    height: 10,
                                                    borderRadius: "50%",
                                                    background:
                                                        agent.is_available
                                                            ? "var(--green)"
                                                            : "var(--text-dim)",
                                                    border: "2px solid var(--bg2)",
                                                }}
                                            />
                                        </div>
                                        <div style={{ flex: 1 }}>
                                            <div
                                                style={{
                                                    fontWeight: 600,
                                                    fontSize: 14,
                                                }}
                                            >
                                                {agent.name}
                                            </div>
                                            <div
                                                style={{
                                                    fontSize: 11,
                                                    color: "var(--text-dim)",
                                                    fontFamily:
                                                        "var(--font-mono)",
                                                }}
                                            >
                                                {agent.email}
                                            </div>
                                        </div>
                                        <span
                                            style={{
                                                fontSize: 10,
                                                background:
                                                    agent.role === "admin"
                                                        ? "var(--gold-dim)"
                                                        : "var(--bg3)",
                                                color:
                                                    agent.role === "admin"
                                                        ? "var(--gold2)"
                                                        : "var(--text-dim)",
                                                border: "1px solid",
                                                borderColor:
                                                    agent.role === "admin"
                                                        ? "var(--gold)44"
                                                        : "var(--border)",
                                                borderRadius: 4,
                                                padding: "2px 8px",
                                                fontFamily: "var(--font-mono)",
                                                textTransform: "uppercase",
                                            }}
                                        >
                                            {agent.role}
                                        </span>
                                    </div>
                                    <div
                                        style={{
                                            display: "grid",
                                            gridTemplateColumns: "1fr 1fr",
                                            gap: 10,
                                            marginBottom: 14,
                                        }}
                                    >
                                        <div
                                            style={{
                                                background: "var(--bg3)",
                                                borderRadius: 6,
                                                padding: "8px 12px",
                                            }}
                                        >
                                            <div
                                                style={{
                                                    fontSize: 10,
                                                    color: "var(--text-dim)",
                                                    fontFamily:
                                                        "var(--font-mono)",
                                                    marginBottom: 2,
                                                }}
                                            >
                                                ACTIVE CONVS
                                            </div>
                                            <div
                                                style={{
                                                    fontSize: 18,
                                                    fontFamily:
                                                        "var(--font-serif)",
                                                    color: "var(--text)",
                                                }}
                                            >
                                                {agent.active_convs}
                                            </div>
                                        </div>
                                        <div
                                            style={{
                                                background: "var(--bg3)",
                                                borderRadius: 6,
                                                padding: "8px 12px",
                                            }}
                                        >
                                            <div
                                                style={{
                                                    fontSize: 10,
                                                    color: "var(--text-dim)",
                                                    fontFamily:
                                                        "var(--font-mono)",
                                                    marginBottom: 2,
                                                }}
                                            >
                                                LAST SEEN
                                            </div>
                                            <div
                                                style={{
                                                    fontSize: 12,
                                                    color: "var(--text-mid)",
                                                    fontFamily:
                                                        "var(--font-mono)",
                                                }}
                                            >
                                                {agent.last_seen_at
                                                    ? timeAgo(
                                                          agent.last_seen_at,
                                                      )
                                                    : "never"}
                                            </div>
                                        </div>
                                    </div>
                                    <div style={{ display: "flex", gap: 8 }}>
                                        <button
                                            onClick={() =>
                                                toggleAgentAvailable(agent.id)
                                            }
                                            style={{
                                                flex: 1,
                                                padding: "7px 0",
                                                borderRadius: 6,
                                                border: "1px solid var(--border)",
                                                background: "transparent",
                                                color: agent.is_available
                                                    ? "var(--green)"
                                                    : "var(--text-dim)",
                                                fontSize: 12,
                                                fontFamily: "var(--font-mono)",
                                                cursor: "pointer",
                                            }}
                                        >
                                            {agent.is_available
                                                ? "● Online"
                                                : "○ Offline"}
                                        </button>
                                        <button
                                            onClick={() => setAgentModal(agent)}
                                            style={{
                                                padding: "7px 14px",
                                                borderRadius: 6,
                                                border: "1px solid var(--border)",
                                                background: "transparent",
                                                color: "var(--text-dim)",
                                                fontSize: 12,
                                                fontFamily: "var(--font-mono)",
                                                cursor: "pointer",
                                            }}
                                        >
                                            Edit
                                        </button>
                                        <button
                                            onClick={() =>
                                                deleteAgent(agent.id)
                                            }
                                            style={{
                                                padding: "7px 12px",
                                                borderRadius: 6,
                                                border: "1px solid #e0555533",
                                                background: "var(--red-dim)",
                                                color: "var(--red)",
                                                fontSize: 12,
                                                fontFamily: "var(--font-mono)",
                                                cursor: "pointer",
                                            }}
                                        >
                                            ✕
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* ── CATALOG VIEW (Admin only) ── */}
                {view === "catalog" && isAdmin && (
                    <div style={{ flex: 1, overflowY: "auto", padding: 28 }}>
                        <div
                            style={{
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "space-between",
                                marginBottom: 20,
                            }}
                        >
                            <div>
                                <h2
                                    style={{
                                        fontFamily: "var(--font-serif)",
                                        fontSize: 22,
                                        color: "var(--gold2)",
                                    }}
                                >
                                    Catalog
                                </h2>
                                <p
                                    style={{
                                        fontSize: 12,
                                        color: "var(--text-dim)",
                                        fontFamily: "var(--font-mono)",
                                        marginTop: 2,
                                    }}
                                >
                                    {catalog.filter((c) => c.in_stock).length}{" "}
                                    in stock · {catalog.length} items
                                </p>
                            </div>
                            <Btn
                                onClick={() => setCatalogModal("create")}
                                variant="primary"
                            >
                                + Add Item
                            </Btn>
                        </div>
                        <div
                            style={{
                                background: "var(--bg2)",
                                border: "1px solid var(--border)",
                                borderRadius: 10,
                                overflow: "hidden",
                            }}
                        >
                            <table
                                style={{
                                    width: "100%",
                                    borderCollapse: "collapse",
                                }}
                            >
                                <thead>
                                    <tr
                                        style={{
                                            borderBottom:
                                                "1px solid var(--border)",
                                        }}
                                    >
                                        {[
                                            "SKU",
                                            "Name",
                                            "Category",
                                            "Price",
                                            "Stock",
                                            "",
                                        ].map((h) => (
                                            <th
                                                key={h}
                                                style={{
                                                    padding: "11px 16px",
                                                    textAlign: "left",
                                                    fontSize: 10,
                                                    fontFamily:
                                                        "var(--font-mono)",
                                                    color: "var(--text-dim)",
                                                    letterSpacing: "0.06em",
                                                    textTransform: "uppercase",
                                                    fontWeight: 500,
                                                }}
                                            >
                                                {h}
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {catalog.map((item) => (
                                        <tr
                                            key={item.id}
                                            style={{
                                                borderBottom:
                                                    "1px solid var(--border)",
                                            }}
                                        >
                                            <td
                                                style={{
                                                    padding: "12px 16px",
                                                    fontSize: 12,
                                                    fontFamily:
                                                        "var(--font-mono)",
                                                    color: "var(--text-dim)",
                                                }}
                                            >
                                                {item.sku}
                                            </td>
                                            <td
                                                style={{
                                                    padding: "12px 16px",
                                                    fontSize: 13,
                                                    color: "var(--text)",
                                                    fontWeight: 500,
                                                }}
                                            >
                                                {item.name}
                                                {item.description && (
                                                    <div
                                                        style={{
                                                            fontSize: 11,
                                                            color: "var(--text-dim)",
                                                            marginTop: 2,
                                                        }}
                                                    >
                                                        {item.description}
                                                    </div>
                                                )}
                                            </td>
                                            <td
                                                style={{ padding: "12px 16px" }}
                                            >
                                                <span
                                                    style={{
                                                        fontSize: 11,
                                                        background:
                                                            "var(--bg3)",
                                                        border: "1px solid var(--border)",
                                                        borderRadius: 4,
                                                        padding: "2px 8px",
                                                        color: "var(--text-mid)",
                                                        fontFamily:
                                                            "var(--font-mono)",
                                                    }}
                                                >
                                                    {item.category}
                                                </span>
                                            </td>
                                            <td
                                                style={{
                                                    padding: "12px 16px",
                                                    fontFamily:
                                                        "var(--font-mono)",
                                                    fontSize: 13,
                                                    color: "var(--gold2)",
                                                }}
                                            >
                                                {fmtCurrency(item.price)}
                                            </td>
                                            <td
                                                style={{ padding: "12px 16px" }}
                                            >
                                                <button
                                                    onClick={() =>
                                                        toggleStock(item.id)
                                                    }
                                                    style={{
                                                        padding: "4px 12px",
                                                        borderRadius: 4,
                                                        border: "1px solid",
                                                        borderColor:
                                                            item.in_stock
                                                                ? "#4caf7d44"
                                                                : "#e0555533",
                                                        background:
                                                            item.in_stock
                                                                ? "var(--green-dim)"
                                                                : "var(--red-dim)",
                                                        color: item.in_stock
                                                            ? "var(--green)"
                                                            : "var(--red)",
                                                        fontSize: 11,
                                                        fontFamily:
                                                            "var(--font-mono)",
                                                        cursor: "pointer",
                                                    }}
                                                >
                                                    {item.in_stock
                                                        ? "● In Stock"
                                                        : "○ Out"}
                                                </button>
                                            </td>
                                            <td
                                                style={{ padding: "12px 16px" }}
                                            >
                                                <button
                                                    onClick={() =>
                                                        setCatalogModal(item)
                                                    }
                                                    style={{
                                                        padding: "5px 12px",
                                                        borderRadius: 4,
                                                        border: "1px solid var(--border)",
                                                        background:
                                                            "transparent",
                                                        color: "var(--text-dim)",
                                                        fontSize: 11,
                                                        fontFamily:
                                                            "var(--font-mono)",
                                                        cursor: "pointer",
                                                    }}
                                                >
                                                    Edit
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}

                {/* ── OVERVIEW (Super Admin) ── */}
                {view === "overview" && isAdmin && (
                    <div style={{ flex: 1, overflowY: "auto", padding: 28 }}>
                        <h2
                            style={{
                                fontFamily: "var(--font-serif)",
                                fontSize: 22,
                                color: "var(--gold2)",
                                marginBottom: 20,
                            }}
                        >
                            Overview
                        </h2>
                        <div
                            style={{
                                display: "grid",
                                gridTemplateColumns: "repeat(3, 1fr)",
                                gap: 14,
                                marginBottom: 24,
                            }}
                        >
                            {[
                                {
                                    label: "Open Conversations",
                                    value: stats.openConvs,
                                    color: "var(--blue)",
                                },
                                {
                                    label: "Human-Intercepted",
                                    value: stats.humanConvs,
                                    color: "var(--amber)",
                                },
                                {
                                    label: "Active Agents",
                                    value: stats.activeAgents,
                                    color: "var(--green)",
                                },
                                {
                                    label: "Total Orders",
                                    value: stats.totalOrders,
                                    color: "var(--text-mid)",
                                },
                                {
                                    label: "Pending Orders",
                                    value: stats.pendingOrders,
                                    color: "var(--red)",
                                },
                                {
                                    label: "Revenue (KES)",
                                    value: stats.revenue.toLocaleString(),
                                    color: "var(--gold2)",
                                },
                            ].map((s, i) => (
                                <div
                                    key={i}
                                    style={{
                                        background: "var(--bg2)",
                                        border: "1px solid var(--border)",
                                        borderRadius: 10,
                                        padding: "18px 20px",
                                        position: "relative",
                                        overflow: "hidden",
                                    }}
                                >
                                    <div
                                        style={{
                                            position: "absolute",
                                            top: 0,
                                            left: 0,
                                            right: 0,
                                            height: 2,
                                            background: `linear-gradient(90deg, transparent, ${s.color}, transparent)`,
                                            opacity: 0.6,
                                        }}
                                    />
                                    <div
                                        style={{
                                            fontSize: 10,
                                            fontFamily: "var(--font-mono)",
                                            color: "var(--text-dim)",
                                            letterSpacing: "0.08em",
                                            textTransform: "uppercase",
                                            marginBottom: 8,
                                        }}
                                    >
                                        {s.label}
                                    </div>
                                    <div
                                        style={{
                                            fontFamily: "var(--font-serif)",
                                            fontSize: 32,
                                            color: s.color,
                                        }}
                                    >
                                        {s.value}
                                    </div>
                                </div>
                            ))}
                        </div>
                        <div
                            style={{
                                display: "grid",
                                gridTemplateColumns: "1fr 1fr",
                                gap: 14,
                            }}
                        >
                            <div
                                style={{
                                    background: "var(--bg2)",
                                    border: "1px solid var(--border)",
                                    borderRadius: 10,
                                    padding: 20,
                                }}
                            >
                                <div
                                    style={{
                                        fontSize: 11,
                                        fontFamily: "var(--font-mono)",
                                        color: "var(--text-dim)",
                                        textTransform: "uppercase",
                                        letterSpacing: "0.08em",
                                        marginBottom: 14,
                                    }}
                                >
                                    Conversation Modes
                                </div>
                                {["ai", "human", "paused"].map((mode) => {
                                    const count = conversations.filter(
                                        (c) => c.intercept_mode === mode,
                                    ).length;
                                    const pct = Math.round(
                                        (count / conversations.length) * 100,
                                    );
                                    const color = {
                                        ai: "var(--blue)",
                                        human: "var(--amber)",
                                        paused: "var(--text-dim)",
                                    }[mode];
                                    return (
                                        <div
                                            key={mode}
                                            style={{ marginBottom: 12 }}
                                        >
                                            <div
                                                style={{
                                                    display: "flex",
                                                    justifyContent:
                                                        "space-between",
                                                    fontSize: 12,
                                                    marginBottom: 5,
                                                }}
                                            >
                                                <span
                                                    style={{
                                                        fontFamily:
                                                            "var(--font-mono)",
                                                        textTransform:
                                                            "uppercase",
                                                        color,
                                                    }}
                                                >
                                                    {mode}
                                                </span>
                                                <span
                                                    style={{
                                                        color: "var(--text-dim)",
                                                        fontFamily:
                                                            "var(--font-mono)",
                                                    }}
                                                >
                                                    {count} ({pct}%)
                                                </span>
                                            </div>
                                            <div
                                                style={{
                                                    height: 4,
                                                    background: "var(--bg3)",
                                                    borderRadius: 2,
                                                }}
                                            >
                                                <div
                                                    style={{
                                                        height: "100%",
                                                        width: `${pct}%`,
                                                        background: color,
                                                        borderRadius: 2,
                                                        transition:
                                                            "width 0.3s",
                                                    }}
                                                />
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                            <div
                                style={{
                                    background: "var(--bg2)",
                                    border: "1px solid var(--border)",
                                    borderRadius: 10,
                                    padding: 20,
                                }}
                            >
                                <div
                                    style={{
                                        fontSize: 11,
                                        fontFamily: "var(--font-mono)",
                                        color: "var(--text-dim)",
                                        textTransform: "uppercase",
                                        letterSpacing: "0.08em",
                                        marginBottom: 14,
                                    }}
                                >
                                    Order Status Breakdown
                                </div>
                                {[
                                    "pending",
                                    "confirmed",
                                    "delivered",
                                    "cancelled",
                                ].map((status) => {
                                    const count = orders.filter(
                                        (o) => o.status === status,
                                    ).length;
                                    const pct = Math.round(
                                        (count / orders.length) * 100,
                                    );
                                    const color = {
                                        pending: "var(--amber)",
                                        confirmed: "var(--blue)",
                                        delivered: "var(--green)",
                                        cancelled: "var(--red)",
                                    }[status];
                                    return (
                                        <div
                                            key={status}
                                            style={{ marginBottom: 12 }}
                                        >
                                            <div
                                                style={{
                                                    display: "flex",
                                                    justifyContent:
                                                        "space-between",
                                                    fontSize: 12,
                                                    marginBottom: 5,
                                                }}
                                            >
                                                <span
                                                    style={{
                                                        fontFamily:
                                                            "var(--font-mono)",
                                                        textTransform:
                                                            "uppercase",
                                                        color,
                                                    }}
                                                >
                                                    {status}
                                                </span>
                                                <span
                                                    style={{
                                                        color: "var(--text-dim)",
                                                        fontFamily:
                                                            "var(--font-mono)",
                                                    }}
                                                >
                                                    {count} ({pct}%)
                                                </span>
                                            </div>
                                            <div
                                                style={{
                                                    height: 4,
                                                    background: "var(--bg3)",
                                                    borderRadius: 2,
                                                }}
                                            >
                                                <div
                                                    style={{
                                                        height: "100%",
                                                        width: `${pct}%`,
                                                        background: color,
                                                        borderRadius: 2,
                                                        transition:
                                                            "width 0.3s",
                                                    }}
                                                />
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    </div>
                )}
            </div>

            {/* ── MODALS ── */}

            {/* Transfer */}
            <Modal
                show={transferModal}
                onClose={() => setTransferModal(false)}
                title="Transfer Conversation"
            >
                <p
                    style={{
                        fontSize: 13,
                        color: "var(--text-dim)",
                        marginBottom: 16,
                    }}
                >
                    Select an agent to transfer this conversation to:
                </p>
                <div
                    style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: 10,
                    }}
                >
                    {agents
                        .filter((a) => a.id !== "a1" && a.is_available)
                        .map((agent) => (
                            <button
                                key={agent.id}
                                onClick={() => transferConv(agent.id)}
                                style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 12,
                                    padding: "12px 14px",
                                    borderRadius: 8,
                                    border: "1px solid var(--border)",
                                    background: "var(--bg3)",
                                    cursor: "pointer",
                                    textAlign: "left",
                                }}
                            >
                                <Avatar name={agent.name} size={32} />
                                <div style={{ flex: 1 }}>
                                    <div
                                        style={{
                                            fontSize: 13,
                                            color: "var(--text)",
                                            fontWeight: 500,
                                        }}
                                    >
                                        {agent.name}
                                    </div>
                                    <div
                                        style={{
                                            fontSize: 11,
                                            color: "var(--text-dim)",
                                            fontFamily: "var(--font-mono)",
                                        }}
                                    >
                                        {agent.active_convs} active ·{" "}
                                        {agent.role}
                                    </div>
                                </div>
                                <span
                                    style={{
                                        fontSize: 11,
                                        color: "var(--green)",
                                        fontFamily: "var(--font-mono)",
                                    }}
                                >
                                    ● Online
                                </span>
                            </button>
                        ))}
                </div>
            </Modal>

            {/* Note */}
            <Modal
                show={noteModal}
                onClose={() => setNoteModal(false)}
                title="Add Internal Note"
            >
                <p
                    style={{
                        fontSize: 13,
                        color: "var(--text-dim)",
                        marginBottom: 16,
                    }}
                >
                    Notes are visible to agents only, not sent to customer.
                </p>
                <InputField
                    label="Note"
                    value={noteText}
                    onChange={setNoteText}
                    placeholder="Type your note here…"
                />
                <Btn onClick={addNote} variant="primary">
                    Save Note
                </Btn>
            </Modal>

            {/* Agent Create/Edit */}
            <Modal
                show={!!agentModal}
                onClose={() => setAgentModal(null)}
                title={
                    agentModal === "create"
                        ? "New Agent"
                        : `Edit ${agentModal?.name}`
                }
            >
                {agentModal === "create" ? (
                    <>
                        <InputField
                            label="Full Name"
                            value={newAgentForm.name}
                            onChange={(v) =>
                                setNewAgentForm((f) => ({ ...f, name: v }))
                            }
                            placeholder="Jane Doe"
                        />
                        <InputField
                            label="Email"
                            value={newAgentForm.email}
                            onChange={(v) =>
                                setNewAgentForm((f) => ({ ...f, email: v }))
                            }
                            placeholder="jane@neema.co"
                            type="email"
                        />
                        <InputField
                            label="Password"
                            value={newAgentForm.password}
                            onChange={(v) =>
                                setNewAgentForm((f) => ({ ...f, password: v }))
                            }
                            placeholder="••••••••"
                            type="password"
                        />
                        <div style={{ marginBottom: 20 }}>
                            <label
                                style={{
                                    fontSize: 11,
                                    fontFamily: "var(--font-mono)",
                                    color: "var(--text-dim)",
                                    letterSpacing: "0.06em",
                                    textTransform: "uppercase",
                                    display: "block",
                                    marginBottom: 6,
                                }}
                            >
                                Role
                            </label>
                            <select
                                value={newAgentForm.role}
                                onChange={(e) =>
                                    setNewAgentForm((f) => ({
                                        ...f,
                                        role: e.target.value,
                                    }))
                                }
                            >
                                <option value="agent">Agent</option>
                                <option value="admin">Admin</option>
                                <option value="readonly">Readonly</option>
                            </select>
                        </div>
                        <div style={{ display: "flex", gap: 10 }}>
                            <Btn onClick={createAgent} variant="primary">
                                Create Agent
                            </Btn>
                            <Btn
                                onClick={() => setAgentModal(null)}
                                variant="secondary"
                            >
                                Cancel
                            </Btn>
                        </div>
                    </>
                ) : (
                    agentModal && (
                        <>
                            <div
                                style={{
                                    padding: "14px 16px",
                                    background: "var(--bg3)",
                                    borderRadius: 8,
                                    marginBottom: 20,
                                }}
                            >
                                <div
                                    style={{
                                        fontSize: 13,
                                        color: "var(--text-mid)",
                                    }}
                                >
                                    Agent ID:{" "}
                                    <span
                                        style={{
                                            fontFamily: "var(--font-mono)",
                                            color: "var(--text-dim)",
                                            fontSize: 11,
                                        }}
                                    >
                                        {agentModal.id}
                                    </span>
                                </div>
                                <div
                                    style={{
                                        fontSize: 13,
                                        color: "var(--text-mid)",
                                        marginTop: 4,
                                    }}
                                >
                                    Email:{" "}
                                    <span style={{ color: "var(--text)" }}>
                                        {agentModal.email}
                                    </span>
                                </div>
                                <div
                                    style={{
                                        fontSize: 13,
                                        color: "var(--text-mid)",
                                        marginTop: 4,
                                    }}
                                >
                                    Role:{" "}
                                    <span style={{ color: "var(--gold2)" }}>
                                        {agentModal.role}
                                    </span>
                                </div>
                            </div>
                            <div style={{ display: "flex", gap: 10 }}>
                                <Btn
                                    onClick={() => {
                                        toggleAgentAvailable(agentModal.id);
                                        setAgentModal(null);
                                    }}
                                    variant={
                                        agentModal.is_available
                                            ? "secondary"
                                            : "success"
                                    }
                                >
                                    {agentModal.is_available
                                        ? "Set Offline"
                                        : "Set Online"}
                                </Btn>
                                <Btn
                                    onClick={() => {
                                        deleteAgent(agentModal.id);
                                        setAgentModal(null);
                                    }}
                                    variant="danger"
                                >
                                    Remove Agent
                                </Btn>
                                <Btn
                                    onClick={() => setAgentModal(null)}
                                    variant="secondary"
                                >
                                    Close
                                </Btn>
                            </div>
                        </>
                    )
                )}
            </Modal>

            {/* Catalog Create/Edit */}
            <Modal
                show={!!catalogModal}
                onClose={() => setCatalogModal(null)}
                title={
                    catalogModal === "create"
                        ? "Add Catalog Item"
                        : `Edit ${catalogModal?.name}`
                }
            >
                {catalogModal === "create" ? (
                    <>
                        <div
                            style={{
                                display: "grid",
                                gridTemplateColumns: "1fr 1fr",
                                gap: 10,
                            }}
                        >
                            <InputField
                                label="SKU"
                                value={newCatalogForm.sku}
                                onChange={(v) =>
                                    setNewCatalogForm((f) => ({ ...f, sku: v }))
                                }
                                placeholder="JRC-001"
                            />
                            <InputField
                                label="Price (KES)"
                                value={newCatalogForm.price}
                                onChange={(v) =>
                                    setNewCatalogForm((f) => ({
                                        ...f,
                                        price: v,
                                    }))
                                }
                                type="number"
                                placeholder="400"
                            />
                        </div>
                        <InputField
                            label="Name"
                            value={newCatalogForm.name}
                            onChange={(v) =>
                                setNewCatalogForm((f) => ({ ...f, name: v }))
                            }
                            placeholder="Jollof Rice Combo"
                        />
                        <InputField
                            label="Category"
                            value={newCatalogForm.category}
                            onChange={(v) =>
                                setNewCatalogForm((f) => ({
                                    ...f,
                                    category: v,
                                }))
                            }
                            placeholder="Mains"
                        />
                        <InputField
                            label="Description"
                            value={newCatalogForm.description}
                            onChange={(v) =>
                                setNewCatalogForm((f) => ({
                                    ...f,
                                    description: v,
                                }))
                            }
                            placeholder="Short description…"
                        />
                        <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
                            <Btn onClick={createCatalogItem} variant="primary">
                                Add to Catalog
                            </Btn>
                            <Btn
                                onClick={() => setCatalogModal(null)}
                                variant="secondary"
                            >
                                Cancel
                            </Btn>
                        </div>
                    </>
                ) : (
                    catalogModal && (
                        <>
                            <div
                                style={{
                                    padding: "14px 16px",
                                    background: "var(--bg3)",
                                    borderRadius: 8,
                                    marginBottom: 20,
                                }}
                            >
                                {[
                                    ["SKU", catalogModal.sku],
                                    ["Category", catalogModal.category],
                                    ["Price", fmtCurrency(catalogModal.price)],
                                    [
                                        "In Stock",
                                        catalogModal.in_stock ? "Yes" : "No",
                                    ],
                                ].map(([k, v]) => (
                                    <div
                                        key={k}
                                        style={{
                                            fontSize: 13,
                                            color: "var(--text-mid)",
                                            marginBottom: 4,
                                        }}
                                    >
                                        {k}:{" "}
                                        <span style={{ color: "var(--text)" }}>
                                            {v}
                                        </span>
                                    </div>
                                ))}
                            </div>
                            <div style={{ display: "flex", gap: 10 }}>
                                <Btn
                                    onClick={() => {
                                        toggleStock(catalogModal.id);
                                        setCatalogModal(null);
                                    }}
                                    variant={
                                        catalogModal.in_stock
                                            ? "danger"
                                            : "success"
                                    }
                                >
                                    {catalogModal.in_stock
                                        ? "Mark Out of Stock"
                                        : "Mark In Stock"}
                                </Btn>
                                <Btn
                                    onClick={() => setCatalogModal(null)}
                                    variant="secondary"
                                >
                                    Close
                                </Btn>
                            </div>
                        </>
                    )
                )}
            </Modal>
        </div>
    );
}
