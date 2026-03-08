import { ReactNode, CSSProperties, MouseEventHandler } from "react";
import { initials } from "@/lib/utils";
import { AgentRole, ROLE_DEFINITIONS } from "@/lib/mockData";

// ── Avatar ─────────────────────────────────────────────────────────────────────

interface AvatarProps {
    name?: string;
    size?: number;
    color?: string;
}

export function Avatar({ name, size = 36, color }: AvatarProps) {
    const colors = [
        "#c9a84c",
        "#5b9cf0",
        "#4caf7d",
        "#e05555",
        "#e8a84c",
        "#9b72d0",
        "#2ecc71",
        "#e74c3c",
    ];
    const bg = color ?? colors[(name?.charCodeAt(0) ?? 0) % colors.length];
    const isDark = !color;
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
                color: isDark ? "#fff" : "#0f0e0d",
                fontWeight: 700,
                flexShrink: 0,
                letterSpacing: "0.02em",
            }}
        >
            {initials(name)}
        </div>
    );
}

// ── Badge ──────────────────────────────────────────────────────────────────────

interface BadgeProps {
    type: "ai" | "human" | "paused";
}

export function Badge({ type }: BadgeProps) {
    const map: Record<string, { label: string; bg: string; color: string }> = {
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
    const s = map[type] ?? map.ai;
    return (
        <span
            style={{
                fontSize: 10,
                fontFamily: "var(--font-mono)",
                background: s.bg,
                color: s.color,
                padding: "2px 8px",
                borderRadius: 4,
                letterSpacing: "0.06em",
            }}
        >
            {s.label}
        </span>
    );
}

// ── StatusBadge ────────────────────────────────────────────────────────────────

interface StatusBadgeProps {
    status: string;
}

export function StatusBadge({ status }: StatusBadgeProps) {
    const map: Record<string, string> = {
        pending: "var(--amber)",
        confirmed: "var(--blue)",
        delivered: "var(--green)",
        cancelled: "var(--red)",
    };
    const col = map[status] ?? "var(--text-dim)";
    return (
        <span
            style={{
                fontSize: 10,
                fontFamily: "var(--font-mono)",
                color: col,
                background: `${col.replace("var(", "").replace(")", "")}-dim`,
                padding: "2px 8px",
                borderRadius: 4,
                letterSpacing: "0.05em",
                textTransform: "uppercase",
            }}
        >
            {status}
        </span>
    );
}

// ── RoleBadge ─────────────────────────────────────────────────────────────────

interface RoleBadgeProps {
    role: AgentRole;
}

export function RoleBadge({ role }: RoleBadgeProps) {
    const r = ROLE_DEFINITIONS[role] ?? { label: role, color: "#8c8279" };
    return (
        <span
            style={{
                fontSize: 10,
                fontFamily: "var(--font-mono)",
                color: r.color,
                background: `${r.color}20`,
                padding: "2px 8px",
                borderRadius: 4,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
            }}
        >
            {r.label}
        </span>
    );
}

// ── Modal ─────────────────────────────────────────────────────────────────────

interface ModalProps {
    show: boolean;
    onClose: () => void;
    title: string;
    children: ReactNode;
    wide?: boolean;
}

export function Modal({ show, onClose, title, children, wide }: ModalProps) {
    if (!show) return null;
    return (
        <div
            style={{
                position: "fixed",
                inset: 0,
                zIndex: 200,
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
                    background: "rgba(0,0,0,0.55)",
                    backdropFilter: "blur(6px)",
                }}
            />
            <div
                style={{
                    position: "relative",
                    background: "var(--bg2)",
                    border: "1px solid var(--border2)",
                    borderRadius: 14,
                    padding: "28px 32px",
                    width: wide ? 640 : 480,
                    maxWidth: "92vw",
                    maxHeight: "85vh",
                    overflowY: "auto",
                    boxShadow: "var(--shadow-md)",
                }}
                onClick={(e) => e.stopPropagation()}
            >
                <div
                    style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        marginBottom: 24,
                    }}
                >
                    <h3
                        style={{
                            fontFamily: "var(--font-serif)",
                            fontSize: 20,
                            color: "var(--gold2)",
                            letterSpacing: "0.01em",
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
                            fontSize: 22,
                            cursor: "pointer",
                            lineHeight: 1,
                            padding: "0 4px",
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

// ── InputField ────────────────────────────────────────────────────────────────

interface InputFieldProps {
    label: string;
    value: string | number;
    onChange: (value: string) => void;
    type?: string;
    placeholder?: string;
    hint?: string;
}

export function InputField({
    label,
    value,
    onChange,
    type = "text",
    placeholder,
    hint,
}: InputFieldProps) {
    return (
        <div style={{ marginBottom: 16 }}>
            <label
                style={{
                    fontSize: 11,
                    fontFamily: "var(--font-mono)",
                    color: "var(--text-dim)",
                    letterSpacing: "0.07em",
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
                    borderRadius: 7,
                    padding: "10px 13px",
                    color: "var(--text)",
                    fontSize: 14,
                    fontFamily: "var(--font-body)",
                    outline: "none",
                    transition: "border-color 0.15s",
                }}
            />
            {hint && (
                <p
                    style={{
                        fontSize: 11,
                        color: "var(--text-dim)",
                        marginTop: 5,
                    }}
                >
                    {hint}
                </p>
            )}
        </div>
    );
}

// ── SelectField ───────────────────────────────────────────────────────────────

interface SelectFieldProps {
    label: string;
    value: string;
    onChange: (value: string) => void;
    children: ReactNode;
}

export function SelectField({
    label,
    value,
    onChange,
    children,
}: SelectFieldProps) {
    return (
        <div style={{ marginBottom: 16 }}>
            <label
                style={{
                    fontSize: 11,
                    fontFamily: "var(--font-mono)",
                    color: "var(--text-dim)",
                    letterSpacing: "0.07em",
                    textTransform: "uppercase",
                    display: "block",
                    marginBottom: 6,
                }}
            >
                {label}
            </label>
            <select
                value={value}
                onChange={(e) => onChange(e.target.value)}
                style={{
                    width: "100%",
                    background: "var(--bg3)",
                    border: "1px solid var(--border)",
                    borderRadius: 7,
                    color: "var(--text)",
                    padding: "10px 13px",
                    fontSize: 14,
                    fontFamily: "var(--font-body)",
                    outline: "none",
                    cursor: "pointer",
                }}
            >
                {children}
            </select>
        </div>
    );
}

// ── Btn ───────────────────────────────────────────────────────────────────────

type BtnVariant =
    | "primary"
    | "secondary"
    | "danger"
    | "success"
    | "blue"
    | "ghost";

interface BtnProps {
    onClick?: MouseEventHandler<HTMLButtonElement>;
    children: ReactNode;
    variant?: BtnVariant;
    small?: boolean;
    disabled?: boolean;
    full?: boolean;
}

export function Btn({
    onClick,
    children,
    variant = "primary",
    small,
    disabled,
    full,
}: BtnProps) {
    const styles: Record<BtnVariant, CSSProperties> = {
        primary: {
            background: "var(--gold)",
            color: "var(--bg)",
            border: "none",
        },
        secondary: {
            background: "transparent",
            color: "var(--text-mid)",
            border: "1px solid var(--border)",
        },
        danger: {
            background: "var(--red-dim)",
            color: "var(--red)",
            border: "1px solid var(--red)",
        },
        success: {
            background: "var(--green-dim)",
            color: "var(--green)",
            border: "1px solid var(--green)",
        },
        blue: {
            background: "var(--blue-dim)",
            color: "var(--blue)",
            border: "1px solid var(--blue)",
        },
        ghost: {
            background: "transparent",
            color: "var(--text-dim)",
            border: "none",
        },
    };
    return (
        <button
            onClick={onClick}
            disabled={disabled}
            style={{
                ...styles[variant],
                padding: small ? "5px 12px" : "9px 18px",
                borderRadius: 7,
                fontSize: small ? 11 : 13,
                fontFamily: "var(--font-mono)",
                cursor: disabled ? "not-allowed" : "pointer",
                opacity: disabled ? 0.5 : 1,
                transition: "all 0.15s",
                letterSpacing: "0.04em",
                width: full ? "100%" : "auto",
                whiteSpace: "nowrap",
            }}
        >
            {children}
        </button>
    );
}

// ── Divider ───────────────────────────────────────────────────────────────────

interface DividerProps {
    label?: string;
}

export function Divider({ label }: DividerProps) {
    return (
        <div
            style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                margin: "20px 0",
            }}
        >
            <div style={{ flex: 1, height: 1, background: "var(--border)" }} />
            {label && (
                <span
                    style={{
                        fontSize: 11,
                        color: "var(--text-dim)",
                        fontFamily: "var(--font-mono)",
                        letterSpacing: "0.07em",
                        textTransform: "uppercase",
                    }}
                >
                    {label}
                </span>
            )}
            <div style={{ flex: 1, height: 1, background: "var(--border)" }} />
        </div>
    );
}

// ── Card ──────────────────────────────────────────────────────────────────────

interface CardProps {
    children: ReactNode;
    style?: CSSProperties;
}

export function Card({ children, style = {} }: CardProps) {
    return (
        <div
            style={{
                background: "var(--bg2)",
                border: "1px solid var(--border)",
                borderRadius: 12,
                ...style,
            }}
        >
            {children}
        </div>
    );
}

// ── SectionHeader ─────────────────────────────────────────────────────────────

interface SectionHeaderProps {
    title: string;
    subtitle?: string;
    action?: ReactNode;
}

export function SectionHeader({ title, subtitle, action }: SectionHeaderProps) {
    return (
        <div
            style={{
                display: "flex",
                alignItems: "flex-start",
                justifyContent: "space-between",
                marginBottom: 24,
            }}
        >
            <div>
                <h2
                    style={{
                        fontFamily: "var(--font-serif)",
                        fontSize: 24,
                        color: "var(--text)",
                        letterSpacing: "0.01em",
                        lineHeight: 1.2,
                    }}
                >
                    {title}
                </h2>
                {subtitle && (
                    <p
                        style={{
                            fontSize: 13,
                            color: "var(--text-dim)",
                            marginTop: 4,
                        }}
                    >
                        {subtitle}
                    </p>
                )}
            </div>
            {action}
        </div>
    );
}

// ── StatCard ──────────────────────────────────────────────────────────────────

interface StatCardProps {
    label: string;
    value: string | number;
    sub?: string;
    color: string;
    icon: string;
}

export function StatCard({ label, value, sub, color, icon }: StatCardProps) {
    return (
        <div
            style={{
                background: "var(--bg2)",
                border: "1px solid var(--border)",
                borderRadius: 12,
                padding: "20px 24px",
                display: "flex",
                alignItems: "center",
                gap: 16,
                boxShadow: "var(--shadow)",
            }}
        >
            <div
                style={{
                    width: 46,
                    height: 46,
                    borderRadius: 12,
                    background: `${color}18`,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 22,
                    flexShrink: 0,
                }}
            >
                {icon}
            </div>
            <div>
                <div
                    style={{
                        fontSize: 26,
                        fontWeight: 700,
                        color: "var(--text)",
                        fontFamily: "var(--font-mono)",
                        lineHeight: 1,
                    }}
                >
                    {value}
                </div>
                <div
                    style={{
                        fontSize: 12,
                        color: "var(--text-dim)",
                        marginTop: 4,
                        fontFamily: "var(--font-mono)",
                        letterSpacing: "0.05em",
                        textTransform: "uppercase",
                    }}
                >
                    {label}
                </div>
                {sub && (
                    <div
                        style={{
                            fontSize: 11,
                            color,
                            marginTop: 2,
                            fontFamily: "var(--font-mono)",
                        }}
                    >
                        {sub}
                    </div>
                )}
            </div>
        </div>
    );
}