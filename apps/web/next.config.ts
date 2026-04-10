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
};

export default nextConfig;