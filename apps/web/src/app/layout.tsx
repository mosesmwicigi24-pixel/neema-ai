import type { Metadata } from "next";
import { SessionProvider } from "next-auth/react";
import { WsProvider } from "@/lib/websocket";
import Providers from "@/components/providers";
import "./globals.css";

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
                <link
                    href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&display=swap"
                    rel="stylesheet"
                />
            </head>
            <body>
                <Providers>{children}</Providers>
            </body>
        </html>
    );
}