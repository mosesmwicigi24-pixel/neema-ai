import React from "react";

// Render WhatsApp-style inline formatting so the inbox shows text the same way
// WhatsApp does. Supports *bold* (and legacy Markdown **bold**), _italics_,
// ~strikethrough~, and `monospace`. Newlines are left intact for the caller's
// `whitespace-pre-wrap` to render. This is display-only — the stored text is
// untouched.
//
// A capturing split keeps the delimiters, so `parts` alternates plain / marked
// segments. The **bold** alternative is listed first so `**x**` wins over `*x*`
// at the same position.
const TOKEN = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|_[^_\n]+_|~[^~\n]+~|`[^`\n]+`)/g;

export function formatWa(text: string | null | undefined): React.ReactNode {
    if (!text) return text ?? null;
    const parts = text.split(TOKEN);
    return parts.map((part, i) => {
        if (!part) return null;
        const inner = part.slice(1, -1);
        if (part.startsWith("**") && part.endsWith("**") && part.length > 4)
            return <strong key={i}>{part.slice(2, -2)}</strong>;
        if (part.startsWith("*") && part.endsWith("*") && part.length > 2)
            return <strong key={i}>{inner}</strong>;
        if (part.startsWith("_") && part.endsWith("_") && part.length > 2)
            return <em key={i}>{inner}</em>;
        if (part.startsWith("~") && part.endsWith("~") && part.length > 2)
            return <s key={i}>{inner}</s>;
        if (part.startsWith("`") && part.endsWith("`") && part.length > 2)
            return (
                <code key={i} className="font-mono text-[0.95em]">
                    {inner}
                </code>
            );
        return <React.Fragment key={i}>{part}</React.Fragment>;
    });
}
