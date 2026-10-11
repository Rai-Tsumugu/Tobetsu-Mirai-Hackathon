import Link from "next/link";
import "./engine.css";

export const metadata = { title: "整備工賃エンジン比較" };

// 元の画面（素の HTML + JS）はそのまま iframe に載せる。API は /api/engine に向けてある。
export default function EnginePage() {
  return (
    <div className="sys-engine">
      <div className="engine-bar">
        <Link href="/">← トップへ戻る</Link>
      </div>
      <iframe src="/api/engine/ui" title="整備工賃エンジン比較" />
    </div>
  );
}
