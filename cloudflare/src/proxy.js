export default {
  async fetch(request, env) {
    const missing = ["ORIGIN_URL", "TEST_GATEWAY_TOKEN"].filter(
      (name) => !env[name],
    );
    if (missing.length > 0) {
      return Response.json(
        { status: "not_configured", missing_bindings: missing },
        { status: 503 },
      );
    }

    const authorization = request.headers.get("Authorization") || "";
    if (authorization !== `Bearer ${env.TEST_GATEWAY_TOKEN}`) {
      return Response.json({ status: "unauthorized" }, { status: 401 });
    }

    let origin;
    try {
      origin = new URL(env.ORIGIN_URL);
    } catch {
      return Response.json({ status: "invalid_origin" }, { status: 503 });
    }
    if (origin.protocol !== "https:") {
      return Response.json(
        { status: "invalid_origin", requirement: "https" },
        { status: 503 },
      );
    }

    const incoming = new URL(request.url);
    const target = new URL(incoming.pathname + incoming.search, origin);
    const headers = new Headers(request.headers);
    headers.set("X-Forwarded-Host", incoming.host);
    headers.set("X-Forwarded-Proto", "https");

    const upstream = await fetch(
      new Request(target, {
        method: request.method,
        headers,
        body: request.body,
        redirect: "manual",
      }),
    );
    const response = new Response(upstream.body, upstream);
    response.headers.set("X-MiSArch-Runtime", "cloudflare-free-proxy");
    return response;
  },
};
