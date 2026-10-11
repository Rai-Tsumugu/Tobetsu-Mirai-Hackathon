/* eslint-disable @typescript-eslint/no-explicit-any */
// 元の FastAPI（TestClient）の応答の記録と、TS の API 処理本体（service.ts）の応答を照合する。
// 保存先はメモリ内の EngineStore で代用する（PostgreSQL への保存は engine-store.test.ts で確認する）。
import { beforeEach, describe, expect, it } from "vitest";
import { canonicalHash, type EngineStore } from "../../../lib/db/repositories/engine-store";
import { PyValueError, type Dict } from "../../../lib/systems/engine/py";
import { resetEngineState } from "../../../lib/systems/engine/runner";
import * as service from "../../../lib/systems/engine/service";
import { compareEngines } from "../../../lib/systems/engine/runner";
import { golden } from "./fixtures";
import { normalize } from "./normalize";

export class MemoryEngineStore implements EngineStore {
  estimates: { id: string; body: Dict; hash: string; at: number; created: string }[] = [];
  idempotency = new Map<string, { id: string; hash: string }>();
  events: Dict[] = [];
  async saveEstimate(id: string, result: Dict, key: string | null) {
    const hash = canonicalHash(result);
    if (key) {
      const existing = this.idempotency.get(key);
      if (existing) {
        if (existing.hash !== hash) throw new PyValueError("idempotency_key_conflict");
        return existing.id;
      }
    }
    this.estimates.push({ id, body: JSON.parse(JSON.stringify(result)), hash, at: this.estimates.length, created: "2026-10-11 00:00:00" });
    if (key) this.idempotency.set(key, { id, hash });
    return id;
  }
  async getEstimate(id: string) {
    return this.estimates.find((e) => e.id === id)?.body ?? null;
  }
  async listEstimates(limit: number) {
    return [...this.estimates].reverse().slice(0, Math.max(1, Math.min(limit, 500))).map((e) => ({ estimate_id: e.id, created_at: e.created, ...e.body }));
  }
  async recordEvent(eventId: string, scenarioId: string, eventType: any, body: Dict, operationId: any) {
    this.events.push({ event_id: eventId, scenario_id: scenarioId, event_type: eventType, body, operation_id: operationId });
  }
  async eventsFor(scenarioId: string) {
    return this.events.filter((e) => e.scenario_id === scenarioId);
  }
}

/** estimate_id・event_id（UUID）と作成時刻は実行ごとに変わるので伏せる。 */
const mask = (value: any): any => {
  if (typeof value === "string") return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value) ? "<uuid>" : value;
  if (Array.isArray(value)) return value.map(mask);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).filter(([k]) => k !== "created_at").map(([k, v]) => [k, mask(v)]));
  return value;
};

function parseQuery(path: string): [string, URLSearchParams] {
  const [p, q] = path.split("?");
  return [p, new URLSearchParams(q ?? "")];
}

async function dispatch(store: MemoryEngineStore, method: string, path: string, body: any): Promise<{ status: number; body: any }> {
  const [p, q] = parseQuery(path);
  const segments = p.split("/").filter(Boolean); // api, ...
  try {
    const isObject = body !== null && typeof body === "object" && !Array.isArray(body);
    const needObject = () => {
      if (!isObject) throw new service.HttpError(422, "<validation>");
    };
    if (method === "GET") {
      if (p === "/api/health") return service.health();
      if (p === "/api/engines") return service.engines();
      if (p === "/api/integrated/schema") return service.integratedSchema(q.get("job_id") ?? undefined);
      if (p === "/api/fixture") {
        const v = q.get("approved_rotor");
        if (v !== null && !["true", "false", "1", "0", "yes", "no", "on", "off", "t", "f", "y", "n"].includes(v.toLowerCase())) throw new service.HttpError(422, "<validation>");
        return service.fixture(v !== null && ["true", "1", "yes", "on", "t", "y"].includes(v.toLowerCase()));
      }
      if (segments[1] === "engines" && segments[3] === "example") {
        const v = q.get("approved_rotor");
        return service.exampleRulePack(segments[2], v === null ? true : ["true", "1", "yes", "on"].includes(v.toLowerCase()));
      }
      if (p === "/api/estimates") {
        const limit = q.get("limit");
        if (limit !== null && !/^[+-]?\d+$/.test(limit)) throw new service.HttpError(422, "<validation>");
        return await service.listEstimates(store, limit === null ? 100 : Number(limit));
      }
      if (segments[1] === "estimates" && segments.length === 3) return await service.getEstimate(store, segments[2]);
    } else {
      needObject();
      if (p === "/api/integrated/evaluate") return service.integratedEvaluate(body);
      if (segments[1] === "engines" && segments[3] === "calculate") return service.calculate(segments[2], body);
      if (p === "/api/compare") return service.compare(body);
      if (p === "/api/estimates") return await service.createEstimate(store, body);
      if (segments[1] === "scenarios" && segments[3] === "events") return await service.addObservationEvent(store, segments[2], body);
    }
    throw new service.HttpError(404, "Not Found");
  } catch (e) {
    if (e instanceof service.HttpError) return { status: e.status, body: { detail: e.detail } };
    throw e;
  }
}

describe("API: 元の FastAPI の応答と一致する", () => {
  const log: any[] = golden("api.json");
  const store = new MemoryEngineStore();
  const ids: string[] = [];
  beforeEach(() => resetEngineState());

  it("操作の記録を順に再生する", async () => {
    resetEngineState();
    for (const [i, step] of log.entries()) {
      let path: string = step.path;
      const m = /\{id:(-?\d+)\}/.exec(path);
      if (m) path = path.replace(m[0], ids.at(Number(m[1]))!);
      const actual = await dispatch(store, step.method, path, step.json);
      if (actual.body && typeof actual.body === "object" && "estimate_id" in actual.body) ids.push(actual.body.estimate_id);
      const label = `${i} ${step.method} ${step.path}`;
      expect(actual.status, label).toBe(step.status);
      if (step.mode === "status") continue;
      if (step.mode === "length") {
        expect(actual.body.length, label).toBe(step.body.length);
        continue;
      }
      if (step.mode === "same_id") {
        expect(actual.body.estimate_id, label).toBe(ids.at(-2));
        continue;
      }
      if (step.mode === "event") {
        expect(actual.body.status, label).toBe("recorded");
        continue;
      }
      if (step.status === 422 && typeof step.body?.detail === "string" && step.body.detail === "<validation>") continue;
      expect(normalize(mask(actual.body)), label).toEqual(normalize(mask(step.body)));
    }
    expect(store.estimates.length).toBeGreaterThan(0);
  });
});

describe("全30案の比較", () => {
  const cases: any[] = golden("compare.json");
  const variants = golden("variants.json");
  for (const c of cases) {
    it(`${c.name}: API の比較と runner の比較が元と一致する`, () => {
      resetEngineState();
      const scenario = variants[c.variant];
      const response = service.compare({ scenario_input: structuredClone(scenario) });
      expect(normalize(response.body.results)).toEqual(normalize(c.expected));
      resetEngineState();
      const runnerResults = compareEngines(structuredClone(scenario), null);
      expect(normalize(runnerResults)).toEqual(normalize(c.runner_expected));
    });
  }
});
