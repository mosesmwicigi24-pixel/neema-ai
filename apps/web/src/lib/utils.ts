/**
 * Returns a human-readable display name for a contact.
 * If no real name is available, formats the phone/wa_id instead of
 * showing a raw digit string.
 *
 * Usage:
 *   displayName(conv.name, conv.wa_id)         → "John Doe" or "+254 712 345 678"
 *   displayName(order.contact_name, order.contact_phone)
 */
export function displayName(
    name: string | null | undefined,
    phoneOrId: string | null | undefined,
): string {
    if (name && name.trim()) return name.trim();
    return formatPhone(phoneOrId) || "Unknown";
}

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

/**
 * Formats a raw phone string (E.164, digits-only, or partial) into a
 * human-readable international format, respecting each country's convention.
 *
 * Examples:
 *   "254712345678"  → "+254 712 345 678"   (Kenya)
 *   "+254712345678" → "+254 712 345 678"   (Kenya)
 *   "447911123456"  → "+44 7911 123456"    (UK)
 *   "12025551234"   → "+1 (202) 555-1234"  (US)
 *   "33612345678"   → "+33 6 12 34 56 78"  (France)
 *   "49301234567"   → "+49 30 1234567"     (Germany)
 *   "27821234567"   → "+27 82 123 4567"    (South Africa)
 *   "919876543210"  → "+91 98765 43210"    (India)
 *
 * Falls back gracefully: if the number can't be parsed it still prepends
 * "+" and groups digits in blocks of 3 for readability.
 */
export function formatPhone(raw: string | null | undefined): string {
    if (!raw) return "";

    // Normalise to digits only, then restore leading +
    const cleaned = String(raw).trim();
    const hasPlus = cleaned.startsWith("+");
    const digits = cleaned.replace(/\D/g, "");

    if (!digits) return cleaned;

    // A real phone is at most 15 digits (E.164). Meta PSIDs/IGSIDs are 16-18
    // digits — phone-formatting them invents a fake country ("+257 522…" from a
    // Messenger id). Show those as a plain id, never as a phone.
    if (digits.length > 15) return "Messenger ID " + cleaned.replace(/^\+/, "");

    // Ensure we always work with the full E.164 digit string (no leading +)
    const e164Digits = digits;

    // Country-code → formatter map.
    // Each entry: [countryCodeLength, formatterFn]
    // The formatter receives the subscriber digits (after the country code).
    type Fmt = (cc: string, sub: string) => string;

    const rules: Array<{ cc: string; fmt: Fmt }> = [
        // ── North America (NANP) +1 ───────────────────────────────────────
        {
            cc: "1",
            fmt: (cc, s) =>
                s.length === 10
                    ? `+${cc} (${s.slice(0, 3)}) ${s.slice(3, 6)}-${s.slice(6)}`
                    : `+${cc} ${s}`,
        },
        // ── Kenya +254 ────────────────────────────────────────────────────
        {
            cc: "254",
            fmt: (cc, s) =>
                s.length === 9
                    ? `+${cc} ${s.slice(0, 3)} ${s.slice(3, 6)} ${s.slice(6)}`
                    : `+${cc} ${s}`,
        },
        // ── South Africa +27 ──────────────────────────────────────────────
        {
            cc: "27",
            fmt: (cc, s) =>
                s.length === 9
                    ? `+${cc} ${s.slice(0, 2)} ${s.slice(2, 5)} ${s.slice(5)}`
                    : `+${cc} ${s}`,
        },
        // ── Nigeria +234 ──────────────────────────────────────────────────
        {
            cc: "234",
            fmt: (cc, s) =>
                s.length === 10
                    ? `+${cc} ${s.slice(0, 3)} ${s.slice(3, 6)} ${s.slice(6)}`
                    : `+${cc} ${s}`,
        },
        // ── UK +44 ────────────────────────────────────────────────────────
        {
            cc: "44",
            fmt: (cc, s) =>
                s.length === 10
                    ? `+${cc} ${s.slice(0, 4)} ${s.slice(4)}`
                    : `+${cc} ${s}`,
        },
        // ── Germany +49 ───────────────────────────────────────────────────
        {
            cc: "49",
            fmt: (cc, s) =>
                s.length >= 9
                    ? `+${cc} ${s.slice(0, 3)} ${s.slice(3, 7)}${s.length > 7 ? " " + s.slice(7) : ""}`
                    : `+${cc} ${s}`,
        },
        // ── France +33 ────────────────────────────────────────────────────
        {
            cc: "33",
            fmt: (cc, s) =>
                s.length === 9
                    ? `+${cc} ${s.slice(0, 1)} ${s.slice(1, 3)} ${s.slice(3, 5)} ${s.slice(5, 7)} ${s.slice(7)}`
                    : `+${cc} ${s}`,
        },
        // ── India +91 ─────────────────────────────────────────────────────
        {
            cc: "91",
            fmt: (cc, s) =>
                s.length === 10
                    ? `+${cc} ${s.slice(0, 5)} ${s.slice(5)}`
                    : `+${cc} ${s}`,
        },
        // ── UAE +971 ──────────────────────────────────────────────────────
        {
            cc: "971",
            fmt: (cc, s) =>
                s.length === 9
                    ? `+${cc} ${s.slice(0, 2)} ${s.slice(2, 5)} ${s.slice(5)}`
                    : `+${cc} ${s}`,
        },
        // ── Tanzania +255 ─────────────────────────────────────────────────
        {
            cc: "255",
            fmt: (cc, s) =>
                s.length === 9
                    ? `+${cc} ${s.slice(0, 3)} ${s.slice(3, 6)} ${s.slice(6)}`
                    : `+${cc} ${s}`,
        },
        // ── Uganda +256 ───────────────────────────────────────────────────
        {
            cc: "256",
            fmt: (cc, s) =>
                s.length === 9
                    ? `+${cc} ${s.slice(0, 3)} ${s.slice(3, 6)} ${s.slice(6)}`
                    : `+${cc} ${s}`,
        },
        // ── Ethiopia +251 ─────────────────────────────────────────────────
        {
            cc: "251",
            fmt: (cc, s) =>
                s.length === 9
                    ? `+${cc} ${s.slice(0, 2)} ${s.slice(2, 5)} ${s.slice(5)}`
                    : `+${cc} ${s}`,
        },
        // ── Ghana +233 ────────────────────────────────────────────────────
        {
            cc: "233",
            fmt: (cc, s) =>
                s.length === 9
                    ? `+${cc} ${s.slice(0, 2)} ${s.slice(2, 5)} ${s.slice(5)}`
                    : `+${cc} ${s}`,
        },
        // ── Rwanda +250 ───────────────────────────────────────────────────
        {
            cc: "250",
            fmt: (cc, s) =>
                s.length === 9
                    ? `+${cc} ${s.slice(0, 3)} ${s.slice(3, 6)} ${s.slice(6)}`
                    : `+${cc} ${s}`,
        },
        // ── Australia +61 ─────────────────────────────────────────────────
        {
            cc: "61",
            fmt: (cc, s) =>
                s.length === 9
                    ? `+${cc} ${s.slice(0, 1)} ${s.slice(1, 5)} ${s.slice(5)}`
                    : `+${cc} ${s}`,
        },
    ];

    // Try matching longest country code first (3-digit, 2-digit, 1-digit)
    for (const prefixLen of [3, 2, 1]) {
        const cc = e164Digits.slice(0, prefixLen);
        const rule = rules.find((r) => r.cc === cc);
        if (rule) {
            const sub = e164Digits.slice(prefixLen);
            return rule.fmt(cc, sub);
        }
    }

    // ── Generic fallback: +[cc?] then groups of 3 ────────────────────────────
    const withPlus = hasPlus ? "+" + digits : digits;
    // Group remaining digits in blocks of 3 for readability
    const grouped = digits.replace(/(\d{3})(?=\d)/g, "$1 ");
    return `+${grouped}`;
}