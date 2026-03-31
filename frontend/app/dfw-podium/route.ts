const BACKEND_URL = process.env.BACKEND_URL ?? "https://two026-space-qlik-back.onrender.com"
const TV_SECRET = process.env.TV_SECRET ?? ""
const TENANT = "https://mb01txe2h9rovgh.us.qlikcloud.com"
const WEB_INTEGRATION_ID = "UcOYHRHZf7W4ydusUB3cJPin3HHOPnit"

export async function GET() {
  const html = `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta http-equiv="refresh" content="3600" />
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      body, html {
        width: 100%;
        height: 100%;
        overflow: hidden;
        background-color: #000;
        color: #fff;
        font-family: sans-serif;
      }
      #status {
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        text-align: center;
        font-size: 18px;
        z-index: 10;
      }
      #dashboard {
        width: 100vw;
        height: 100vh;
        position: relative;
      }
      qlik-embed {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
      }
    </style>
    <title>Podium DFW Dashboard - TV Display</title>
  </head>
  <body>
    <div id="status">Loading dashboard...</div>
    <div id="dashboard" style="display:none;"></div>

    <script>
      (async function() {
        const TENANT = "${TENANT}";
        const WEB_INTEGRATION_ID = "${WEB_INTEGRATION_ID}";
        const BACKEND = "${BACKEND_URL}";
        const SECRET = "${TV_SECRET}";

        const status = document.getElementById("status");

        try {
          // 1. Get viewer JWT from backend
          status.textContent = "Authenticating...";
          const tokenRes = await fetch(BACKEND + "/api/qlik/tv-token?secret=" + encodeURIComponent(SECRET), {
            method: "POST",
          });
          if (!tokenRes.ok) throw new Error("Token request failed: " + tokenRes.status);
          const tokenData = await tokenRes.json();
          const jwt = tokenData.data.token;

          // 2. Exchange JWT for Qlik session cookie
          status.textContent = "Establishing session...";
          const sessionRes = await fetch(
            TENANT + "/login/jwt-session?qlik-web-integration-id=" + WEB_INTEGRATION_ID,
            {
              method: "POST",
              credentials: "include",
              headers: {
                "Authorization": "Bearer " + jwt,
                "qlik-web-integration-id": WEB_INTEGRATION_ID,
              },
            }
          );

          if (!sessionRes.ok) {
            console.warn("Session exchange returned " + sessionRes.status);
          }

          // 3. Load qlik-embed web components and render
          status.textContent = "Loading visualization...";
          const script = document.createElement("script");
          script.src = "https://cdn.jsdelivr.net/npm/@qlik/embed-web-components@1/dist/index.min.js";
          script.setAttribute("data-host", TENANT);
          script.setAttribute("data-auth-type", "cookie");
          script.setAttribute("data-web-integration-id", WEB_INTEGRATION_ID);
          document.head.appendChild(script);

          script.onload = function() {
            const embed = document.createElement("qlik-embed");
            embed.setAttribute("ui", "classic/app");
            embed.setAttribute("app-id", "87278082-0346-4d41-8b2c-ac658a8d5a1f");
            embed.setAttribute("sheet-id", "f56141e7-004e-42cb-8507-57196cb77d13");
            embed.setAttribute("theme", "Sense Horizon");
            embed.setAttribute("host", TENANT);
            embed.setAttribute("auth-type", "cookie");
            embed.setAttribute("web-integration-id", WEB_INTEGRATION_ID);
            embed.style.width = "100%";
            embed.style.height = "100%";

            document.getElementById("dashboard").style.display = "block";
            document.getElementById("dashboard").appendChild(embed);
            document.getElementById("status").style.display = "none";
          };

        } catch (err) {
          status.textContent = "Error: " + err.message;
          console.error(err);
          // Retry in 30 seconds
          setTimeout(function() { location.reload(); }, 30000);
        }
      })();
    </script>
  </body>
</html>`

  return new Response(html, {
    headers: {
      "Content-Type": "text/html",
      "Cache-Control": "no-store",
    },
  })
}
