// registry.py の移植: 30案のモジュールを案IDで引く。
import type { Json, Store } from "./core";
import { ValidationError } from "./core";
import * as m01 from "./m01";
import * as m02 from "./m02";
import * as m03 from "./m03";
import * as m04 from "./m04";
import * as m05 from "./m05";
import * as m06 from "./m06";
import * as m07 from "./m07";
import * as m08 from "./m08";
import * as m09 from "./m09";
import * as m10 from "./m10";
import * as m11 from "./m11";
import * as m12 from "./m12";
import * as m13 from "./m13";
import * as m14 from "./m14";
import * as m15 from "./m15";
import * as m16 from "./m16";
import * as m17 from "./m17";
import * as m18 from "./m18";
import * as m19 from "./m19";
import * as m20 from "./m20";
import * as m21 from "./m21";
import * as m22 from "./m22";
import * as m23 from "./m23";
import * as m24 from "./m24";
import * as m25 from "./m25";
import * as m26 from "./m26";
import * as m27 from "./m27";
import * as m28 from "./m28";
import * as m29 from "./m29";
import * as m30 from "./m30";

export type IdeaSpec = { idea_id: string; title: string; description: string; defaults: Json };
export type IdeaModule = { SPEC: IdeaSpec; run: (payload: unknown, store: Store) => Promise<Json> };

const MODULES: Record<string, IdeaModule> = {
  M01: m01,
  M02: m02,
  M03: m03,
  M04: m04,
  M05: m05,
  M06: m06,
  M07: m07,
  M08: m08,
  M09: m09,
  M10: m10,
  M11: m11,
  M12: m12,
  M13: m13,
  M14: m14,
  M15: m15,
  M16: m16,
  M17: m17,
  M18: m18,
  M19: m19,
  M20: m20,
  M21: m21,
  M22: m22,
  M23: m23,
  M24: m24,
  M25: m25,
  M26: m26,
  M27: m27,
  M28: m28,
  M29: m29,
  M30: m30,
};

export const IDEA_IDS = Object.keys(MODULES);

/** module_for(): 案IDが M01〜M30 でなければ止める。 */
export async function moduleFor(ideaId: string): Promise<IdeaModule> {
  if (!Object.prototype.hasOwnProperty.call(MODULES, ideaId)) {
    throw new ValidationError("案IDが不正です");
  }
  return MODULES[ideaId];
}

/** specifications(): 30案の SPEC（名称・説明・架空の既定入力）。 */
export function specifications(): IdeaSpec[] {
  return IDEA_IDS.map((ideaId) => MODULES[ideaId].SPEC);
}
