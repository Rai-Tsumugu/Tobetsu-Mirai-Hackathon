// メモリ上の Store（元の Store(':memory:') 相当）。ゴールデン照合テストで使う。
// 保存は JSON 文字列で持ち、読むたびに解釈し直す（SQLite の payload 列と同じ）。
import { Store, type Json, type PriceVersion } from "./core";
import { dumps, uuidHex } from "./py";

type RecordRow = { namespace: string; record_id: string; payload: string };
type PriceRow = { item_id: string; price_type: string; supplier_id: string; payload: string };

export class MemoryStore extends Store {
  private recordRows: RecordRow[] = [];
  private priceRows: PriceRow[] = [];

  async transaction<T>(fn: () => Promise<T>): Promise<T> {
    const records = this.recordRows.length;
    const prices = this.priceRows.length;
    try {
      return await fn();
    } catch (error) {
      this.recordRows.length = records;
      this.priceRows.length = prices;
      throw error;
    }
  }

  protected newId(): string {
    return uuidHex();
  }

  protected async insertRecord(namespace: string, recordId: string, payload: string): Promise<void> {
    this.recordRows.push({ namespace, record_id: recordId, payload });
  }

  protected async selectRecords(namespace: string, recordId: string | null): Promise<{ record_id: string; payload: Json }[]> {
    return this.recordRows
      .filter((row) => row.namespace === namespace && (recordId === null || row.record_id === recordId))
      .map((row) => ({ record_id: row.record_id, payload: JSON.parse(row.payload) as Json }));
  }

  protected async insertPrice(version: PriceVersion): Promise<string> {
    const id = uuidHex();
    const payload = dumps({ ...version, price_version_id: id });
    this.priceRows.push({
      item_id: version.item.item_id,
      price_type: version.item.price_type,
      supplier_id: version.supplier_id,
      payload,
    });
    return id;
  }

  protected async selectPrices(itemId: string | null, priceType: string | null, supplierId: string | null): Promise<PriceVersion[]> {
    return this.priceRows
      .filter(
        (row) =>
          (itemId === null || row.item_id === itemId) &&
          (priceType === null || row.price_type === priceType) &&
          (supplierId === null || row.supplier_id === supplierId),
      )
      .map((row) => JSON.parse(row.payload) as PriceVersion);
  }
}
