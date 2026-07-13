"use client";

import { SessionProvider } from "next-auth/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WsProvider } from "@/lib/websocket";
import { WhatsAppSoftphone } from "@/components/WhatsAppSoftphone";
import { ReactNode, useState } from "react";

export default function Providers({ children }: { children: ReactNode }) {
    const [queryClient] = useState(() => new QueryClient());

    return (
        <SessionProvider>
            <QueryClientProvider client={queryClient}>
                <WsProvider>
                    {children}
                    {/* Global — rings anywhere in the dashboard on an inbound WhatsApp call. */}
                    <WhatsAppSoftphone />
                </WsProvider>
            </QueryClientProvider>
        </SessionProvider>
    );
}
