import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      // Images still served by the current nuruplace.org CMS. Remove once
      // every asset has been migrated into /public.
      { protocol: "https", hostname: "nuruplace.org" },
    ],
  },
};

export default nextConfig;
