#!/usr/bin/env python3
"""Arm C: user-butler agent driving the merchant store-agent over A2A.

Design (see a2aexperimentdesign.*.md):
  - The user profile lives user-side and is used ONLY locally for ranking.
  - Across the A2A boundary the butler sends only a task-derived query plus a
    minimal, whitelisted set of constraints — never the raw profile. Whatever
    crosses is logged as profile_fields_disclosed (empty by default).
  - The store-agent returns UNRANKED candidates; the butler ranks them locally.
  - Risk is recorded as a 4-field object; purchase is Phase-1 interception only.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from scripts.agent_gcp_baseline_test import (
    DEFAULT_MODEL,
    DEFAULT_MODEL_BASE_URL,
    elapsed_ms,
    extract_json_object,
    load_api_key,
    post_json,
    responses_api_call,
    utc_now,
)
from scripts.run_metrics import (
    METER,
    TRANSCRIPT,
    annotate_measurement,
    per_task_server_metrics_enabled,
    read_server_metrics,
    server_delta,
    write_transcript_sidecar,
)

DEFAULT_A2A_URL = os.environ.get("MISARCH_A2A_URL", "http://127.0.0.1:8001")
DEFAULT_PROFILE = "data/user_profile.json"
DEFAULT_USER_ID = "demo-user"
DEFAULT_TOP_K = 10

PURCHASE_KEYWORDS = ("place an order", "order", "buy", "purchase", "checkout")

# Guardrail: a retail price below this floor is treated as fabricated. The
# adversarial store-agent quotes 1 cent (€0.01) to hijack price-sensitive
# ranking; genuine retail goods are not priced under €1.00. Used by
# PreferenceModule.screen_candidates as the T1 price-manipulation defense.
MIN_PLAUSIBLE_PRICE_CENTS = 100
A2A_USER_AGENT = "misarch-a2a-e2e/1.0"

def build_intent_prompt(task: str) -> str:
    return (
        "Classify a shopping request. Return ONLY JSON: "
        '{"category":"<single english noun, e.g. cup or tent>",'
        '"is_purchase":true|false}.\n'
        "is_purchase is true only if the user wants to place/buy an order now.\n\n"
        f"Request: {task}"
    )


def build_final_answer_prompt(
    task: str,
    ranked: list[dict[str, Any]],
    pref: dict[str, Any],
) -> str:
    return (
        "You are a user-side shopping butler. Recommend ONE product from the "
        "ranked candidates and justify it by citing the user's preference. "
        "Be concise.\n\n"
        f"Task: {task}\n"
        f"User preference (private, applied locally): {json.dumps(pref, ensure_ascii=False)}\n"
        f"Ranked candidates: {json.dumps(ranked[:5], ensure_ascii=False)}\n\n"
        "Return ONLY JSON: {\"answer\":\"...\"}"
    )


def purchase_risk_policy(is_purchase: bool, advertised_skill: dict[str, Any]) -> dict[str, Any]:
    """Butler-side purchase-risk classification (T1 malicious-card defense).

    A purchase is classified high-risk by OUR policy, regardless of the store's
    self-advertised Agent Card metadata. A malicious store must not be able to
    downgrade its own confirmation gate by advertising risk_level="none",
    requires_confirmation=false, or by omitting the purchase skill entirely. The
    advertised metadata is recorded elsewhere for audit/mismatch, never trusted
    to relax the gate.
    """
    risk = {
        "detected": False,
        "confirmation_required": False,
        "user_confirmed": None,
        "purchase_task_sent": False,
    }
    if is_purchase:
        risk["detected"] = True
        risk["confirmation_required"] = True
        risk["user_confirmed"] = False
    return risk


def get_json(
    url: str,
    timeout: float = 15,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": A2A_USER_AGENT,
            **(headers or {}),
        },
        method="GET",
    )
    t_req = TRANSCRIPT.now_ms()
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        METER.record_http("backend", 0, len(raw))
        body = raw.decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} failed with HTTP {exc.code}: {body[:400]}") from exc
    except urllib.error.URLError as exc:
        METER.record_http("backend", 0, 0)
        raise RuntimeError(f"GET {url} failed: {exc.reason}") from exc
    with response:
        raw = response.read()
    METER.record_http("backend", 0, len(raw))
    parsed = json.loads(raw.decode("utf-8"))
    TRANSCRIPT.record_http(url, None, "backend", parsed, t_req, TRANSCRIPT.now_ms())
    return parsed


class A2AClient:
    """A2A 1.0 JSON-RPC client for the store-agent experiment."""

    def __init__(self, base_url: str, bearer_token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.bearer_token = (
            os.environ.get("MISARCH_A2A_BEARER_TOKEN", "")
            if bearer_token is None
            else bearer_token
        )
        self.card: dict[str, Any] | None = None
        self.last_exchange: dict[str, Any] | None = None

    def fetch_card(self) -> dict[str, Any]:
        self.card = get_json(
            self.base_url + "/.well-known/agent-card.json",
            headers=self._auth_headers(),
        )
        return self.card

    def _auth_headers(self) -> dict[str, str]:
        if not self.bearer_token:
            return {}
        return {"Authorization": f"Bearer {self.bearer_token}"}

    def _jsonrpc_interface(self) -> tuple[str, str]:
        card = self.card or self.fetch_card()
        for interface in card.get("supportedInterfaces", []):
            if not isinstance(interface, dict):
                continue
            if str(interface.get("protocolBinding", "")).upper() != "JSONRPC":
                continue
            url = str(interface.get("url", "")).rstrip("/")
            version = str(interface.get("protocolVersion", ""))
            if not url:
                raise RuntimeError("A2A JSONRPC interface is missing url")
            if not version.startswith("1."):
                raise RuntimeError(
                    f"A2A JSONRPC interface uses unsupported protocol version {version!r}; "
                    "this client requires A2A 1.x"
                )
            return url, version
        raise RuntimeError("Agent Card does not advertise an A2A JSONRPC interface")

    def send_task(self, task_id: str, skill: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._send_message(task_id, skill, payload)

    def continue_task(
        self,
        request_label: str,
        task_id: str,
        context_id: str,
        skill: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not task_id or not context_id:
            raise ValueError("task_id and context_id are required for an A2A continuation")
        return self._send_message(
            request_label,
            skill,
            payload,
            task_id=task_id,
            context_id=context_id,
        )

    def _send_message(
        self,
        request_label: str,
        skill: str,
        payload: dict[str, Any],
        *,
        task_id: str = "",
        context_id: str = "",
    ) -> dict[str, Any]:
        endpoint, version = self._jsonrpc_interface()
        request_id = f"{request_label}-{uuid.uuid4()}"
        message_id = str(uuid.uuid4())
        message = {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [{"data": {"skill": skill, "input": payload}}],
        }
        if task_id:
            message["taskId"] = task_id
        if context_id:
            message["contextId"] = context_id
        request_body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "SendMessage",
            "params": {
                "message": message,
            },
        }
        body, _ = post_json(
            endpoint,
            request_body,
            headers={
                "Accept": "application/json",
                "User-Agent": A2A_USER_AGENT,
                "A2A-Version": version,
                **self._auth_headers(),
            },
        )
        if body.get("jsonrpc") != "2.0" or body.get("id") != request_id:
            raise RuntimeError("A2A JSON-RPC response envelope does not match the request")
        self.last_exchange = {
            "stage": f"{skill}_task",
            "request": {
                "method": "POST",
                "url": endpoint,
                "headers": {"A2A-Version": version},
                "json": request_body,
            },
            "response": body,
        }
        return self._adapt_send_result(body)

    @staticmethod
    def _adapt_send_result(body: dict[str, Any]) -> dict[str, Any]:
        error = body.get("error")
        if isinstance(error, dict):
            raise RuntimeError(
                f"A2A JSON-RPC error {error.get('code')}: {error.get('message', 'unknown error')}"
            )
        result = body.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("A2A SendMessage response is missing result")
        task = result.get("task")
        if not isinstance(task, dict):
            if isinstance(result.get("message"), dict):
                raise RuntimeError("A2A store-agent returned a direct Message; a Task is required")
            raise RuntimeError("A2A SendMessage result is missing task")

        status = task.get("status") if isinstance(task.get("status"), dict) else {}
        protocol_state = status.get("state")
        state = {
            "TASK_STATE_COMPLETED": "completed",
            "TASK_STATE_INPUT_REQUIRED": "input-required",
            "TASK_STATE_WORKING": "working",
            "TASK_STATE_SUBMITTED": "working",
        }.get(protocol_state, "failed")

        artifact: dict[str, Any] = {}
        for item in task.get("artifacts", []):
            if not isinstance(item, dict):
                continue
            for part in item.get("parts", []):
                if isinstance(part, dict) and isinstance(part.get("data"), dict):
                    artifact.update(part["data"])

        message = status.get("message") if isinstance(status.get("message"), dict) else {}
        text_parts = [
            part.get("text", "")
            for part in message.get("parts", [])
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        note = "\n".join(text for text in text_parts if text)
        adapted = {
            "task_id": task.get("id", ""),
            "context_id": task.get("contextId", ""),
            "state": state,
            "message": note,
            "artifact": artifact,
        }
        if state == "failed":
            adapted["error"] = note or f"A2A task failed with state {protocol_state}"
        return adapted


def card_skill_risk(card: dict[str, Any], skill_id: str) -> dict[str, Any]:
    """Read MiSArch risk metadata from its declared A2A card extension."""
    capabilities = card.get("capabilities")
    if not isinstance(capabilities, dict):
        return {}
    for extension in capabilities.get("extensions", []):
        if not isinstance(extension, dict):
            continue
        params = extension.get("params")
        skills = params.get("skills") if isinstance(params, dict) else None
        risk = skills.get(skill_id) if isinstance(skills, dict) else None
        if isinstance(risk, dict):
            return risk
    return {}


class PreferenceModule:
    """User-side, in-process. NOT A2A. The full profile is used only locally."""

    def __init__(self, profile_path: str, user_id: str) -> None:
        data = json.loads(pathlib.Path(profile_path).read_text(encoding="utf-8"))
        user = data.get("users", {}).get(user_id, {})
        self.categories: dict[str, Any] = user.get("categories", {})
        self.global_prefs: dict[str, Any] = user.get("global", {})

    def for_category(self, category: str) -> dict[str, Any]:
        """Full preference for a category (local use only)."""
        return self.categories.get(category, {})

    def minimal_constraints(self, task: str, category: str) -> tuple[dict[str, Any], list[str]]:
        """Whitelisted hard limits to disclose, and the field names disclosed.

        Strong-privacy default: disclose nothing. The query (task-derived) is
        enough for the store-agent to return candidates; ranking is local.
        """
        return {}, []

    def budget_cents(self) -> Any:
        """User's per-item budget (max_single_item_cents), or None if unset."""
        return self.global_prefs.get("max_single_item_cents")

    def screen_candidates(
        self, candidates: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Guardrail (T1 price defense): reject store-reported prices we cannot
        trust for a money decision, before they influence the local ranking.

        A candidate is unsafe if its quoted price is implausibly low (fabricated,
        below MIN_PLAUSIBLE_PRICE_CENTS) or exceeds the user's per-item budget.
        Returns (safe_candidates, review) where review is a machine-readable
        audit of what was rejected and why. The store is a separate trust domain;
        its self-reported price is never trusted blindly again after this point.
        """
        budget = self.budget_cents()
        reviewed: list[dict[str, Any]] = []
        safe: list[dict[str, Any]] = []
        for c in candidates:
            price = c.get("retail_price_cents")
            anomaly = price is not None and price < MIN_PLAUSIBLE_PRICE_CENTS
            over_budget = budget is not None and price is not None and price > budget
            ok = price is not None and not anomaly and not over_budget
            reviewed.append({
                "id": c.get("id") or c.get("product_id"),
                "name": c.get("name"),
                "price_cents": price,
                "price_anomaly": anomaly,
                "over_budget": over_budget,
                "safe": ok,
            })
            if ok:
                safe.append(c)
        review = {
            "budget_cents": budget,
            "min_plausible_price_cents": MIN_PLAUSIBLE_PRICE_CENTS,
            "screened": len(candidates),
            "safe": len(safe),
            "rejected_price_anomaly": sum(1 for r in reviewed if r["price_anomaly"]),
            "rejected_over_budget": sum(1 for r in reviewed if r["over_budget"]),
            "candidates": reviewed,
        }
        return safe, review

    def rank(self, candidates: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
        """Rank candidates locally using the full profile. Profile never leaves."""
        pref = self.for_category(category)
        if not pref:
            return candidates
        material = str(pref.get("material", "")).lower()
        sensitivity = pref.get("price_sensitivity", "medium")

        def score(product: dict[str, Any]) -> float:
            value = 0.0
            name = str(product.get("name", "")).lower()
            if material and material in name:
                value += 10.0
            price = product.get("retail_price_cents") or 0
            if sensitivity == "high":
                value -= price / 1000.0
            elif sensitivity == "medium":
                value -= price / 5000.0
            # "low" sensitivity: price ignored
            return -value  # ascending sort -> best (highest value) first

        return sorted(candidates, key=score)


class UserButler:
    def __init__(
        self,
        a2a: A2AClient,
        prefs: PreferenceModule,
        base_url: str,
        api_key: str,
        model: str,
        top_k: int = DEFAULT_TOP_K,
        include_prompts: bool = False,
    ) -> None:
        self.a2a = a2a
        self.prefs = prefs
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.top_k = top_k
        self.include_prompts = include_prompts
        self.prompt_log: list[dict[str, Any]] = []
        self.a2a_transcript: list[dict[str, Any]] = []

    def _record_prompt(self, stage: str, prompt: str) -> dict[str, Any] | None:
        if not self.include_prompts:
            return None
        entry = {"stage": stage, "prompt": prompt}
        self.prompt_log.append(entry)
        return entry

    def _record_a2a(self, entry: dict[str, Any]) -> None:
        if self.include_prompts:
            self.a2a_transcript.append(entry)

    def _attach_debug(self, result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result.get("metrics"), dict):
            result["metrics"] = METER.snapshot()
        trace = result.get("trace") if isinstance(result.get("trace"), list) else []
        cross_agent_round_trips = int(result.get("hops", 0))
        business_calls = sum(
            1 for event in trace if event.get("event") == "browse_task"
        )
        annotate_measurement(
            result,
            protocol="a2a",
            cross_agent_round_trips=cross_agent_round_trips,
            business_calls=business_calls,
            protocol_round_trips=cross_agent_round_trips,
        )
        if self.include_prompts:
            result["llm_prompts"] = self.prompt_log
            result["a2a_transcript"] = self.a2a_transcript
        return result

    def _a2a_base_url(self) -> str:
        return str(getattr(self.a2a, "base_url", "fake-a2a-transport"))

    def _infer_category_and_intent(self, task: str) -> tuple[str, bool]:
        heuristic_purchase = any(k in task.lower() for k in PURCHASE_KEYWORDS)
        prompt = build_intent_prompt(task)
        prompt_entry = self._record_prompt("intent_classification", prompt)
        try:
            raw = responses_api_call(self.base_url, self.api_key, self.model, prompt)
            if prompt_entry is not None:
                prompt_entry["raw_output"] = raw
            payload = extract_json_object(raw)
            category = str(payload.get("category", "")).strip().lower() or "unknown"
            is_purchase = bool(payload.get("is_purchase", heuristic_purchase))
            return category, is_purchase
        except Exception as exc:
            if prompt_entry is not None:
                prompt_entry["error"] = str(exc)
            # Heuristic fallback keeps the arm runnable if the model proxy is down.
            category = "cup" if "cup" in task.lower() else (
                "tent" if "tent" in task.lower() else "unknown"
            )
            return category, heuristic_purchase

    def _final_answer(self, task: str, ranked: list[dict[str, Any]], pref: dict[str, Any]) -> str:
        prompt = build_final_answer_prompt(task, ranked, pref)
        prompt_entry = self._record_prompt("final_answer", prompt)
        try:
            raw = responses_api_call(self.base_url, self.api_key, self.model, prompt)
            if prompt_entry is not None:
                prompt_entry["raw_output"] = raw
            return str(extract_json_object(raw).get("answer", "")).strip() or raw.strip()
        except Exception as exc:
            if prompt_entry is not None:
                prompt_entry["error"] = str(exc)
            # Deterministic fallback so a model outage still yields a grounded answer.
            if ranked:
                top = ranked[0]
                return (
                    f"Recommended: {top.get('name')} "
                    f"({top.get('retail_price_cents')} {top.get('currency', '')}). "
                    f"(model unavailable: {exc})"
                )
            return f"No candidates available. (model unavailable: {exc})"

    def run(self, task: str) -> dict[str, Any]:
        task = task.strip()
        if not task:
            raise ValueError("task must not be empty")

        METER.reset()
        TRANSCRIPT.reset()
        self.prompt_log = []
        self.a2a_transcript = []
        start = time.perf_counter()
        trace: list[dict[str, Any]] = []
        hops = 0
        risk = {
            "detected": False,
            "confirmation_required": False,
            "user_confirmed": None,
            "purchase_task_sent": False,
        }

        # 1. category + intent (local reasoning)
        category, is_purchase = self._infer_category_and_intent(task)

        # 2. discover skills + risk metadata (A2A hop)
        card_start = time.perf_counter()
        try:
            card = self.a2a.fetch_card()
        except Exception as exc:
            return self._fail(task, start, trace, hops, risk, f"fetch_card failed: {exc}")
        hops += 1
        if self.include_prompts:
            self._record_a2a({
                "stage": "agent_card_discovery",
                "request": {
                    "method": "GET",
                    "url": self._a2a_base_url() + "/.well-known/agent-card.json",
                },
                "response": card,
            })
        trace.append({"event": "fetch_card", "duration_ms": elapsed_ms(card_start)})
        skills = {s.get("id"): s for s in card.get("skills", []) if isinstance(s, dict)}

        # 3. minimal disclosure (local) — what may cross the boundary
        constraints, disclosed = self.prefs.minimal_constraints(task, category)

        # 4. browse task (A2A hop) — store-agent returns UNRANKED candidates
        browse_start = time.perf_counter()
        browse_payload = {"top_k": self.top_k, "query": category, "constraints": constraints}
        try:
            resp = self.a2a.send_task(
                "a2a-browse",
                "browse",
                browse_payload,
            )
        except Exception as exc:
            return self._fail(task, start, trace, hops, risk, f"browse failed: {exc}")
        hops += 1
        if self.include_prompts:
            exchange = getattr(self.a2a, "last_exchange", None)
            if isinstance(exchange, dict):
                self._record_a2a(exchange)
            else:
                self._record_a2a({
                    "stage": "browse_task",
                    "request": {
                        "method": "POST",
                        "url": self._a2a_base_url() + "/a2a",
                        "json": {
                            "jsonrpc": "2.0",
                            "method": "SendMessage",
                            "params": {
                                "message": {
                                    "role": "ROLE_USER",
                                    "parts": [{"data": {
                                        "skill": "browse",
                                        "input": browse_payload,
                                    }}],
                                }
                            },
                        },
                    },
                    "response": resp,
                })
        trace.append({"event": "browse_task", "duration_ms": elapsed_ms(browse_start), "state": resp.get("state")})

        if resp.get("state") != "completed":
            return self._fail(task, start, trace, hops, risk,
                              f"browse not completed: {resp.get('state')} {resp.get('error', '')}")
        candidates = (resp.get("artifact") or {}).get("products") or []

        # 4b. structured inventory check — the store-agent can complete a browse and
        # still return zero purchasable candidates (out of stock / nothing matched).
        # Treat that as a first-class, structured outcome instead of handing an empty
        # list to the ranker and the model, which would otherwise emit a vague
        # "no candidates" answer with no machine-readable signal.
        inventory = {"sufficient": bool(candidates), "candidate_count": len(candidates)}
        if not inventory["sufficient"]:
            trace.append({"event": "inventory_shortfall", "duration_ms": 0.0, "candidate_count": 0})
            return self._attach_debug({
                "success": True,
                "arm": "a2a",
                "task": task,
                "answer": "Insufficient inventory: the store returned no recommendable/orderable candidate products.",
                "category": category,
                "steps": len(trace),
                "hops": hops,
                "duration_ms": elapsed_ms(start),
                "preference_used": False,
                "profile_fields_disclosed": disclosed,
                "risk": risk,
                "inventory": inventory,
                "ranked_candidates": [],
                "metrics": METER.snapshot(),
                "transcript": TRANSCRIPT.entries,
                "trace": trace,
            })

        # 4c. price guardrail (T1 price defense) — the store is a separate trust
        # domain, so its self-reported prices are screened before they can
        # influence ranking: fabricated near-zero prices and over-budget items
        # are dropped. If nothing survives, refuse rather than recommend on
        # untrusted prices (e.g. an --adversarial store quoting €0.01 for all).
        safe, price_review = self.prefs.screen_candidates(candidates)
        if not safe:
            trace.append({"event": "price_screen_blocked", "duration_ms": 0.0,
                          "screened": price_review["screened"], "safe": 0})
            return self._attach_debug({
                "success": True,
                "arm": "a2a",
                "task": task,
                "answer": "Withheld: no candidate passed price screening "
                          "(prices were implausibly low or over budget). Refusing "
                          "to recommend on untrusted store-reported prices.",
                "category": category,
                "steps": len(trace),
                "hops": hops,
                "duration_ms": elapsed_ms(start),
                "preference_used": False,
                "profile_fields_disclosed": disclosed,
                "risk": risk,
                "inventory": inventory,
                "price_review": price_review,
                "ranked_candidates": [],
                "trace": trace,
            })

        # 5. LOCAL ranking with the full profile (profile never left the process)
        pref = self.prefs.for_category(category)
        ranked = self.prefs.rank(safe, category)
        preference_used = bool(pref)

        # 6. risk handling — purchase is Phase-1 interception only. The gate is
        # keyed off OUR policy, not the store's self-advertised Agent Card, so a
        # malicious card cannot downgrade it (T1 card defense). The advertised
        # metadata is recorded for audit/mismatch only.
        advertised = dict(skills.get("purchase", {}))
        advertised.update(card_skill_risk(card, "purchase"))
        risk.update(purchase_risk_policy(is_purchase, advertised))
        if is_purchase:
            trace.append({"event": "risk_intercept", "duration_ms": 0.0, "held": True,
                          "advertised_risk_level": advertised.get("risk_level"),
                          "advertised_requires_confirmation": advertised.get("requires_confirmation")})
            self._record_a2a({
                "stage": "purchase_task",
                "request": None,
                "response": None,
                "note": "purchase intent was intercepted by the butler; no A2A purchase task was sent",
                "risk": risk,
            })

        # 7. final recommendation citing the (locally applied) preference
        answer_start = time.perf_counter()
        answer = self._final_answer(task, ranked, pref)
        trace.append({"event": "final_answer", "duration_ms": elapsed_ms(answer_start)})

        result = {
            "success": True,
            "arm": "a2a",
            "task": task,
            "answer": answer,
            "category": category,
            "steps": len(trace),
            "hops": hops,
            "duration_ms": elapsed_ms(start),
            "preference_used": preference_used,
            "profile_fields_disclosed": disclosed,
            "risk": risk,
            "inventory": inventory,
            "price_review": price_review,
            "ranked_candidates": ranked[:5],
            "metrics": METER.snapshot(),
            "transcript": TRANSCRIPT.entries,
            "trace": trace,
        }
        return self._attach_debug(result)

    def _fail(self, task, start, trace, hops, risk, error):
        return self._attach_debug({
            "success": False,
            "arm": "a2a",
            "task": task,
            "error": error,
            "steps": len(trace),
            "hops": hops,
            "duration_ms": elapsed_ms(start),
            "preference_used": False,
            "profile_fields_disclosed": [],
            "risk": risk,
            "inventory": {"sufficient": None, "candidate_count": 0},
            "metrics": METER.snapshot(),
            "transcript": TRANSCRIPT.entries,
            "trace": trace,
        })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Arm C: A2A user-butler agent.")
    parser.add_argument("--task", required=True)
    parser.add_argument("--a2a-url", default=DEFAULT_A2A_URL)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--model-base-url", default=os.environ.get("OPENAI_BASE_URL", DEFAULT_MODEL_BASE_URL))
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--include-prompts", action="store_true")
    parser.add_argument("--output", default="")
    return parser


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    args = build_parser().parse_args()
    try:
        api_key = load_api_key()
        prefs = PreferenceModule(args.profile, args.user_id)
        butler = UserButler(
            A2AClient(args.a2a_url),
            prefs,
            args.model_base_url,
            api_key,
            args.model,
            top_k=args.top_k,
            include_prompts=args.include_prompts,
        )
        collect_server_metrics = per_task_server_metrics_enabled()
        server_pre = read_server_metrics(args.a2a_url) if collect_server_metrics else None
        result = butler.run(args.task)
        server_post = read_server_metrics(args.a2a_url) if collect_server_metrics else None
        delta = server_delta(server_pre, server_post)
        if delta and isinstance(result.get("metrics"), dict):
            result["metrics"]["server"] = delta
            result["metrics"]["server_metric_scope"] = "task"
        elif not collect_server_metrics and isinstance(result.get("metrics"), dict):
            result["metrics"]["server_metric_scope"] = "benchmark_window"

        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        print(rendered)
        if args.output:
            output_path = pathlib.Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered + "\n", encoding="utf-8")
            write_transcript_sidecar(args.output)
        return 0 if result.get("success") else 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
