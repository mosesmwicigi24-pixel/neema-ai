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
    size?: "xs" | "sm" | "md" | "lg" | "xl" | number;
    className?: string;
}

export function Avatar({
    name,
    size = "md",
    className = "",
}: AvatarProps): React.ReactElement {
    const px = typeof size === "number" ? size : (SIZE_PX[size] ?? 40);

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
            className={`rounded-full flex items-center justify-center ${className}`}
        >
            {initials(name)}
        </div>
    );
}