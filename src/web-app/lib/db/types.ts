// numeric 列は丸めを避けるため文字列のまま扱う（例: "1.5"）。入力は数値も受け付ける。
export type DecimalString = string;
export type DecimalInput = string | number;

export const BANDS = ["low", "typical", "high"] as const;
export type Band = (typeof BANDS)[number];
export type BandRange<T = DecimalString> = Record<Band, T>;

export type JsonObject = { [key: string]: unknown };

export const ITEM_CATEGORIES = ["部品", "塗料", "溶剤", "消耗品"] as const;
export type ItemCategory = (typeof ITEM_CATEGORIES)[number];

export const PRICE_TYPES = ["仕入", "販売"] as const;
export type PriceType = (typeof PRICE_TYPES)[number];

export const QUOTE_LINE_KINDS = ["labor", "parts", "materials", "adjustment", "discount"] as const;
export type QuoteLineKind = (typeof QUOTE_LINE_KINDS)[number];

export const QUOTE_STATUSES = ["calculated", "proposed", "confirmed", "blocked"] as const;
export type QuoteStatus = (typeof QUOTE_STATUSES)[number];
