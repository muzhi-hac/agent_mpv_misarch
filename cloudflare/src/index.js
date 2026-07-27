import { Container, getContainer } from "@cloudflare/containers";
import { env as bindings } from "cloudflare:workers";

const REQUIRED_RUNTIME_BINDINGS = [
  "MISARCH_GRAPHQL_URL",
  "MISARCH_KEYCLOAK_TOKEN_URL",
  "MISARCH_KEYCLOAK_USERNAME",
  "MISARCH_KEYCLOAK_PASSWORD",
];

export class MisarchGatewayContainer extends Container {
  defaultPort = 8001;
  requiredPorts = [8001];
  sleepAfter = "1m";
  enableInternet = true;
  envVars = {
    HTTP_ADDR: ":8001",
    PUBLIC_BASE_URL: String(bindings.PUBLIC_BASE_URL || ""),
    MISARCH_GRAPHQL_URL: String(bindings.MISARCH_GRAPHQL_URL || ""),
    MISARCH_GRAPHQL_TIMEOUT: String(bindings.MISARCH_GRAPHQL_TIMEOUT || "8s"),
    CORS_ALLOWED_ORIGINS: String(bindings.CORS_ALLOWED_ORIGINS || ""),
    MISARCH_KEYCLOAK_TOKEN_URL: String(bindings.MISARCH_KEYCLOAK_TOKEN_URL || ""),
    MISARCH_KEYCLOAK_CLIENT_ID: String(
      bindings.MISARCH_KEYCLOAK_CLIENT_ID || "frontend",
    ),
    MISARCH_KEYCLOAK_USERNAME: String(bindings.MISARCH_KEYCLOAK_USERNAME || ""),
    MISARCH_KEYCLOAK_PASSWORD: String(bindings.MISARCH_KEYCLOAK_PASSWORD || ""),
  };
}

export default {
  async fetch(request, env) {
    const missing = REQUIRED_RUNTIME_BINDINGS.filter((name) => !env[name]);
    if (missing.length > 0) {
      return Response.json(
        {
          status: "not_configured",
          missing_bindings: missing,
        },
        { status: 503 },
      );
    }

    // A constant name and max_instances=1 make the cost ceiling explicit and
    // also keep the A2A in-memory task store available between preview and
    // confirmation while the singleton is awake.
    const container = getContainer(env.MISARCH_GATEWAY, "singleton");
    const response = await container.fetch(request);
    const forwarded = new Response(response.body, response);
    forwarded.headers.set("X-MiSArch-Runtime", "cloudflare-container-lite");
    return forwarded;
  },
};
