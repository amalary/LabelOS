import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@label-os/ui"],
  logging: {
    incomingRequests: {
      // Callback codes and invitation tokens are credentials, including in dev.
      ignore: [/\/api\/auth\//, /\/join\//, /\/invites\//, /\/oauth\//],
    },
  },
};

export default nextConfig;
