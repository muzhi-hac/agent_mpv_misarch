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
    read_server_metrics,
    server_delta,
    write_transcript_sidecar,
)

DEFAULT_A2A_URL = os.environ.get("MISARCH_A2A_URL", "http://127.0.0.1:8001")
DEFAULT_PROFILE = "data/user_profile.json"
DEFAULT_USER_ID = "demo-user"
DEFAULT_TOP_K = 10

PURCHASE_KEYWORDS = ("place an order", "order", "buy", "purchase", "checkout")


def get_json(url: str, timeout: float = 15) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
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
    """Minimal A2A client: read the Agent Card and POST tasks."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def fetch_card(self) -> dict[str, Any]:
        return get_json(self.base_url + "/.well-known/agent-card.json")

    def send_task(self, task_id: str, skill: str, payload: dict[str, Any]) -> dict[str, Any]:
        body, _ = post_json(
            self.base_url + "/tasks",
            {"task_id": task_id, "skill": skill, "input": payload},
        )
        return body


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
    ) -> None:
        self.a2a = a2a
        self.prefs = prefs
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.top_k = top_k

    def _infer_category_and_intent(self, task: str) -> tuple[str, bool]:
        heuristic_purchase = any(k in task.lower() for k in PURCHASE_KEYWORDS)
        prompt = (
            "Classify a shopping request. Return ONLY JSON: "
            '{"category":"<single english noun, e.g. cup or tent>",'
            '"is_purchase":true|false}.\n'
            "is_purchase is true only if the user wants to place/buy an order now.\n\n"
            f"Request: {task}"
        )
        try:
            raw = responses_api_call(self.base_url, self.api_key, self.model, prompt)
            payload = extract_json_object(raw)
            category = str(payload.get("category", "")).strip().lower() or "unknown"
            is_purchase = bool(payload.get("is_purchase", heuristic_purchase))
            return category, is_purchase
        except Exception:
            # Heuristic fallback keeps the arm runnable if the model proxy is down.
            category = "cup" if "cup" in task.lower() else (
                "tent" if "tent" in task.lower() else "unknown"
            )
            return category, heuristic_purchase

    def _final_answer(self, task: str, ranked: list[dict[str, Any]], pref: dict[str, Any]) -> str:
        prompt = (
            "You are a user-side shopping butler. Recommend ONE product from the "
            "ranked candidates and justify it by citing the user's preference. "
            "Be concise.\n\n"
            f"Task: {task}\n"
            f"User preference (private, applied locally): {json.dumps(pref, ensure_ascii=False)}\n"
            f"Ranked candidates: {json.dumps(ranked[:5], ensure_ascii=False)}\n\n"
            "Return ONLY JSON: {\"answer\":\"...\"}"
        )
        try:
            raw = responses_api_call(self.base_url, self.api_key, self.model, prompt)
            return str(extract_json_object(raw).get("answer", "")).strip() or raw.strip()
        except Exception as exc:
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
        trace.append({"event": "fetch_card", "duration_ms": elapsed_ms(card_start)})
        skills = {s.get("id"): s for s in card.get("skills", []) if isinstance(s, dict)}

        # 3. minimal disclosure (local) — what may cross the boundary
        constraints, disclosed = self.prefs.minimal_constraints(task, category)

        # 4. browse task (A2A hop) — store-agent returns UNRANKED candidates
        browse_start = time.perf_counter()
        try:
            resp = self.a2a.send_task(
                "a2a-browse",
                "browse",
                {"top_k": self.top_k, "query": category, "constraints": constraints},
            )
        except Exception as exc:
            return self._fail(task, start, trace, hops, risk, f"browse failed: {exc}")
        hops += 1
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
            return {
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
            }

        # 5. LOCAL ranking with the full profile (profile never left the process)
        pref = self.prefs.for_category(category)
        ranked = self.prefs.rank(candidates, category)
        preference_used = bool(pref)

        # 6. risk handling — purchase is Phase-1 interception only
        if is_purchase:
            purchase_skill = skills.get("purchase", {})
            if purchase_skill.get("risk_level", "none") != "none":
                risk["detected"] = True
            if purchase_skill.get("requires_confirmation"):
                risk["confirmation_required"] = True
                # Non-interactive run: confirmation is held, purchase task NOT sent.
                risk["user_confirmed"] = False
            # purchase_task_sent stays False (Phase 1 stops here)
            trace.append({"event": "risk_intercept", "duration_ms": 0.0, "held": True})

        # 7. final recommendation citing the (locally applied) preference
        answer_start = time.perf_counter()
        answer = self._final_answer(task, ranked, pref)
        trace.append({"event": "final_answer", "duration_ms": elapsed_ms(answer_start)})

        return {
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
            "ranked_candidates": ranked[:5],
            "metrics": METER.snapshot(),
            "transcript": TRANSCRIPT.entries,
            "trace": trace,
        }

    def _fail(self, task, start, trace, hops, risk, error):
        return {
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
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Arm C: A2A user-butler agent.")
    parser.add_argument("--task", required=True)
    parser.add_argument("--a2a-url", default=DEFAULT_A2A_URL)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--model-base-url", default=os.environ.get("OPENAI_BASE_URL", DEFAULT_MODEL_BASE_URL))
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
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
        )
        server_pre = read_server_metrics(args.a2a_url)
        result = butler.run(args.task)
        delta = server_delta(server_pre, read_server_metrics(args.a2a_url))
        if delta and isinstance(result.get("metrics"), dict):
            result["metrics"]["server"] = delta

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
