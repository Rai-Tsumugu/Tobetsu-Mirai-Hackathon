// api.py（FastAPI）の移植。パス・メソッド・入出力 JSON・ステータスコードを元に合わせる。
// ルートの照合は Starlette と同じく上から順に行い、パスだけ一致したら 405、どれにも一致しなければ 404。
import teams from "../../../../auto_repair_quote/teams.json";
import { demo_inputs } from "./fixtures";
import { confirm_quote } from "./p14";
import { form_state } from "./p13";
import { revise_quote } from "./p15";
import { quick_quote } from "./p16";
import { resume_draft, save_draft } from "./p17";
import { record_communication } from "./p18";
import { load_preset } from "./p19";
import { search_jobs } from "./p20";
import { search_quotes } from "./p21";
import { question_guide } from "./p22";
import { compare_bands } from "./p23";
import { price_comparison } from "./p24";
import { combine_quotes } from "./p25";
import { compare_versions } from "./p26";
import { save_snapshot } from "./p27";
import { communication_ledger } from "./p28";
import { record_change } from "./p29";
import { document_payload } from "./p30";
import { customer_summary } from "./p12";
import { calculate, json_ready } from "./pipeline";
import { deepcopy, errorKind, get, IntegrityErr, isDict, item, KeyErr, PyError, TypeErr, uuid4Hex, ValueErr, type Obj } from "./pyrt";
import type { QuoteStore } from "./store";
import { preview, saved_workflow } from "./workflow";

export type ApiResponse = { status: number; json?: unknown; text?: string };

type Ctx = { store: QuoteStore; params: Record<string, string>; query: URLSearchParams; body: () => Obj };
type Route = { method: "GET" | "POST"; path: string; handler: (ctx: Ctx) => Promise<unknown> | unknown };

const DUPLICATE_DETAIL = "既存の見積版またはイベントIDです。上書きせず新しい版を作成してください。";

class RequestValidationError extends Error {
  constructor(public detail: unknown[]) {
    super("request validation");
  }
}

/** quote_version: int | None = None（FastAPI のクエリ検証）。 */
function optionalInt(query: URLSearchParams, name: string): number | null {
  const raw = query.get(name);
  if (raw === null) return null;
  if (!/^\s*[+-]?\d+\s*$/.test(raw)) {
    throw new RequestValidationError([
      { type: "int_parsing", loc: ["query", name], msg: "Input should be a valid integer, unable to parse string as an integer", input: raw },
    ]);
  }
  return Number(raw.trim());
}

function needDict(value: unknown, method: string): Obj {
  if (!isDict(value)) throw new TypeErr(`'${Array.isArray(value) ? "list" : typeof value}' object has no attribute '${method}'`);
  return value;
}

function withIdentity(inputs: unknown, quoteId: unknown, quoteVersion: unknown): Obj {
  const copy = needDict(deepcopy(inputs), "update");
  copy.quote_id = quoteId;
  copy.quote_version = quoteVersion;
  return copy;
}

const ROUTES: Route[] = [
  { method: "POST", path: "/api/workflow/preview", handler: ({ body }) => preview(item(body(), "inputs")) },
  {
    method: "GET",
    path: "/api/workflow/{quote_id}",
    handler: ({ store, params, query }) => saved_workflow(store, params.quote_id, optionalInt(query, "quote_version")),
  },
  {
    method: "POST",
    path: "/api/forms/state",
    handler: ({ body }) => {
      const data = body();
      return form_state(item(data, "inputs"), get(data, "step", 0), get(data, "quote"));
    },
  },
  {
    method: "POST",
    path: "/api/questions",
    handler: ({ body }) => {
      const data = body();
      return question_guide(item(data, "inputs"), get(data, "required_fields"));
    },
  },
  {
    method: "POST",
    path: "/api/prices/compare",
    handler: ({ body }) => {
      const data = body();
      return price_comparison(item(data, "history"), item(data, "item_id"));
    },
  },
  {
    method: "POST",
    path: "/api/quotes/combine",
    handler: ({ body }) => {
      const data = body();
      return combine_quotes(item(data, "quotes"), get(data, "accepted_dedup_refs"), get(data, "approved_by"));
    },
  },
  {
    method: "POST",
    path: "/api/changes",
    handler: ({ store, body }) => {
      const data = body();
      return store.transaction(async () => {
        try {
          await store.get_quote(item(data, "quote_id"), item(data, "to_version"));
        } catch (error) {
          if (!(error instanceof ValueErr)) throw error;
          const inputs = withIdentity(item(data, "inputs"), item(data, "quote_id"), item(data, "to_version"));
          const proposed = calculate(inputs);
          if (proposed.status === "blocked") throw new ValueErr("blocked changes cannot be recorded as a calculated quote");
          proposed.parent_version = item(data, "from_version");
          await store.save_quote(proposed);
        }
        return record_change(store, data);
      });
    },
  },
  { method: "GET", path: "/api/quotes/{quote_id}/changes", handler: ({ store, params }) => store.list_change_events(params.quote_id) },
  {
    method: "GET",
    path: "/api/demo",
    handler: () => ({
      ...demo_inputs(),
      quote_id: "Q-" + uuid4Hex().slice(0, 10),
      customer_ref: "C-DEMO-01",
      vehicle_ref: "V-DEMO-01",
      job_ref: "JOB-DEMO-01",
    }),
  },
  { method: "GET", path: "/api/jobs", handler: async ({ store, query }) => search_jobs(await store.list_presets(), query.get("query") ?? "") },
  {
    method: "POST",
    path: "/api/presets/load",
    handler: async ({ store, body }) => {
      const data = body();
      const result = load_preset(await store.list_presets(), item(data, "preset_id"));
      result.inputs.quote_id = "Q-" + uuid4Hex().slice(0, 10);
      return result.inputs;
    },
  },
  {
    method: "POST",
    path: "/api/quotes/quick",
    handler: async ({ store, body }) => {
      const data = body();
      return quick_quote(await store.list_presets(), item(data, "preset_id"), get(data, "vehicle_ref"));
    },
  },
  { method: "POST", path: "/api/quotes/calculate", handler: ({ body }) => calculate(body()) },
  {
    method: "POST",
    path: "/api/quotes/confirm",
    handler: ({ store, body }) => {
      const data = body();
      return store.transaction(async () => {
        const inputs = withIdentity(item(data, "inputs"), item(data, "quote_id"), item(data, "quote_version"));
        let previous: Obj | null;
        try {
          previous = await store.get_quote(data.quote_id, data.quote_version);
        } catch (error) {
          if (!(error instanceof ValueErr)) throw error;
          previous = null;
        }
        if (previous !== null) {
          if (get(previous, "status") === "confirmed") throw new ValueErr("already confirmed: create a new version first");
          inputs.parent_version = data.quote_version;
          inputs.quote_version = item(await store.get_quote(data.quote_id), "quote_version") + 1;
        }
        let quote = calculate(inputs);
        quote = confirm_quote(
          quote,
          item(data, "selected_band"),
          item(data, "confirmed_by"),
          get(data, "final_amount"),
          get(data, "override_reason"),
        );
        return save_snapshot(store, quote);
      });
    },
  },
  {
    method: "GET",
    path: "/api/quotes",
    handler: ({ store, query }) => search_quotes(store, query.get("customer_ref"), query.get("vehicle_ref")),
  },
  {
    method: "POST",
    path: "/api/quotes/revise",
    handler: ({ store, body }) => {
      const data = body();
      const inputs = deepcopy(item(data, "inputs"));
      if (!isDict(inputs)) throw new TypeErr("object does not support item assignment");
      inputs.quote_id = item(data, "quote_id");
      return revise_quote(store, data.quote_id, item(data, "from_version"), inputs, calculate);
    },
  },
  {
    method: "POST",
    path: "/api/drafts/save",
    handler: ({ store, body }) => {
      const data = body();
      return save_draft(store, item(data, "draft_id"), item(data, "inputs"), get(data, "step", 0));
    },
  },
  {
    method: "POST",
    path: "/api/drafts/resume",
    handler: ({ store, body }) => {
      const data = body();
      return resume_draft(store, item(data, "draft_id"), item(data, "resume_mode"), demo_inputs());
    },
  },
  {
    method: "POST",
    path: "/api/communications",
    handler: ({ store, body }) => {
      const data = body();
      return store.transaction(async () => {
        let quote: Obj;
        try {
          quote = await store.get_quote(item(data, "quote_id"), item(data, "quote_version"));
        } catch (error) {
          if (!(error instanceof ValueErr)) throw error;
          const inputs = withIdentity(item(data, "inputs"), data.quote_id, data.quote_version);
          quote = calculate(inputs);
          if (quote.status === "blocked") throw new ValueErr("blocked quote cannot be communicated");
          await store.save_quote(json_ready(quote));
        }
        return record_communication(store, quote, data);
      });
    },
  },
  {
    method: "GET",
    path: "/api/quotes/{quote_id}/communications",
    handler: ({ store, params }) => communication_ledger(store, params.quote_id),
  },
  {
    method: "POST",
    path: "/api/quotes/summary",
    handler: ({ body }) => {
      const data = body();
      return customer_summary(item(data, "quote"), get(data, "selected_band"));
    },
  },
  { method: "POST", path: "/api/quotes/compare-bands", handler: ({ body }) => compare_bands(item(body(), "quote")) },
  {
    method: "POST",
    path: "/api/quotes/diff",
    handler: ({ body }) => {
      const data = body();
      return compare_versions(item(data, "from_quote"), item(data, "to_quote"));
    },
  },
  {
    method: "GET",
    path: "/api/quotes/{quote_id}/document",
    handler: async ({ store, params, query }) =>
      document_payload(await store.get_quote(params.quote_id, optionalInt(query, "quote_version"))),
  },
  {
    method: "GET",
    path: "/api/quotes/{quote_id}",
    handler: ({ store, params, query }) => store.get_quote(params.quote_id, optionalInt(query, "quote_version")),
  },
  { method: "GET", path: "/api/teams", handler: () => deepcopy(teams) },
];

function matchPath(pattern: string, path: string): Record<string, string> | null {
  const names: string[] = [];
  const regex = new RegExp(
    "^" + pattern.replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\{(\w+)\}/g, (_, name: string) => {
      names.push(name);
      return "([^/]+)";
    }) + "$",
  );
  const match = regex.exec(path);
  if (!match) return null;
  const params: Record<string, string> = {};
  names.forEach((name, index) => {
    params[name] = decodeURIComponent(match[index + 1]);
  });
  return params;
}

function parseBody(text: string | undefined): Obj {
  if (text === undefined || text === "") {
    throw new RequestValidationError([{ type: "missing", loc: ["body"], msg: "Field required", input: null }]);
  }
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (error) {
    throw new RequestValidationError([
      { type: "json_invalid", loc: ["body", 0], msg: "JSON decode error", input: {}, ctx: { error: String((error as Error).message) } },
    ]);
  }
  if (!isDict(value)) {
    throw new RequestValidationError([{ type: "dict_type", loc: ["body"], msg: "Input should be a valid dictionary", input: value }]);
  }
  return value;
}

/**
 * 1リクエストを処理する。path は "/api/..."（元の API のパス）とクエリ文字列。
 * store の書き込みは呼び出し側のトランザクションで包む（失敗時は途中の保存も取り消す）。
 */
export async function handleQuoteApi(store: QuoteStore, method: string, url: string, bodyText?: string): Promise<ApiResponse> {
  const [rawPath, rawQuery = ""] = url.split("?", 2);
  const path = rawPath;
  let methodMismatch = false;
  for (const route of ROUTES) {
    const params = matchPath(route.path, path);
    if (params === null) continue;
    if (route.method !== method.toUpperCase()) {
      methodMismatch = true;
      continue;
    }
    let parsedBody: Obj | null = null;
    const ctx: Ctx = {
      store,
      params,
      query: new URLSearchParams(rawQuery),
      body: () => (parsedBody ??= parseBody(bodyText)),
    };
    try {
      if (route.method === "POST") ctx.body();
      const result = await route.handler(ctx);
      return { status: 200, json: result };
    } catch (error) {
      return errorResponse(error);
    }
  }
  if (methodMismatch) return { status: 405, json: { detail: "Method Not Allowed" } };
  return { status: 404, json: { detail: "Not Found" } };
}

function errorResponse(error: unknown): ApiResponse {
  if (error instanceof RequestValidationError) return { status: 422, json: { detail: error.detail } };
  if (error instanceof IntegrityErr) return { status: 409, json: { detail: DUPLICATE_DETAIL } };
  if (error instanceof KeyErr) return { status: 422, json: { detail: "必須項目がありません: " + error.message } };
  if (error instanceof ValueErr) return { status: 422, json: { detail: error.message } };
  if (error instanceof PyError || error instanceof TypeError) {
    console.error("quote api error", errorKind(error), error);
    return { status: 500, text: "Internal Server Error" };
  }
  throw error;
}
