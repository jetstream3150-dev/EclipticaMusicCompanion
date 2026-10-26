Ecliptica Music Companion v1.7 beta — 1ウィンドウ統合版
==========================================================

変更点
- 操作画面（従来のTkinter）と再生画面（Edge）を統合。通常、Edgeのアプリウィンドウ1つだけが開きます。
- 初回の「音楽をスタートする」でブラウザの再生を有効化し、VRChatログ監視を開始します。
- ホーム / 曲を設定 / ボスの曲 / その他を画面左側から切り替えられます。
- 画面右側にプレイヤーの接続状態・音量・現在の曲を常時表示します。
- 曲設定、ボス設定、ロビー曲、予備MP3、試聴/停止、バックアップ・復元、許可済みMP3変換を引き継ぎます。
- 以前のsettings.jsonは同じ保存先なので、そのまま読み込みます。

GitHub Actionsで配布用Windowsアプリをビルドする方法
1. ZIP内の以下のファイルをリポジトリの同じパスへアップロードまたは上書きしてください:
   EclipticaMusic.py / player.html / engine.js / unified.html / requirements.txt / .github/workflows/build.yml
2. GitHub Actions > Build Windows App > Run workflow を実行。
3. Artifactsの EclipticaMusicCompanion-Windows-v1.7 をダウンロード。
4. 展開したフォルダ全体を保持し、EclipticaMusicCompanion.exeを実行。
   （_internalフォルダの移動/削除は不可）

注意
- 古いEXE/別バージョンが実行中なら先に終了してください。新旧を同時実行すると二つのウィンドウが出ます。
- ユーザー操作による初回の再生許可が必要です（ブラウザの自動再生制限）。
- 内部でEdgeを使用しますが、Chrome等の普段のブラウザとは別プロファイルにします。
- 曲データ: %LOCALAPPDATA%\EclipticaMusicCompanion\settings.json
- MP3ファイルを選ぶときはWindows標準ファイル選択ダイアログが一時的に開きます。
- YouTube動画は埋め込み禁止・ネットワーク・ブラウザの制限で再生不可の場合があります。
- サードパーティ音源の利用権やダウンロード権限を確認してください。
- Pythonコンパイル、Tkinterを用いたローカルAPIの操作テスト、ブラウザUIの表示確認は実施済み。
- Windows実機での起動・YouTube音声再生・GitHub Actionsのビルドは未検証です。
