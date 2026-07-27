import { randomUUID } from "node:crypto";

const baseURL = String(
  process.env.CLOUDFLARE_TEST_BASE_URL ||
    "https://misarch-store-agent.young-math-5a26.workers.dev",
).replace(/\/+$/, "");
const bearerToken = String(process.env.MISARCH_A2A_BEARER_TOKEN || "");
if (!bearerToken) {
  throw new Error("MISARCH_A2A_BEARER_TOKEN is required for the cloud smoke test");
}
const authorization = `Bearer ${bearerToken}`;

async function fetchChecked(path, expectedStatus = 200) {
  const started = performance.now();
  const response = await fetch(`${baseURL}${path}`, {
    headers: { Accept: "application/json", Authorization: authorization },
    signal: AbortSignal.timeout(90_000),
  });
  const text = await response.text();
  if (response.status !== expectedStatus) {
    throw new Error(
      `${path} returned ${response.status}, want ${expectedStatus}: ${text.slice(0, 500)}`,
    );
  }
  return {
    response,
    body: text ? JSON.parse(text) : {},
    duration_ms: Number((performance.now() - started).toFixed(1)),
  };
}

function jsonrpcInterface(card) {
  const found = (card.supportedInterfaces || []).find(
    (item) =>
      String(item.protocolBinding || "").toUpperCase() === "JSONRPC" &&
      String(item.protocolVersion || "").startsWith("1."),
  );
  if (!found?.url) {
    throw new Error("Agent Card has no A2A 1.x JSON-RPC interface");
  }
  if (!String(found.url).startsWith(`${baseURL}/a2a`)) {
    throw new Error(`Agent Card advertises unexpected public URL: ${found.url}`);
  }
  return found;
}

async function browse(card) {
  const iface = jsonrpcInterface(card);
  const requestID = `cloud-smoke-${randomUUID()}`;
  const response = await fetch(iface.url, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "A2A-Version": iface.protocolVersion,
      Authorization: authorization,
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: requestID,
      method: "SendMessage",
      params: {
        message: {
          messageId: randomUUID(),
          role: "ROLE_USER",
          parts: [
            {
              data: {
                skill: "browse",
                input: { query: "cup", top_k: 5 },
              },
            },
          ],
        },
      },
    }),
    signal: AbortSignal.timeout(90_000),
  });
  const body = await response.json();
  if (!response.ok || body.error) {
    throw new Error(`A2A browse failed: ${JSON.stringify(body).slice(0, 700)}`);
  }
  const state = body?.result?.task?.status?.state;
  if (state !== "TASK_STATE_COMPLETED") {
    throw new Error(`A2A browse state=${state}, want TASK_STATE_COMPLETED`);
  }
  return { status: response.status, state };
}

const health = await fetchChecked("/healthz");
const readiness = await fetchChecked("/readyz");
const cardResult = await fetchChecked("/.well-known/agent-card.json");
const purchaseSkill = (cardResult.body.skills || []).find(
  (skill) => skill.id === "purchase",
);
if (!purchaseSkill) {
  throw new Error("Agent Card is missing purchase skill");
}
const browseResult = await browse(cardResult.body);

console.log(
  JSON.stringify(
    {
      success: true,
      base_url: baseURL,
      health_ms: health.duration_ms,
      readiness_ms: readiness.duration_ms,
      card_ms: cardResult.duration_ms,
      browse: browseResult,
    },
    null,
    2,
  ),
);
