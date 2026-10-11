// workflow.py: 採用案をつないだ「試算→比較→確定→説明」の統合処理。
import { customer_summary } from "./p12";
import { question_guide } from "./p22";
import { compare_bands } from "./p23";
import { document_payload } from "./p30";
import { calculate, json_ready } from "./pipeline";
import { deepcopy, get, isDict, QuoteError, type Obj } from "./pyrt";
import type { QuoteStore } from "./store";

/** 1回だけ計算し、すべての表示を同じスナップショットから作る（保存しない）。 */
export function preview(inputs: unknown): Obj {
  if (!isDict(inputs)) throw new QuoteError("inputs must be an object");
  const quote = calculate(inputs);
  const questions = question_guide(inputs);
  if (quote.status === "blocked") {
    questions.can_calculate = false;
    questions.status = "blocked";
    const knownPaths = new Set((questions.questions as Obj[]).map((question) => question.field));
    for (const issue of get(quote, "issues", []) as Obj[]) {
      if (!knownPaths.has(issue.path)) {
        questions.questions.push({
          field: issue.path, prompt: issue.message, detail: issue.message, status: "unanswered", answer: null, source_ref: issue.path,
        });
        knownPaths.add(issue.path);
      }
    }
  }
  const canConfirm = quote.status === "proposed";
  return json_ready({
    quote,
    summary: customer_summary(quote),
    band_comparison: canConfirm ? compare_bands(quote) : [],
    questions,
    can_confirm: canConfirm,
    next_action: canConfirm ? "select_band" : "resolve_conditions",
  }) as Obj;
}

/** 保存された版を、再計算せず・後の版の記録を混ぜずに説明する。 */
export async function saved_workflow(store: QuoteStore, quote_id: unknown, quote_version: unknown = null): Promise<Obj> {
  const { quote, communications, changes } = await store.transaction(async () => {
    const found = await store.get_quote(quote_id, quote_version);
    const version = found.quote_version;
    return {
      quote: found,
      communications: (await store.list_communications(quote_id)).filter((event) => event.quote_version === version),
      changes: (await store.list_change_events(quote_id)).filter((event) => event.to_version === version),
    };
  });
  const confirmed = quote.status === "confirmed";
  return json_ready({
    quote: deepcopy(quote),
    summary: customer_summary(quote),
    document: confirmed ? document_payload(quote) : null,
    communications,
    changes,
    next_action: confirmed ? (communications.length ? "review_history" : "explain_and_record") : "select_band",
  }) as Obj;
}
