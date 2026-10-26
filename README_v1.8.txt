Ecliptica Music Companion v1.8 β — ボス拡充 / 独自デスクトップ戦闘HUD
=======================================================

これはソースコードの更新ZIPです。Windows版のEXEはGitHub Actionsでビルドします。
【主な更新点】
・「ボスの曲」を自由入力型から正式なプルダウンに変更。
・Ecliptica Indexに掲載された32体のボス名に加え、旧版のログ名・形態別の候補も保持。
  「一覧にないボスを追加」で手動登録。実ログで検出したボスも一覧に追加します。
・一部の表記揺れを吸収してBGMを探します（例: JimBringer / Jim C. Bringer,
  JackedPumpkin / Jacked O' Lantern）。フェーズ専用曲は優先されます。
・「バトルHUD」タブを新設。任意でWindowsデスクトップ上に小さな常時最前面ウィンドウを表示。
  ボス名、推定ターゲット、直近1〜15秒DPS、ボス戦ダメージ、累計ダメージ、攻撃速度を表示。
  設定した自分の名前が推定ターゲットになったとき警告音。解除や他人同士の変更音も設定可能。
  HUDの不透明度・警告音量・位置（ドラッグ）を変更できます。
・従来のBGM再生・設定は引き続き1つの統合ウィンドウ内で操作できます。

【重要な制約】
・戦闘HUDは本アプリ独自の実装であり、添付された EclipticaOverlay の改変・組込みではありません。
  EclipticaOverlay の作者は同ツールの無断再配布・改変・再配布を禁止しています。
  本ZIPには同ツール本体・ソース・素材を含めていません。
・このHUDは Windows デスクトップ用。SteamVR / HMD 内のネイティブ表示には未対応です。
・ダメージ/ターゲットの検出はベータ版です。実際の ECLIPTICA の VRChat ログサンプルが
  提供されていないため、現行のログの全形式との互換性は保証できません。
  明示されたECLIPTICAログのボス名・damage / STRIKE・target / aggro / hate / ownership の
  パターンを認識します。認識できない形式ではゼロまたは未検出のままになります。
・「狙われている」はログに基づく推定です。正確な戦闘判定ではありません。
・VRChatの 設定 → デバッグ → ログ出力 → 完全 を有効にしてください。
  情報が足りない場合は VRChat の Udon デバッグログの有効化も必要なことがあります。
・HUDはユーザーがONにした時のみ追加表示します。オフ時は従来どおり再生/設定の1画面のみ。
・Windowsの排他フルスクリーン上にはデスクトップHUDが表示されない場合があります。

【更新方法】
1. GitHubのリポジトリに、このZIPの下記ファイルをそれぞれ上書き・追加してください。
   EclipticaMusic.py
   combat_meter.py       ← 新規ファイル。必ず追加。
   unified.html
   player.html
   engine.js
   requirements.txt
   build_windows.bat
   .github/workflows/build.yml
2. GitHub Actions -> Build Windows App -> Run workflow を実行。
3. Artifacts -> EclipticaMusicCompanion-Windows-v1.8 を取得。
4. ZIPを「すべて展開」。EclipticaMusicCompanion.exeを起動。
   _internalフォルダーはexeと同じ場所に保管してください。
5. 左の「ボスの曲」からボスをプルダウン選択。
6. 左の「バトルHUD」からユーザー名を設定し、HUDをONにして保存。
7. 自分にタゲが向いた際の警告音を「警告音を試す」で確認。

【設定の引継ぎ】
%LOCALAPPDATA%\EclipticaMusicCompanion\settings.json をそのまま使います。
既存のボス・難易度・音楽・ロビー・音量の設定は引継ぎ対象です。
アップデート前に「その他 → バックアップ」をお勧めします。

【検証状況】
Pythonの構文検証、ブラウザJavaScript構文チェック、模擬ログによるダメージ/DPS/タゲ通知、
仮想ディスプレイ上でのTkinterのHUD表示・設定API・閉じる処理は成功しました。
Windows実機、YouTube再生、実際のVRChatログ、SteamVRでの動作は未検証です。

【ボス名称の参考】
Ecliptica Index: https://eclipticaindex.com/database/bosses/
