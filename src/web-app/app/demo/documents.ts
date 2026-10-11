// 元: src/app-demo/frontend/src/documents.ts（変更なし）。ブラウザ内で帳票 PDF を作る。
import type { EstimateCase } from "./CasesDashboard";

type DocumentEstimate = {
  id: string;
  case_id: string;
  year: number;
  grade: string;
  vehicle: { maker: string; model: string; model_code: string };
  items: {
    name: string;
    conditions: string;
    labor_price: number;
    parts_price: number;
  }[];
  labor_total: number;
  parts_total: number;
  tax_rate: number;
  subtotal: number;
  tax_amount: number;
  total_amount: number;
};
const yen = (n: number) =>
  new Intl.NumberFormat("ja-JP", { style: "currency", currency: "JPY" }).format(
    n,
  );
const encoder = new TextEncoder();

// Embed browser-rendered A4 pages as JPEG images. Japanese uses the same local
// fonts as the UI; no names, notes, or amounts leave the browser for PDF creation.
function makePdf(pages: HTMLCanvasElement[]): Blob {
  const objects: Uint8Array[] = [];
  const bytes = (s: string) => encoder.encode(s);
  const join = (chunks: Uint8Array[]) => {
    const out = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
    let offset = 0;
    for (const chunk of chunks) {
      out.set(chunk, offset);
      offset += chunk.length;
    }
    return out;
  };
  objects.push(bytes("<< /Type /Catalog /Pages 2 0 R >>"));
  objects.push(
    bytes(
      `<< /Type /Pages /Count ${pages.length} /Kids [${pages.map((_, i) => `${3 + i * 3} 0 R`).join(" ")}] >>`,
    ),
  );
  pages.forEach((canvas, i) => {
    const pageId = 3 + i * 3;
    const imageId = pageId + 1;
    const contentId = pageId + 2;
    objects.push(
      bytes(
        `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] /Resources << /XObject << /Image ${imageId} 0 R >> >> /Contents ${contentId} 0 R >>`,
      ),
    );
    const binary = atob(canvas.toDataURL("image/jpeg", 0.94).split(",")[1]);
    const jpeg = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    objects.push(
      join([
        bytes(
          `<< /Type /XObject /Subtype /Image /Width ${canvas.width} /Height ${canvas.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>\nstream\n`,
        ),
        jpeg,
        bytes("\nendstream"),
      ]),
    );
    const commands = "q\n595.28 0 0 841.89 0 0 cm\n/Image Do\nQ\n";
    objects.push(
      bytes(
        `<< /Length ${bytes(commands).length} >>\nstream\n${commands}endstream`,
      ),
    );
  });
  const chunks = [bytes("%PDF-1.4\n")];
  const offsets = [0];
  let size = chunks[0].length;
  objects.forEach((object, i) => {
    offsets.push(size);
    const chunk = join([
      bytes(`${i + 1} 0 obj\n`),
      object,
      bytes("\nendobj\n"),
    ]);
    chunks.push(chunk);
    size += chunk.length;
  });
  chunks.push(
    bytes(
      `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets
        .slice(1)
        .map((n) => `${String(n).padStart(10, "0")} 00000 n \n`)
        .join(
          "",
        )}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${size}\n%%EOF\n`,
    ),
  );
  return new Blob([join(chunks).buffer as ArrayBuffer], {
    type: "application/pdf",
  });
}

export async function downloadDocument(
  c: EstimateCase,
  estimate: DocumentEstimate,
  kind: "estimate" | "invoice",
) {
  if (!c.recipient_name.trim())
    throw new Error("案件の編集で宛名を入力してください。");
  if (estimate.case_id !== c.id || estimate.id !== c.latest_estimate_id)
    throw new Error("案件と見積もりの紐付けを確認してください。");
  await document.fonts.ready;
  const title = kind === "estimate" ? "見積書" : "請求書";
  const number = `${kind === "estimate" ? "EST" : "INV"}-${estimate.id}`;
  const issued = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const pages: HTMLCanvasElement[] = [];
  let ctx!: CanvasRenderingContext2D;
  let y = 0;
  const font = (size = 14, bold = false) => {
    ctx.font = `${bold ? "600" : "400"} ${size}px "Hiragino Kaku Gothic ProN", "Yu Gothic", "Meiryo", sans-serif`;
  };
  function text(
    value: string,
    x: number,
    at: number,
    size = 14,
    bold = false,
    align: CanvasTextAlign = "left",
  ) {
    font(size, bold);
    ctx.fillStyle = "#253c53";
    ctx.textAlign = align;
    ctx.fillText(value, x, at);
    ctx.textAlign = "left";
  }
  function line(at: number) {
    ctx.strokeStyle = "#d5e0ea";
    ctx.beginPath();
    ctx.moveTo(48, at);
    ctx.lineTo(746, at);
    ctx.stroke();
  }
  function page() {
    const canvas = document.createElement("canvas");
    canvas.width = 1588;
    canvas.height = 2246;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("PDFを作成できませんでした。");
    ctx = context;
    ctx.scale(2, 2);
    ctx.fillStyle = "white";
    ctx.fillRect(0, 0, 794, 1123);
    pages.push(canvas);
    text(title, 48, 78, 30, true);
    text("当別整備ワークベンチ（デモ）", 746, 65, 15, true, "right");
    text("整備・修理の帳票サンプル", 746, 89, 11, false, "right");
    line(108);
    y = 139;
    text(`帳票番号 ${number}`, 48, y, 11);
    text(`発行日 ${issued}`, 746, y, 11, false, "right");
    y += 27;
  }
  function ensure(height: number) {
    if (y + height > 1030) page();
  }
  function paragraph(value: string, size = 14, bold = false) {
    for (const raw of value.replaceAll("\r", "").split("\n")) {
      let segment = "";
      for (const char of Array.from(raw)) {
        font(size, bold);
        if (segment && ctx.measureText(segment + char).width > 698) {
          ensure(size + 12);
          text(segment, 48, y, size, bold);
          y += size + 9;
          segment = "";
        }
        segment += char;
      }
      ensure(size + 12);
      text(segment, 48, y, size, bold);
      y += size + 9;
    }
  }
  page();
  const recipient = /(?:様|御中)$/.test(c.recipient_name.trim())
    ? c.recipient_name.trim()
    : c.recipient_name.trim() + " 様";
  paragraph(recipient, 22, true);
  y += 9;
  paragraph(
    kind === "estimate"
      ? "下記のとおりお見積もりいたします。"
      : "下記のとおりご請求申し上げます。",
    12,
  );
  ensure(86);
  ctx.fillStyle = "#eef5fb";
  ctx.fillRect(48, y, 698, 70);
  text(
    kind === "estimate" ? "お見積金額（税込）" : "ご請求金額（税込）",
    65,
    y + 27,
    14,
  );
  text(yen(estimate.total_amount), 728, y + 48, 29, true, "right");
  y += 99;
  paragraph(`案件名：${c.title}`, 14, true);
  paragraph(`案件ID：${c.id}`, 10);
  paragraph(
    `車両：${estimate.vehicle.maker} ${estimate.vehicle.model} / ${estimate.vehicle.model_code}`,
    13,
  );
  paragraph(`年式・仕様：${estimate.year}年 / ${estimate.grade}`, 12);
  paragraph(`納期：${c.due_date?.replaceAll("-", "/") || "未設定"}`, 12);
  y += 13;
  function tableHeader() {
    ensure(42);
    ctx.fillStyle = "#173b63";
    ctx.fillRect(48, y, 698, 32);
    font(12, true);
    ctx.fillStyle = "white";
    ctx.fillText("作業明細", 60, y + 22);
    ctx.textAlign = "right";
    for (const [label, x] of [
      ["工賃（税抜）", 478],
      ["部品代（税抜）", 610],
      ["小計（税抜）", 732],
    ] as const)
      ctx.fillText(label, x, y + 22);
    ctx.textAlign = "left";
    y += 54;
  }
  tableHeader();
  for (const item of estimate.items) {
    if (y + 65 > 1030) {
      page();
      tableHeader();
    }
    font(13, true);
    const chars = Array.from(item.name);
    let titleLine = "";
    for (const char of chars) {
      if (ctx.measureText(titleLine + char).width > 310) {
        ensure(26);
        text(titleLine, 60, y, 13, true);
        y += 23;
        titleLine = "";
      }
      titleLine += char;
    }
    ensure(34);
    text(titleLine, 60, y, 13, true);
    text(yen(item.labor_price), 478, y, 13, false, "right");
    text(yen(item.parts_price), 610, y, 13, false, "right");
    text(yen(item.labor_price + item.parts_price), 732, y, 13, true, "right");
    y += 28;
    if (item.conditions) paragraph(`作業条件：${item.conditions}`, 11);
    ensure(17);
    line(y);
    y += 22;
  }
  ensure(185);
  y += 12;
  for (const [label, value] of [
    ["工賃合計", estimate.labor_total],
    ["部品代合計", estimate.parts_total],
    ["税抜合計", estimate.subtotal],
    [`消費税（${Math.round(estimate.tax_rate * 100)}%）`, estimate.tax_amount],
    ["税込合計", estimate.total_amount],
  ] as const) {
    text(label, 490, y, 13, label === "税込合計");
    text(yen(value), 732, y, 15, label === "税込合計", "right");
    y += 29;
  }
  y += 15;
  paragraph(
    "備考：記載した作業・条件を対象としたデモ帳票です。追加作業・未記載の条件は別途確認してください。",
    11,
  );
  pages.forEach((canvas, i) => {
    ctx = canvas.getContext("2d")!;
    line(1064);
    text("デモ帳票 / 発行元・支払条件・振込先は未設定", 48, 1086, 10);
    text(`${i + 1} / ${pages.length}`, 746, 1086, 10, false, "right");
  });
  const url = URL.createObjectURL(makePdf(pages));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${kind}-${estimate.id}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
