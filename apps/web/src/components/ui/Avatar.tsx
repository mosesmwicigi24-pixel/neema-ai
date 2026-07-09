import React from "react";
import { initials } from "@/lib/utils";

// Single neutral avatar colour aligned with the UI theme.
// Light stone-green background with dark green initials — visible against
// both the default white list background and the selected-row highlight
// (#f3f9ec) because the tint and border keep it distinct in both states.
const AVATAR_BG     = "rgb(245, 246, 243)";
const AVATAR_TEXT   = "#3a5c28";
const AVATAR_BORDER = "1px solid #dde8d5";

const SIZE_PX: Record<string, number> = {
    xs: 24, sm: 32, md: 40, lg: 48, xl: 64,
};

interface AvatarProps {
    name?: string;
    // Optional profile photo (e.g. a Messenger/IG avatar). Meta pic URLs can
    // expire, so on any load error we fall back to the initials automatically.
    src?: string | null;
    size?: "xs" | "sm" | "md" | "lg" | "xl" | number;
    className?: string;
}

export function Avatar({
    name,
    src,
    size = "md",
    className = "",
}: AvatarProps): React.ReactElement {
    const px = typeof size === "number" ? size : (SIZE_PX[size] ?? 40);
    const [broken, setBroken] = React.useState(false);
    // Reset the error state when the photo changes (e.g. switching conversations).
    React.useEffect(() => setBroken(false), [src]);
    const showImg = Boolean(src) && !broken;

    return (
        <div
            style={{
                width:           px,
                height:          px,
                fontSize:        px * 0.36,
                backgroundColor: AVATAR_BG,
                color:           AVATAR_TEXT,
                border:          AVATAR_BORDER,
                fontWeight:      700,
                letterSpacing:   "0.02em",
                flexShrink:      0,
            }}
            className={`rounded-full flex items-center justify-center overflow-hidden ${className}`}
        >
            {showImg ? (
                <img
                    src={src as string}
                    alt={name || ""}
                    onError={() => setBroken(true)}
                    style={{ width: "100%", height: "100%", objectFit: "cover" }}
                />
            ) : (
                initials(name)
            )}
        </div>
    );
}