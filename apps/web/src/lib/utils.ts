export const timeAgo = (iso: string): string => {
    const d = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (d < 60) return `${d}s ago`;
    if (d < 3600) return `${Math.floor(d / 60)}m ago`;
    if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
    return `${Math.floor(d / 86400)}d ago`;
};

export const initials = (n?: string): string =>
    n
        ?.split(" ")
        .map((w) => w[0])
        .join("")
        .slice(0, 2)
        .toUpperCase() ?? "?";

export const fmtCurrency = (n?: number): string =>
    `KES ${(n ?? 0).toLocaleString()}`;

export const fmtDate = (iso: string): string =>
    new Date(iso).toLocaleDateString("en-KE", {
        day: "numeric",
        month: "short",
        year: "numeric",
    });

export const cn = (...classes: (string | undefined | null | false)[]): string =>
    classes.filter(Boolean).join(" ");
