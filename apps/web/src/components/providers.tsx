"use client";

import { SessionProvider } from "next-auth/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WsProvider } from "@/lib/websocket";
import { ReactNode, useState } from "react";

export default function Providers({ children }: { children: ReactNode }) {
    const [queryClient] = useState(() => new QueryClient());

    return (
        <SessionProvider>
            <QueryClientProvider client={queryClient}>
                <WsProvider>{children}</WsProvider>
            </QueryClientProvider>
        </SessionProvider>
    );
}
