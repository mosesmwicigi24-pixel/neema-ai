import type { NextConfig } from "next";

const nextConfig: NextConfig = {
    output: "standalone",
    devIndicators: false,
    experimental: {
        serverActions: {
            allowedOrigins: [
                process.env.NEXTAUTH_URL ?? "http://localhost:3000",
            ],
        },
    },
    // Disable the dev error overlay
    onDemandEntries: {
        maxInactiveAge: 0,
    },
};

export default nextConfig;