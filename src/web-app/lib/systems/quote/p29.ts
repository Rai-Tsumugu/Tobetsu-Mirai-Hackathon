// P29: 追加変更（版の間の差と顧客の了承）を追記で記録する。
import { compare_versions } from "./p26";
import { deepcopy, get, has, isDict, isInt, KeyErr, nowIso, pyEq, QuoteError, uuid4, ValueErr, type Obj } from "./pyrt";
import type { QuoteStore } from "./store";

const ALLOWED = [
  "quote_id", "from_version", "to_version", "trigger_ref", "operator",
  "condition_note", "ack_status", "communicated_amount", "communication_id",
];

export async function record_change(store: QuoteStore, data: unknown): Promise<Obj> {
  if (!isDict(data)) throw new QuoteError("data must be an object");
  const clean: Obj = {};
  for (const key of ALLOWED) if (has(data, key)) clean[key] = deepcopy(data[key]);
  for (const key of ["quote_id", "trigger_ref", "operator", "condition_note", "ack_status"]) {
    const value = get(clean, key);
    if (typeof value !== "string" || !value.trim()) throw new QuoteError(`${key} is required`);
  }
  if (!["pending", "accepted", "declined"].includes(clean.ack_status)) throw new QuoteError("ack_status must be pending, accepted, or declined");
  for (const key of ["from_version", "to_version"]) {
    const value = get(clean, key);
    if (!isInt(value) || value < 1) throw new QuoteError(`${key} must be a positive integer`);
  }
  if (clean.to_version <= clean.from_version) throw new QuoteError("to_version must be greater than from_version");

  return store.transaction(async () => {
    let oldQuote: Obj;
    let newQuote: Obj;
    try {
      oldQuote = await store.get_quote(clean.quote_id, clean.from_version);
      newQuote = await store.get_quote(clean.quote_id, clean.to_version);
    } catch (error) {
      if (error instanceof ValueErr || error instanceof KeyErr) throw new QuoteError("both persisted quote versions are required");
      throw error;
    }
    if (!pyEq(get(oldQuote, "quote_id"), get(newQuote, "quote_id"))) throw new QuoteError("quote versions must belong to the same quote");
    const diff = compare_versions(oldQuote, newQuote);

    let communication: Obj | null = null;
    const communicationId = get(clean, "communication_id");
    if (clean.ack_status === "accepted" && !communicationId) throw new QuoteError("accepted changes require a saved communication_id");
    if (communicationId !== null) {
      if (typeof communicationId !== "string" || !communicationId.trim()) throw new QuoteError("communication_id must be a non-empty string");
      communication = (await store.list_communications(clean.quote_id)).find((entry) => get(entry, "communication_id") === communicationId) ?? null;
      if (communication === null) throw new QuoteError("communication_id must reference a saved communication");
      if (get(communication, "quote_id") !== clean.quote_id || get(communication, "quote_version") !== clean.to_version) {
        throw new QuoteError("communication must reference the new quote version");
      }
      if (!pyEq(get(communication, "condition_note"), clean.condition_note)) throw new QuoteError("communication condition must match the change event");
      if (!pyEq(get(communication, "customer_ref"), get(newQuote, "customer_ref")) || !pyEq(get(communication, "vehicle_ref"), get(newQuote, "vehicle_ref"))) {
        throw new QuoteError("communication customer references must match the new quote");
      }
      if (has(clean, "communicated_amount") && !pyEq(clean.communicated_amount, get(communication, "communicated_amount"))) {
        throw new QuoteError("communicated_amount must match the saved communication");
      }
      clean.communicated_amount = deepcopy(get(communication, "communicated_amount"));
    } else if (has(clean, "communicated_amount")) {
      throw new QuoteError("communicated_amount requires a saved communication");
    }
    if (clean.ack_status === "accepted" && communication === null) throw new QuoteError("accepted changes require a matching saved communication");
    const event: Obj = {
      event_id: uuid4(),
      quote_id: clean.quote_id,
      from_version: clean.from_version,
      to_version: clean.to_version,
      trigger_ref: clean.trigger_ref,
      delta_lines: { added: deepcopy(diff.added), removed: deepcopy(diff.removed), changed: deepcopy(diff.changed) },
      amount_delta: deepcopy(diff.amount_delta),
      condition_note: clean.condition_note,
      operator: clean.operator,
      ack_status: clean.ack_status,
      work_status: clean.ack_status === "pending" ? "pending" : clean.ack_status === "declined" ? "blocked" : "continue",
      timestamp: nowIso(),
    };
    if (has(clean, "communicated_amount")) event.communicated_amount = deepcopy(clean.communicated_amount);
    if (communication !== null) event.communication_id = communicationId;
    return store.append_change_event(event);
  });
}

export async function list_change_events(store: QuoteStore, quote_id: unknown): Promise<Obj[]> {
  return deepcopy(await store.list_change_events(quote_id));
}
