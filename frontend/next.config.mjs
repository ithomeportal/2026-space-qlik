/** @type {import('next').NextConfig} */
const nextConfig = {
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-eval' 'unsafe-inline' https://mb01txe2h9rovgh.us.qlikcloud.com https://cdn.qlikcloud.com",
              "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.qlikcloud.com",
              "font-src 'self' https://fonts.gstatic.com https://cdn.qlikcloud.com",
              "img-src 'self' data: blob: https://mb01txe2h9rovgh.us.qlikcloud.com https://cdn.qlikcloud.com",
              "frame-src https://mb01txe2h9rovgh.us.qlikcloud.com https://cdn.qlikcloud.com",
              "connect-src 'self' https://mb01txe2h9rovgh.us.qlikcloud.com wss://mb01txe2h9rovgh.us.qlikcloud.com https://cdn.qlikcloud.com",
              "frame-ancestors 'self'",
            ].join("; "),
          },
          {
            key: "X-Frame-Options",
            value: "SAMEORIGIN",
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
        ],
      },
    ]
  },
}

export default nextConfig
