from fastapi.testclient import TestClient

from backend.app import app


def base(**values):
    return {"period_start": "2026-01-01", "source_date": "2026-10-01", "effective_from": "2026-11-01",
            "source": "架空シミュレータ", "evidence_ref": "架空例", "evidence_notes": "架空入力", **values}


def test_r20_duplicate_worker_ids_rejected_without_candidate_or_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_REPAIR_RATE_DB", str(tmp_path / "r20-duplicates.sqlite3"))
    payload = base(
        workers=[
            {"id": "worker-a", "annual_cost_yen": 3_600_000, "annual_billable_hours": 1800},
            {"id": "worker-a", "annual_cost_yen": 7_200_000, "annual_billable_hours": 1800},
        ],
        job_hours_by_worker={"worker-a": 2},
    )

    with TestClient(app) as client:
        preview = client.post("/api/auto-repair-rate/R20/rates/preview", json=payload)
        proposal = client.post("/api/auto-repair-rate/R20/proposals", json=payload)

    assert preview.status_code == 422
    assert "worker IDs must be unique" in preview.text
    assert proposal.status_code == 422
    assert "worker IDs must be unique" in proposal.text
    assert not (tmp_path / "r20-duplicates.sqlite3").exists()
