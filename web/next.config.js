/** @type {import("next").NextConfig} */
module.exports = {
  reactStrictMode: false,
  output: "standalone",
  async rewrites() {
    const apiBase = process.env.MAILHUB_API_INTERNAL_URL || "http://127.0.0.1:8024";
    return [
      { source: "/api/:path*", destination: `${apiBase}/api/:path*` },
    ];
  },
};
