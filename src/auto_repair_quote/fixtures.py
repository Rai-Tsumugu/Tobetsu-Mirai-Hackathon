"""Canonical fictional inputs shared by quote design implementations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_DEMO_INPUTS: dict[str, Any] = {
    "quote_id": "demo",
    "labor": {
        "person_hours": {"low": 1, "typical": 1.5, "high": 2.5},
        "elapsed_hours": {"low": 1, "typical": 3, "high": 5},
        "breakdown": [
            {
                "operation": "架空: デモ作業",
                "hours": {"low": 1, "typical": 1.5, "high": 2.5},
                "reason": "架空: 現車確認前のデモ条件",
                "status": "proposed",
            }
        ],
        "unknowns": [],
    },
    "labor_rate": {
        "yen_per_person_hour": 8000,
        "rate_ref": "RATE-DEMO-01",
        "effective_from": "2026-10-01",
        "basis": [
            {"label": "架空: デモ設定", "value": 8000, "unit": "円/人時"}
        ],
    },
    "items": [
        {
            "item_id": "SIM-PART-001",
            "name": "架空: 販売部品",
            "category": "部品",
            "unit": "個",
            "unit_price": 1000,
            "price_type": "販売",
            "source": "simulator",
            "updated_at": "2026-10-11",
            "quantity_range": {"low": 1, "typical": 1, "high": 1},
            "quantity_unit": "個",
        }
    ],
    "tax_policy": {
        "source": "simulator",
        "rate": 0.1,
        "rounding": "floor",
    },
}


def demo_inputs() -> dict[str, Any]:
    """Return a fresh copy of the canonical, entirely fictional demo inputs."""
    return deepcopy(_DEMO_INPUTS)


def demo_presets():
    """Fictional complete bundles; no vehicle/rust multipliers."""
    inputs = demo_inputs()
    inputs.update(customer_ref='C-DEMO-01', vehicle_ref='V-DEMO-01', job_ref='JOB-DEMO-01')
    return [{
        'preset_id': 'PRESET-DEMO-01', 'job_id': 'JOB-DEMO-01',
        'job_ref': 'JOB-DEMO-01', 'name': '架空: ブレーキ整備',
        'aliases': [{'alias':'ブレーキ','approved_by':'operator-demo-01'}, {'alias':'パッド','approved_by':'operator-demo-01'}], 'source':'simulator', 'approved_by': 'operator-demo-01',
        'required_conditions': [], 'updated_at': '2026-10-11',
        'version': 1, 'inputs': inputs, 'default_quantity': 1,
        'rate_ref': 'RATE-DEMO-01', 'item_refs': ['SIM-PART-001'],
    }]
