"use client";

import { SessionProvider } from "next-auth/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WsProvider } from "@/lib/websocket";
import { CallProvider } from "@/lib/callContext";
import { ReactNode, useState } from "react";

export default function Providers({ children }: { children: ReactNode }) {
    const [queryClient] = useState(() => new QueryClient());

    return (
        <SessionProvider>
            <QueryClientProvider client={queryClient}>
                <WsProvider>
                    {/* Call state is app-global; the call CARD renders inside the
                        dashboard content area (CallStage) so the sidebar stays visible. */}
                    <CallProvider>{children}</CallProvider>
                </WsProvider>
            </QueryClientProvider>
        </SessionProvider>
    );
}
