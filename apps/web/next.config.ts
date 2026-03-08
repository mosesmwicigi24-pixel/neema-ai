import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',   // lean production image
  experimental: {
    serverActions: {
      allowedOrigins: [process.env.NEXTAUTH_URL ?? 'http://localhost:3000'],
    },
  },
};

export default nextConfig;