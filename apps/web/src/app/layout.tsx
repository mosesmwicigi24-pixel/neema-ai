import type { Metadata, Viewport } from "next";
import Providers from "@/components/providers";
import "./globals.css";

// The mobile composer contract: on browsers that support it (Android Chrome),
// the layout itself shrinks when the keyboard opens, so the reply box lands
// above the keyboard natively; on iOS Safari (which ignores interactiveWidget)
// the visualViewport lift in ConversationsView translates it up instead.
export const viewport: Viewport = {
    width: "device-width",
    initialScale: 1,
    viewportFit: "cover",
    interactiveWidget: "resizes-content",
};

export const metadata: Metadata = {
    title: {
        default: "Neema — Bethany House",
        template: "%s | Neema",
    },
    description: "AI-powered customer engagement platform for Bethany House",
    icons: {
        icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='8' fill='%23589b31'/><path d='M8 16c0-4.4 3.6-8 8-8s8 3.6 8 8c0 2.8-1.4 5.2-3.6 6.7l-1.1 3.3H12.7l-1.1-3.3A8 8 0 0 1 8 16z' fill='white'/></svg>",
    },
};

export default function RootLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <html lang="en" suppressHydrationWarning>
            <head>
                <link rel="preconnect" href="https://fonts.googleapis.com" />
                <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
                <link
                    href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&display=swap"
                    rel="stylesheet"
                />
            </head>
            <body>
                <Providers>{children}</Providers>
            </body>
        </html>
    );
}