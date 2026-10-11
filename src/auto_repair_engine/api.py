"""FastAPI entry point for the local simulator."""
from __future__ import annotations

import os
import sys
import uuid
from copy import deepcopy
from math import floor, isfinite
from pathlib import Path
from typing import Any

from .runner import ENGINE_IDS, compare_engines, run_engine
from .store import AutoRepairStore
from .contract import approved_common_scenario_fixture, common_scenario_fixture

try:
    from fastapi import FastAPI, HTTPException
except ImportError as exc:  # pragma: no cover - depends on the local environment
    FastAPI = None  # type: ignore[assignment,misc]
    _FASTAPI_IMPORT_ERROR = exc
else:
    _FASTAPI_IMPORT_ERROR = None


def create_app(db_path: str | None = None):
    if FastAPI is None:
        raise RuntimeError("FastAPI is required to start this API; install it in the project environment") from _FASTAPI_IMPORT_ERROR
    app = FastAPI(title="Auto Repair Labor Simulator", version="0.1.0")
    from fastapi.responses import FileResponse
    default_data_dir = (Path.home() / "Library" / "Application Support" / "AutoRepairEngine" if sys.platform == "darwin"
                        else Path.home() / ".local" / "share" / "auto-repair-engine")
    persistence = AutoRepairStore(db_path or os.environ.get("AUTOREPAIR_DB", str(default_data_dir / "auto_repair_simulator.sqlite3")))

    def scenario_from(payload: dict[str, Any], *, allow_inline: bool = False) -> dict[str, Any]:
        scenario = payload.get("scenario_input")
        if scenario is None and allow_inline and "job_id" in payload:
            scenario = payload
        if not isinstance(scenario, dict) or not scenario:
            raise HTTPException(status_code=422, detail="scenario_input object is required")
        return scenario

    @app.get("/")
    def mobile_ui():
        return FileResponse(Path(__file__).with_name("web") / "index.html", media_type="text/html")

    @app.get("/browser.mjs")
    def browser_module():
        return FileResponse(Path(__file__).with_name("browser.mjs"), media_type="text/javascript")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "mode": "simulator", "fictional_data": True}

    @app.get("/api/engines")
    def engines() -> dict[str, Any]:
        return {"engine_ids": list(ENGINE_IDS), "integrated_engine_id": "integrated", "count": len(ENGINE_IDS)}

    @app.get("/api/integrated/schema")
    def integrated_schema(job_id: str = "front_brake_service"):
        from .e13 import build_schema
        return build_schema(job_id)

    @app.post("/api/integrated/evaluate")
    def integrated_evaluate(payload: dict[str, Any]):
        scenario = scenario_from(payload)
        from .e13 import apply_answers, render_form
        applied = apply_answers(scenario, payload.get("answers", {})) if "answers" in payload else {"scenario_input": scenario, "errors": [], "approvals": []}
        return {"scenario_input": applied["scenario_input"], "errors": applied["errors"],
                "questions": render_form(applied["scenario_input"])["questions"], "approvals": applied["approvals"]}

    @app.get("/api/fixture")
    def fixture(approved_rotor: bool = False) -> dict[str, Any]:
        maker = approved_common_scenario_fixture if approved_rotor else common_scenario_fixture
        return {"scenario_input": maker(), "fictional_data": True}


    def fictional_e02_pack(scenario: dict[str, Any]) -> dict[str, Any]:
        """Fixture-only E02 pack built by the product API, not imported from tests."""
        return {"engine_id": "e02_versioned_json", "rule_version": scenario.get("rule_version", "fictional-rule-v1"),
                "status": "approved", "approved_by": "fictional_shop_owner", "effective_from": "2026-10-11",
                "source": "fictional_fixture_only", "basis_unit": scenario.get("basis_unit"),
                "basis_definition": scenario.get("basis_definition"), "rules": [
                    {"job_id":"front_brake_service","operation_key":"base_service","condition":{"field":"work_scope","equals":"front_brake_service"},"hours":{"low":1.7,"typical":1.7,"high":1.7},"unit":"person_hours","source":"fictional_json:base"},
                    {"job_id":"front_brake_service","operation_key":"replacement_carry","condition":{"field":"included_operations","contains":"remove_install"},"hours":{"low":0.2,"typical":0.2,"high":0.2},"unit":"person_hours","source":"fictional_json:carry"},
                    {"job_id":"front_brake_service","operation_key":"snow_melt","condition":{"field":"included_operations","contains":"snow_removal"},"hours":{"low":0.5,"typical":0.5,"high":0.5},"unit":"elapsed_hours","source":"fictional_json:snow"},
                    {"job_id":"front_brake_service","operation_key":"penetrant_wait","condition":{"field":"work_scope","equals":"front_brake_service"},"hours":{"low":0.25,"typical":0.25,"high":0.25},"unit":"elapsed_hours","source":"fictional_json:penetrant"},
                    {"job_id":"front_brake_service","operation_key":"parts_wait","condition":{"field":"parts_wait_stock_checked","equals":True},"hours":{"low":0.0,"typical":0.0,"high":0.0},"unit":"elapsed_hours","source":"fictional_json:parts"},
                    {"job_id":"front_brake_service","operation_key":"wash","condition":{"field":"work_scope","equals":"front_brake_service"},"hours":{"low":0.1,"typical":0.1,"high":0.1},"unit":"person_hours","source":"fictional_json:wash"},
                    {"job_id":"front_brake_service","operation_key":"rotor_seizure","condition":{"field":"rotor_relevance","equals":"relevant"},"hours":{"low":0.0,"typical":0.25,"high":0.5},"unit":"person_hours","source":"fictional_json:rotor"}]}

    @app.get("/api/engines/{engine_id}/example")
    def example_rule_pack(engine_id: str, approved_rotor: bool = True) -> dict[str, Any]:
        scenario = approved_common_scenario_fixture() if approved_rotor else common_scenario_fixture()
        if engine_id == "e02":
            return {"scenario_input": scenario, "rule_pack": fictional_e02_pack(scenario), "fictional_data": True}
        raise HTTPException(status_code=404, detail="no approved example pack for this engine")

    @app.post("/api/engines/{engine_id}/calculate")
    def calculate(engine_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            if engine_id == "integrated":
                scenario = scenario_from(payload, allow_inline=True)
                rule_pack=payload.get("rule_pack")
                if payload.get("client_proposal") is not None:
                    rule_pack={**(rule_pack or {}),"rule_version":scenario.get("rule_version","fictional-rule-v1"),
                               "client_proposal":payload["client_proposal"]}
                return run_engine(engine_id, scenario, rule_pack)
            scenario = scenario_from(payload, allow_inline=True)
            rule_pack = payload.get("rule_pack")
            if engine_id == "e02" and rule_pack is None:
                rule_pack = fictional_e02_pack(scenario)
            return run_engine(engine_id, scenario, rule_pack)
        except (TypeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ModuleNotFoundError as exc:
            raise HTTPException(status_code=503, detail=f"{engine_id} implementation is not installed yet") from exc

    @app.post("/api/compare")
    def compare(payload: dict[str, Any]) -> dict[str, Any]:
        scenario = scenario_from(payload)
        raw_engine_ids = payload.get("engine_ids", ENGINE_IDS)
        if not isinstance(raw_engine_ids, (list, tuple)) or not raw_engine_ids:
            raise HTTPException(status_code=422, detail="engine_ids must be a non-empty array")
        engine_ids = tuple(raw_engine_ids)
        if any(engine_id not in ENGINE_IDS for engine_id in engine_ids):
            raise HTTPException(status_code=422, detail="unknown engine_id")
        try:
            custom_packs = payload.get("rule_packs", {})
            if not isinstance(custom_packs, dict):
                raise HTTPException(status_code=422, detail="rule_packs must be an object keyed by engine id")
            results = []
            for selected_engine in engine_ids:
                selected_pack = custom_packs.get(selected_engine, payload.get("rule_pack"))
                if selected_engine == "e02" and selected_pack is None:
                    selected_pack = fictional_e02_pack(scenario)
                result = run_engine(selected_engine, scenario, selected_pack)
                results.append({"engine_id": selected_engine, "labor": result.get("labor"), "status": result.get("status"),
                                "rule_version": result.get("rule_version"), "trace": result.get("trace", [])})
        except (TypeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ModuleNotFoundError as exc:
            raise HTTPException(status_code=503, detail="one or more engine implementations are not installed yet") from exc
        return {"scenario_id": scenario.get("scenario_id"), "results": results, "fictional_data": True}

    @app.post("/api/estimates", status_code=201)
    def create_estimate(payload: dict[str, Any]) -> dict[str, Any]:
        scenario = deepcopy(scenario_from(payload))
        engine_id = payload.get("engine_id", scenario.get("engine_id", "e07"))
        try:
            rule_pack = payload.get("rule_pack")
            if engine_id == "e02" and rule_pack is None:
                rule_pack = fictional_e02_pack(scenario)
            if engine_id in ("e27", "e28", "integrated") and payload.get("client_proposal") is not None:
                rule_pack = {**(rule_pack or {}), "rule_version": scenario.get("rule_version", "fictional-rule-v1"),
                             "client_proposal": payload["client_proposal"]}
            result = run_engine(engine_id, scenario, rule_pack)
        except ModuleNotFoundError as exc:
            raise HTTPException(status_code=503, detail=f"{engine_id} implementation is not installed yet") from exc
        except (TypeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if result.get("status") in ("missing-required", "blocked"):
            raise HTTPException(status_code=409, detail={"message": "required observations or approvals are missing", "engine_result": result})
        rate_raw = scenario.get("labor_rate")
        rate = rate_raw.get("value") if isinstance(rate_raw, dict) else rate_raw
        hours = result.get("labor", {}).get("person_hours", {})
        try:
            rate_value = float(rate)
        except (TypeError, ValueError):
            rate_value = float("nan")
        if rate is None:
            raise HTTPException(status_code=409, detail="labor_rate is required to calculate money")
        if isinstance(rate, bool) or not isfinite(rate_value) or rate_value < 0:
            raise HTTPException(status_code=422, detail="labor_rate must be a finite, non-negative number")
        if any(hours.get(key) is None for key in ("low", "typical", "high")):
            raise HTTPException(status_code=409, detail="a complete person_hours range is required to calculate money")
        try:
            hour_values = {key: float(hours[key]) for key in ("low", "typical", "high")}
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="person_hours range must contain finite numbers")
        if any(not isfinite(value) or value < 0 for value in hour_values.values()) or not (hour_values["low"] <= hour_values["typical"] <= hour_values["high"]):
            raise HTTPException(status_code=422, detail="person_hours range must be finite, non-negative, and ordered low <= typical <= high")
        amount_range = {key: floor(hour_values[key] * rate_value) for key in ("low", "typical", "high")}
        result["labor_result"] = {"labor_hours": hour_values, "labor_rate": rate_value, "calculated_amount_range": amount_range,
                                  "final_labor_amount": None, "parts_amount": None, "tax_amount": None, "status": "proposed"}
        approvals = list(result.get("approvals", []))
        if payload.get("final_labor_amount") is not None:
            actor = payload.get("actor")
            reason = payload.get("adjustment_reason")
            final_amount = payload["final_labor_amount"]
            if isinstance(final_amount, bool) or not isinstance(final_amount, (int, float)) or not isfinite(float(final_amount)) or final_amount < 0 or not float(final_amount).is_integer():
                raise HTTPException(status_code=422, detail="final_labor_amount must be a non-negative whole number")
            if not isinstance(actor, str) or not actor.strip() or not isinstance(reason, str) or not reason.strip():
                raise HTTPException(status_code=422, detail="manual adjustment requires actor and adjustment_reason")
            approvals.append({"type": "labor_amount_adjustment", "actor": actor, "reason": reason,
                              "old_value": amount_range["typical"],
                              "new_value": int(final_amount)})
            result["approvals"] = approvals
            result["labor_result"]["final_labor_amount"] = int(final_amount)
            result["labor_result"]["status"] = "confirmed"
        estimate_id = str(uuid.uuid4())
        idempotency_key = payload.get("idempotency_key")
        if idempotency_key is not None and (not isinstance(idempotency_key, str) or not idempotency_key.strip()):
            raise HTTPException(status_code=422, detail="idempotency_key must be a non-empty string")
        try:
            estimate_id = persistence.save_estimate(estimate_id, result, idempotency_key)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"estimate_id": estimate_id, **(persistence.get_estimate(estimate_id) or result)}

    @app.get("/api/estimates")
    def list_estimates(limit: int = 100) -> list[dict[str, Any]]:
        return persistence.list_estimates(limit)

    @app.get("/api/estimates/{estimate_id}")
    def get_estimate(estimate_id: str) -> dict[str, Any]:
        result = persistence.get_estimate(estimate_id)
        if result is None:
            raise HTTPException(status_code=404, detail="estimate not found")
        return {"estimate_id": estimate_id, **result}

    @app.post("/api/scenarios/{scenario_id}/events", status_code=201)
    def add_observation_event(scenario_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        event_id = str(uuid.uuid4())
        persistence.record_event(event_id, scenario_id, payload.get("event_type", "observation"), payload,
                                 payload.get("operation_id"))
        return {"event_id": event_id, "scenario_id": scenario_id, "status": "recorded"}

    return app


app = create_app() if FastAPI is not None else None


if __name__ == "__main__":
    if app is None:
        raise SystemExit("FastAPI is not installed")
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
