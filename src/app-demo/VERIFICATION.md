# 検証記録

検証日：2026-10-11（日本時間）

- `npm run build`：TypeScript型チェックとVite本番ビルドに成功。
- `python -m unittest discover -s backend -p 'test_*.py' -v`：6件成功。
- `backend/check_browser.py`：PlaywrightからローカルのGoogle Chromeをheadlessで使用し、成功。
- 1440pxデスクトップ幅、390pxスマートフォン幅のスクリーンショットを確認。スマートフォン幅で横はみ出しなし。
- JavaScriptのpageerrorなし。履歴ダイアログをEscapeで閉じる動作を確認。

ブラウザで確認した流れ：

1. シビック・FL4の検索、年式と仕様の選択。
2. フロントブレーキパッド交換を選択し、候補4件を表示。
3. 中央値6,000円、Cを除外して5,500円、全除外して算出不可。
4. 手入力7,000円＋部品代12,000円、調整理由入力、税1,900円、合計20,900円。
5. SQLite保存、ページ再読み込み、履歴のFL4検索、詳細表示。
6. 保存当時の条件を再利用し、確定工賃7,000円を復元。

検証のDBは `/tmp/repair-browser-42ffa7.sqlite3`。通常起動時の `demo.sqlite3` と分離しています。

SQLite接続の解放漏れをテスト中に修正し、再検証済みです。FastAPI/Starletteのテストクライアントがhttpx利用に関する非推奨警告を出しますが、テストは成功しています。

外部API、メーカー資料との諸元照合、実車への適合、公開環境、Safari/Firefoxは未検証・対象外です。
