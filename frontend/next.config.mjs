/** @type {import('next').NextConfig} */
const BASE_CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-eval' 'unsafe-inline' https://cdn.jsdelivr.net",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com",
  "img-src 'self' data: blob:",
  "frame-src 'self'",
  "connect-src 'self' https://two026-space-qlik-back.onrender.com https://cdn.jsdelivr.net",
  "worker-src 'self' blob:",
  "child-src 'self' blob:",
]

const nextConfig = {
  async headers() {
    return [
      {
        // Everything EXCEPT the floor-TV displays: never framed by another site.
        source: "/((?!public/).*)",
        headers: [
          {
            key: "Content-Security-Policy",
            value: [...BASE_CSP, "frame-ancestors 'self'"].join("; "),
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
      {
        // Floor-TV displays (2026-11-02): read-only, key-gated, and the TV
        // signage provider is not chosen yet — it may show the page inside its
        // own frame, so ANY origin may embed /public/* (no X-Frame-Options).
        // The key rides in the URL ⇒ never leak it through a Referer, never
        // let a search engine index it, never cache it in a shared cache.
        source: "/public/:path*",
        headers: [
          {
            key: "Content-Security-Policy",
            value: [...BASE_CSP, "frame-ancestors *"].join("; "),
          },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
          { key: "Cache-Control", value: "no-store" },
        ],
      },
    ]
  },
}

export default nextConfig
