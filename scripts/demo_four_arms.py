#!/usr/bin/env python3
"""Live, deterministic four-arm terminal demo for video recording."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any

from scripts.agent_a2a_loop import A2AClient
from scripts.agent_gcp_baseline_test import (
    LIST_PRODUCTS_QUERY,
    bearer_headers,
    graphql_request,
    keycloak_token,
)
from scripts.agent_mcp_loop import MCPClient
from scripts.openai_demo_agent import run_openai_agent


DEFAULT_QUESTION = "Help me choose an inexpensive cup"
PROFILE_MATERIAL = "stainless steel"
CUP_WORDS = ("cup", "bottle", "mug", "水杯")
QUERY_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "affordable",
        "buy",
        "cheap",
        "choose",
        "find",
        "for",
        "get",
        "help",
        "i",
        "inexpensive",
        "looking",
        "me",
        "my",
        "need",
        "please",
        "purchase",
        "recommend",
        "show",
        "some",
        "the",
        "to",
        "want",
        "would",
    }
)

ARM_META = {
    "A": {
        "title": "A · Direct GraphQL",
        "color": "\033[36m",
        "path": "User → native GraphQL → MiSArch",
        "protocol": "GraphQL",
    },
    "B": {
        "title": "B · MCP",
        "color": "\033[33m",
        "path": "User → MCP tools/list + tools/call → MiSArch",
        "protocol": "MCP",
    },
    "D": {
        "title": "D · MCP + Structured Profile",
        "color": "\033[35m",
        "path": "User + local profile → MCP → MiSArch",
        "protocol": "MCP + Structured Profile",
    },
    "C": {
        "title": "C · A2A",
        "color": "\033[32m",
        "path": "Butler → Agent Card → A2A Store Agent → MiSArch",
        "protocol": "A2A",
    },
}

ARM_AGENT_POLICIES = {
    "A": {
        "role": "GraphQL schema explorer",
        "policy": (
            "Expose the raw matching candidates and their prices. Do not make a "
            "single recommendation: selected_name must be an empty string."
        ),
        "public_rules": [
            "Display cup candidates and prices returned by GraphQL",
            "Apply no personal preference and make no single recommendation",
        ],
        "allow_no_selection": True,
        "agent_profile_fields": 0,
    },
    "B": {
        "role": "MCP budget buyer",
        "policy": (
            "Choose exactly one product using lowest price as the only ranking "
            "criterion. Ties are resolved alphabetically."
        ),
        "public_rules": [
            "Compare candidate prices only",
            "Select the lowest price; break ties alphabetically",
        ],
        "allow_no_selection": False,
        "agent_profile_fields": 0,
    },
    "D": {
        "role": "MCP structured-profile buyer",
        "policy": (
            "The local structured profile says preferred material is stainless "
            "steel. Choose the cheapest stainless-steel candidate even when a "
            "different material is cheaper."
        ),
        "public_rules": [
            "Apply the local structured preference: stainless steel",
            "Keep stainless-steel candidates first, then choose their lowest price",
        ],
        "allow_no_selection": False,
        "agent_profile_fields": 1,
    },
    "C": {
        "role": "Privacy-aware A2A butler",
        "policy": (
            "Keep private preferences out of the A2A Store Agent request. Locally "
            "avoid plastic and premium products above EUR 20; choose the cheapest "
            "reusable non-plastic candidate, preferring borosilicate glass."
        ),
        "public_rules": [
            "Keep preferences inside the Butler; do not send them to the store",
            "Exclude plastic products and products above EUR 20",
            "Prefer borosilicate glass among eligible candidates, then compare price",
        ],
        "allow_no_selection": False,
        "agent_profile_fields": 2,
    },
}


def cup_candidates(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        product
        for product in products
        if any(word in str(product.get("name", "")).lower() for word in CUP_WORDS)
    ]


def normalize_catalog_query(token: str) -> str:
    token = token.lower()
    if token.endswith("ies") and len(token) > 3:
        return token[:-3] + "y"
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def extract_catalog_query(question: str) -> str:
    """Extract a compact product noun for the deterministic retrieval layer."""
    tokens = re.findall(r"[a-z0-9]+", question.lower())
    meaningful = [
        token
        for token in tokens
        if token not in QUERY_STOP_WORDS and not token.isdigit()
    ]
    return normalize_catalog_query(meaningful[-1]) if meaningful else "product"


def query_candidates(
    products: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    normalized_query = normalize_catalog_query(query)
    matches: list[dict[str, Any]] = []
    for product in products:
        tokens = [
            normalize_catalog_query(token)
            for token in re.findall(
                r"[a-z0-9]+",
                str(product.get("name") or "").lower(),
            )
        ]
        if any(
            token.startswith(normalized_query)
            or normalized_query.startswith(token)
            for token in tokens
        ):
            matches.append(product)
    return matches


def choose_cheapest(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        raise RuntimeError("No cup candidates are available")
    return min(candidates, key=lambda item: int(item["retail_price_cents"]))


def choose_profiled(
    candidates: list[dict[str, Any]],
    material: str,
) -> dict[str, Any]:
    if not candidates:
        raise RuntimeError("No cup candidates are available")
    material = material.lower()
    return sorted(
        candidates,
        key=lambda item: (
            material not in str(item.get("name", "")).lower(),
            int(item["retail_price_cents"]),
        ),
    )[0]


def normalize_graphql_products(response: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = ((response.get("data") or {}).get("products") or {}).get("nodes") or []
    products: list[dict[str, Any]] = []
    for node in nodes:
        variant = node.get("defaultVariant") or {}
        version = variant.get("currentVersion") or {}
        products.append(
            {
                "product_id": node.get("id"),
                "variant_id": variant.get("id"),
                "name": version.get("name"),
                "retail_price_cents": int(version.get("retailPrice") or 0),
                "currency": "EUR",
            }
        )
    return products


def local_graphql_products() -> list[dict[str, Any]]:
    auth_args = argparse.Namespace(
        keycloak_token_url=os.environ.get(
            "MISARCH_KEYCLOAK_TOKEN_URL",
            "http://127.0.0.1:8081/keycloak/realms/Misarch/protocol/openid-connect/token",
        ),
        keycloak_client_id=os.environ.get("MISARCH_KEYCLOAK_CLIENT_ID", "frontend"),
        keycloak_username=os.environ.get("MISARCH_KEYCLOAK_USERNAME", "gatling"),
        keycloak_password=os.environ.get("MISARCH_KEYCLOAK_PASSWORD", "123"),
        keycloak_grant_type="password",
    )
    token = keycloak_token(auth_args)
    response = graphql_request(
        os.environ.get("MISARCH_GRAPHQL_URL", "http://127.0.0.1:8080/graphql"),
        LIST_PRODUCTS_QUERY,
        {"first": 100},
        bearer_headers(token),
    )
    return normalize_graphql_products(response)


def mcp_products(query: str) -> tuple[
    list[dict[str, Any]],
    list[str],
    list[dict[str, str]],
]:
    client = MCPClient(
        os.environ.get("MISARCH_MCP_URL", "http://127.0.0.1:8001/mcp")
    )
    client.connect()
    tools = client.list_tools()
    result = client.call_tool("list_products", {"top_k": 100})
    products = result.get("products") or []
    tool_names = [
        str(tool.get("name")) for tool in tools if tool.get("name")
    ]
    server_name = str((client.server_info or {}).get("name") or "MiSArch MCP Gateway")
    session_hint = (
        f"{client.session_id[:8]}…"
        if isinstance(client.session_id, str) and len(client.session_id) > 8
        else str(client.session_id or "assigned")
    )
    protocol_trace = [
        {
            "from": "MCP Client",
            "to": "MCP Gateway",
            "action": "initialize",
            "detail": (
                f"JSON-RPC 2.0; protocolVersion={client.protocol_version}; "
                "clientInfo=misarch-autonomous-mcp-agent"
            ),
        },
        {
            "from": "MCP Gateway",
            "to": "MCP Client",
            "action": "initialize result",
            "detail": f"serverInfo={server_name}; Mcp-Session-Id={session_hint}",
        },
        {
            "from": "MCP Client",
            "to": "MCP Gateway",
            "action": "tool discovery",
            "detail": f"tools/list → {tool_names}",
        },
        {
            "from": "MCP Client",
            "to": "MCP Gateway",
            "action": "tool invocation",
            "detail": "tools/call name=list_products arguments={top_k:100}",
        },
        {
            "from": "MCP Gateway",
            "to": "MiSArch",
            "action": "catalog adapter call",
            "detail": "Translate the MCP tool request into a MiSArch catalog query",
        },
        {
            "from": "MCP Gateway",
            "to": "MCP Client",
            "action": "tool result",
            "detail": (
                f"Structured result contains {len(products)} products; "
                f"client-side query filter={query}"
            ),
        },
    ]
    normalized_products = [
        item for item in products if isinstance(item, dict)
    ]
    return query_candidates(normalized_products, query), tool_names, protocol_trace


def a2a_products(query: str) -> tuple[
    list[dict[str, Any]],
    list[str],
    list[dict[str, str]],
]:
    base_url = os.environ.get("MISARCH_A2A_URL", "http://127.0.0.1:8001")
    client = A2AClient(base_url)
    card = client.fetch_card()
    # The running gateway may advertise its Cloudflare URL for public tests.
    # This recording is intentionally local and read-only, so keep the
    # discovered card/skills but route its JSON-RPC interface to the same local
    # gateway that served the card.
    if base_url.startswith(("http://127.0.0.1", "http://localhost")):
        for interface in card.get("supportedInterfaces", []):
            if (
                isinstance(interface, dict)
                and str(interface.get("protocolBinding", "")).upper() == "JSONRPC"
            ):
                interface["url"] = base_url.rstrip("/") + "/a2a"
    response = client.send_task(
        "video-demo-browse",
        "browse",
        {"query": query, "top_k": 10, "constraints": {}},
    )
    if response.get("state") != "completed":
        raise RuntimeError(
            f"A2A browse did not complete: "
            f"{response.get('state')} {response.get('error', '')}"
        )
    products = (response.get("artifact") or {}).get("products") or []
    skills = [
        str(skill.get("id"))
        for skill in card.get("skills", [])
        if isinstance(skill, dict) and skill.get("id")
    ]
    interface = next(
        (
            item
            for item in card.get("supportedInterfaces", [])
            if isinstance(item, dict)
            and str(item.get("protocolBinding", "")).upper() == "JSONRPC"
        ),
        {},
    )
    exchange = client.last_exchange or {}
    request = exchange.get("request") if isinstance(exchange.get("request"), dict) else {}
    request_headers = (
        request.get("headers") if isinstance(request.get("headers"), dict) else {}
    )
    data_part_summary = json.dumps(
        {
            "skill": "browse",
            "input": {
                "query": query,
                "top_k": 10,
                "constraints": {},
            },
        },
        separators=(",", ":"),
    )
    protocol_trace = [
        {
            "from": "Butler",
            "to": "Store Agent",
            "action": "discover capabilities",
            "detail": "GET /.well-known/agent-card.json",
        },
        {
            "from": "Store Agent",
            "to": "Butler",
            "action": "return Agent Card",
            "detail": (
                f"skills={skills}; binding={interface.get('protocolBinding', 'JSONRPC')}; "
                f"version={request_headers.get('A2A-Version', '1.x')}"
            ),
        },
        {
            "from": "Butler",
            "to": "Store Agent",
            "action": "send A2A task",
            "detail": (
                f"POST {request.get('url', base_url.rstrip('/') + '/a2a')}; "
                "JSON-RPC 2.0 method=SendMessage; "
                f"DataPart={data_part_summary}; "
                "profile_fields=0"
            ),
        },
        {
            "from": "Store Agent",
            "to": "MiSArch",
            "action": "execute browse skill",
            "detail": (
                f"Call Catalog ListProducts and filter query={query} "
                "inside the Store Agent"
            ),
        },
        {
            "from": "MiSArch",
            "to": "Store Agent",
            "action": "return catalog evidence",
            "detail": f"Return {len(products)} unranked product candidates",
        },
        {
            "from": "Store Agent",
            "to": "Butler",
            "action": "complete A2A Task",
            "detail": (
                f"state={response.get('state')}; task_id={response.get('task_id')}; "
                f"context_id={response.get('context_id')}; "
                f"Artifact.products={len(products)}"
            ),
        },
        {
            "from": "Butler",
            "to": "OpenAI Agent",
            "action": "local decision",
            "detail": (
                "Apply 2 private preference fields inside the Butler; "
                "do not send them back to the Store Agent"
            ),
        },
    ]
    return (
        [item for item in products if isinstance(item, dict)],
        skills,
        protocol_trace,
    )


def run_arm(arm: str, question: str) -> dict[str, Any]:
    started = time.perf_counter()
    protocol_started = time.perf_counter()
    catalog_query = extract_catalog_query(question)
    if arm == "A":
        candidates = query_candidates(local_graphql_products(), catalog_query)
        arm_result = {
            "candidates": candidates,
            "catalog_query": catalog_query,
            "hops": 0,
            "preference_used": False,
            "store_profile_fields_disclosed": 0,
            "protocol_metadata": (
                "Native GraphQL schema; no tool discovery; no Agent Card"
            ),
            "protocol_trace": [
                {
                    "from": "GraphQL Client",
                    "to": "MiSArch",
                    "action": "direct query",
                    "detail": (
                        "POST /graphql operation=ListProducts(first:100); "
                        "the client must know the schema in advance"
                    ),
                },
                {
                    "from": "MiSArch",
                    "to": "GraphQL Client",
                    "action": "query result",
                    "detail": (
                        f"GraphQL data.products.nodes returned; "
                        f"local query filter={catalog_query}; "
                        f"{len(candidates)} matching candidate(s) retained"
                    ),
                },
                {
                    "from": "GraphQL Client",
                    "to": "OpenAI Agent",
                    "action": "forward evidence",
                    "detail": (
                        "Pass normalized names and prices; no MCP tools/list "
                        "and no A2A Agent Card discovery"
                    ),
                },
            ],
        }
    elif arm in {"B", "D"}:
        candidates, tools, protocol_trace = mcp_products(catalog_query)
        if arm == "D":
            protocol_trace.append(
                {
                    "from": "Local Profile",
                    "to": "OpenAI Agent",
                    "action": "apply structured preference",
                    "detail": (
                        "material=stainless steel; preference is applied locally "
                        "and is not included in tools/call"
                    ),
                }
            )
        arm_result = {
            "candidates": candidates,
            "catalog_query": catalog_query,
            "hops": 1,
            "preference_used": arm == "D",
            "store_profile_fields_disclosed": 0,
            "protocol_metadata": f"Discovered MCP tools: {', '.join(tools)}",
            "protocol_trace": protocol_trace,
        }
    else:
        candidates, skills, protocol_trace = a2a_products(catalog_query)
        arm_result = {
            "candidates": candidates,
            "catalog_query": catalog_query,
            "hops": 2,
            "preference_used": True,
            "store_profile_fields_disclosed": 0,
            "protocol_metadata": f"Agent Card skills: {', '.join(skills)}",
            "protocol_trace": protocol_trace,
        }

    protocol_duration_ms = round(
        (time.perf_counter() - protocol_started) * 1000,
        1,
    )
    policy = ARM_AGENT_POLICIES[arm]
    public_rules = policy["public_rules"]
    agent_policy = policy["policy"]
    allow_no_selection = policy["allow_no_selection"]
    if not arm_result["candidates"]:
        public_rules = [
            f"Search the catalog using query={catalog_query}",
            "Do not substitute unrelated products when the query has no matches",
            "Return an explicit no-match result with no selected product",
        ]
        agent_policy = (
            f"{agent_policy} The catalog returned no candidates for query "
            f"{catalog_query!r}. selected_name must be an empty string and the "
            "final answer must clearly say that no matching product was found."
        )
        allow_no_selection = True
    agent_started = time.perf_counter()
    decision = run_openai_agent(
        arm=arm,
        question=question,
        role=policy["role"],
        policy=agent_policy,
        candidates=arm_result["candidates"],
        protocol_context={
            "path": ARM_META[arm]["path"],
            "hops": arm_result["hops"],
            "metadata": arm_result["protocol_metadata"],
            "catalog_query": catalog_query,
            "profile_fields_sent_to_store": arm_result[
                "store_profile_fields_disclosed"
            ],
        },
        allow_no_selection=allow_no_selection,
    )
    agent_duration_ms = round((time.perf_counter() - agent_started) * 1000, 1)
    selected = next(
        (
            candidate
            for candidate in arm_result["candidates"]
            if candidate.get("name") == decision["selected_name"]
        ),
        None,
    )
    return {
        "arm": arm,
        "question": question,
        "answer": decision["final_answer"],
        "decision_summary": decision["decision_summary"],
        "selected": selected,
        **arm_result,
        "agent_role": policy["role"],
        "agent_profile_fields": policy["agent_profile_fields"],
        "public_rules": public_rules,
        "openai_model": decision.get("model"),
        "openai_response_id": decision.get("response_id"),
        "openai_usage": decision.get("usage") or {},
        "protocol_duration_ms": protocol_duration_ms,
        "agent_duration_ms": agent_duration_ms,
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def public_candidate_audit(result: dict[str, Any]) -> list[dict[str, str]]:
    """Explain observable policy application without exposing private reasoning."""
    arm = result["arm"]
    selected = result.get("selected") or {}
    selected_name = str(selected.get("name") or "")
    selected_price = int(selected.get("retail_price_cents") or 0)
    rows: list[dict[str, str]] = []

    for candidate in result["candidates"]:
        name = str(candidate.get("name") or "")
        lowered_name = name.lower()
        price = int(candidate.get("retail_price_cents") or 0)
        status = "ELIGIBLE"
        reason = "Candidate came from protocol-returned product evidence"

        if arm == "A":
            status = "DISPLAY"
            reason = "This path displays raw candidates without selecting one"
        elif arm == "B":
            if name == selected_name:
                status = "SELECT"
                reason = "Lowest price"
            else:
                status = "REJECT"
                reason = (
                    f"€{price / 100:.2f} is above the lowest price "
                    f"€{selected_price / 100:.2f}"
                )
        elif arm == "D":
            if "stainless steel" not in lowered_name:
                status = "REJECT"
                reason = "Does not match local material preference: stainless steel"
            elif name == selected_name:
                status = "SELECT"
                reason = (
                    "Matches the stainless-steel preference and has the lowest "
                    "price among matching candidates"
                )
            else:
                status = "REJECT"
                reason = "Matches the material preference but costs more"
        else:
            if "plastic" in lowered_name:
                status = "REJECT"
                reason = "Local private preference excludes plastic"
            elif price > 2000:
                status = "REJECT"
                reason = "Price exceeds the local EUR 20 limit"
            elif name == selected_name:
                status = "SELECT"
                if "borosilicate" in lowered_name:
                    reason = (
                        "Non-plastic, within budget, and matches the "
                        "borosilicate-glass preference"
                    )
                else:
                    reason = "Non-plastic, within budget, and ranks highest"
            else:
                status = "ELIGIBLE"
                reason = "Non-plastic and within budget, but did not rank first"

        rows.append(
            {
                "name": name,
                "price": f"€{price / 100:.2f}",
                "status": status,
                "reason": reason,
            }
        )
    return rows


def render(result: dict[str, Any]) -> str:
    meta = ARM_META[result["arm"]]
    color = meta["color"] if sys.stdout.isatty() and not os.environ.get("NO_COLOR") else ""
    reset = "\033[0m" if color else ""
    lines = [
        f"{color}╔══════════════════════════════════════════════════╗",
        f"  {meta['title']}",
        f"╚══════════════════════════════════════════════════╝{reset}",
        f"Same question: {result['question']}",
        f"Catalog query: {result['catalog_query']}",
        f"Path: {meta['path']}",
        f"Real OpenAI Agent: true ({result['agent_role']})",
        "",
    ]
    if result.get("protocol_trace"):
        lines.append(
            f"{meta['protocol']} interaction trace "
            "(summary of real protocol exchanges):"
        )
        for index, event in enumerate(result["protocol_trace"], start=1):
            lines.append(
                f"  [{index}] {event['from']} ──{event['action']}──▶ {event['to']}"
            )
            lines.append(f"      {event['detail']}")
        lines.extend(
            [
                "  Privacy boundary: Store Agent received profile_fields=0; "
                f"{result['agent_profile_fields']} preference field(s) stayed local.",
                "",
            ]
        )
    lines.extend(
        [
        "Public auditable decision trace "
        "(derived from inputs, rules, and output; not private chain-of-thought):",
        f"  [1/5] Receive evidence: {len(result['candidates'])} candidate(s) "
        f"for query={result['catalog_query']}",
        "  [2/5] Set privacy boundary: "
        f"{result['agent_profile_fields']} local preference field(s); "
        f"{result['store_profile_fields_disclosed']} sent to Store Agent/MiSArch",
        "  [3/5] Apply public rules:",
        ]
    )
    for rule in result["public_rules"]:
        lines.append(f"        - {rule}")
    lines.append("  [4/5] Evaluate each candidate:")
    audit_rows = public_candidate_audit(result)
    if not audit_rows:
        lines.append("        · No matching candidates to evaluate")
    for row in audit_rows:
        marker = (
            "✓"
            if row["status"] == "SELECT"
            else "×"
            if row["status"] == "REJECT"
            else "·"
        )
        lines.append(
            f"        {marker} {row['name']} | {row['price']} | "
            f"{row['status']}: {row['reason']}"
        )
    selection = (
        f"{result['selected'].get('name')}, "
        f"€{int(result['selected'].get('retail_price_cents') or 0) / 100:.2f}"
        if result.get("selected")
        else (
            "No matching product selected"
            if not result["candidates"]
            else "This role makes no single recommendation"
        )
    )
    lines.extend(
        [
            f"  [5/5] Produce output: {selection}",
            "",
            "Agent's public explanation:",
        ]
    )
    for index, step in enumerate(result["decision_summary"], start=1):
        lines.append(f"  {index}. {step}")
    lines.extend(
        [
            "",
            f"Final answer: {result['answer']}",
            "",
            "Candidates:",
        ]
    )
    if not result["candidates"]:
        lines.append("  · None returned for this catalog query")
    for item in result["candidates"]:
        marker = "★" if result.get("selected") is item else "·"
        lines.append(
            f"  {marker} {item.get('name')}  "
            f"€{int(item.get('retail_price_cents') or 0) / 100:.2f}"
        )
    lines.extend(
        [
            "",
            f"Protocol hops: {result['hops']}",
            f"Structured preference used: {str(result['preference_used']).lower()}",
            f"Preference fields given to OpenAI Agent: {result['agent_profile_fields']}",
            "Preference fields sent to Store Agent/MiSArch: "
            f"{result['store_profile_fields_disclosed']}",
            f"Protocol metadata: {result['protocol_metadata']}",
            f"OpenAI model: {result['openai_model']}",
            f"OpenAI response: {result['openai_response_id']}",
            "Tokens: "
            f"in={result['openai_usage'].get('input_tokens', '?')} / "
            f"out={result['openai_usage'].get('output_tokens', '?')} / "
            f"total={result['openai_usage'].get('total_tokens', '?')}",
            "Latency: "
            f"protocol {result['protocol_duration_ms']} ms + "
            f"Agent {result['agent_duration_ms']} ms = "
            f"{result['duration_ms']} ms",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one live arm of the video demo.")
    parser.add_argument("--arm", required=True, choices=["A", "B", "D", "C"])
    parser.add_argument("--question", default="")
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    question = args.question.strip()
    if question:
        try:
            result = run_arm(args.arm, question)
            print(
                json.dumps(result, ensure_ascii=False, indent=2)
                if args.json
                else render(result)
            )
            return 0
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    meta = ARM_META[args.arm]
    color = (
        meta["color"]
        if sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        else ""
    )
    reset = "\033[0m" if color else ""
    if sys.stdout.isatty():
        print(f"\033]0;{meta['title']}\007", end="")
    print(f"{color}━━ {meta['title']} ━━{reset}")
    print("Interactive mode: ask repeatedly; type quit or exit to stop this pane.")

    while True:
        try:
            question = input(
                f"\n[{args.arm}] Enter the same question "
                "(quit/exit to stop): "
            ).strip()
        except EOFError:
            print("\nInput closed. Exiting.")
            return 0
        if question.lower() in {"quit", "exit"}:
            print("Demo pane stopped.")
            return 0
        if not question:
            print("Please enter a non-empty question.")
            continue
        try:
            result = run_arm(args.arm, question)
            print(
                json.dumps(result, ensure_ascii=False, indent=2)
                if args.json
                else render(result)
            )
            print("\nReady for the next question.")
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            print("The pane remains active; fix the issue or enter another question.")


if __name__ == "__main__":
    raise SystemExit(main())
