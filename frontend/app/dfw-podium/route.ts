export async function GET() {
  const html = `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta http-equiv="X-UA-Compatible" content="ie=edge" />
    <meta http-equiv="refresh" content="3600" />
    <style>
      * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
      }
      body,
      html {
        width: 100%;
        height: 100%;
        overflow: hidden;
        background-color: #000;
      }
      .dashboard-wrapper {
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
    <script
      crossorigin="anonymous"
      type="application/javascript"
      src="https://cdn.jsdelivr.net/npm/@qlik/embed-web-components@1/dist/index.min.js"
      data-host="https://mb01txe2h9rovgh.us.qlikcloud.com"
      data-client-id="019d446c6b163a8dfc7c1b72220d5833"
      data-redirect-uri="https://space.unilinkportal.com/dfw-podium"
      data-auto-redirect="true"
      data-access-token-storage="session"
    ></script>
  </head>
  <body>
    <div class="dashboard-wrapper">
      <qlik-embed
        ui="classic/app"
        app-id="87278082-0346-4d41-8b2c-ac658a8d5a1f"
        sheet-id="f56141e7-004e-42cb-8507-57196cb77d13"
        theme="Sense Horizon"
        iframe="true"
        preview="true"
      ></qlik-embed>
    </div>
  </body>
</html>`

  return new Response(html, {
    headers: { "Content-Type": "text/html" },
  })
}
