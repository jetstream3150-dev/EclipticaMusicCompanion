# Ecliptica Music Companion v1.8.1 β Lite（セキュリティ点検版）

## なぜ別バージョンにしたか

v1.8の**配布ZIP**がVirusTotalで4/65の検出となり、Chromeで危険なダウンロードと警告されました。これは誤検知の可能性もありますが、**無害であることは未確認**です。このLite版は検査対象と依存関係を減らし、配布を透明にする目的で作りました。

**重要：本ZIPは更新用ソースコードであり、Windows実行ファイルではありません。** こちらの環境ではWindows版EXEを実際にビルドしていないため、ChromeやVirusTotalの警告が消える保証はありません。旧v1.8 ZIP/EXEは検査・原因特定まで配布しないでください。

## 維持した機能

- YouTube URLの**再生**（ダウンロードとは別、ブラウザの再生許可が必要）
- 手持ちのMP3/WAV/OGG/M4Aファイルの登録・再生
- ボス別・難易度別・ロビーBGM設定
- デスクトップ向けバトルHUD、DPS、ターゲット推定通知音（実ログとの完全互換性は未検証）
- 単一ウィンドウの統合UI・設定保存

## 一時停止した機能

**YouTubeからMP3としてダウンロード・変換する機能**を、Lite版では一時的に無効化しています。
この機能のUIとPythonの変換処理は除去し、yt-dlp / imageio-ffmpeg / FFmpegバイナリも配布しません。YouTube URLを入力して**そのまま再生する機能は残っています**。

## GitHubに適用する手順

1. このZIPを展開する。
2. 次のファイルを、GitHubリポジトリの**同じ位置に上書き・追加**する。
   - `EclipticaMusic.py`, `combat_meter.py`, `unified.html`, `player.html`, `engine.js`
   - `requirements.txt`, `build_windows.bat`, `test_v18.py`
   - `.github/workflows/build.yml` （重要）
   - `tools/verify_release.py`, `tools/test_lite.py`, `tools/windows_defender_scan.ps1` （tools フォルダを新規作成）
3. GitHubの Actions → **Build Windows App (v1.8.1 Lite Audit)** → Run workflow。
4. Artifact の **EclipticaMusicCompanion-Windows-v1.8.1-Lite** を取得。内容は `EclipticaMusicCompanion.exe` と `_internal`、検査レポートなど。
5. `BUNDLE_AUDIT.json`, `DEFENDER_SCAN.txt`, `SHA256SUMS.txt` を確認。`DEFENDER_SCAN.txt` が **NOT VERIFIED** とあればDefenderは未実行です。
6. EXE単体とZIP両方を別途ウイルス対策で調べ、新しいVirusTotal検出結果を確認する。無断で警告を解除するようユーザーに案内しない。

## セキュリティに関する注意

- PyInstallerによる自己完結EXEは誤検知されることがありますが、**検出数が減っても安全性の証明にはなりません**。
- `tools/verify_release.py` は余分な実行ファイルとFFmpeg/yt-dlpの残留を検出し、ファイルごとのSHA256を出します。マルウェアの存在を完全に判定するツールではありません。
- 可能な場合はGitHub Actions上でMicrosoft Defenderを実行します。ランナーがDefenderを提供しない場合は**未検証**として記録します。実機での検査は別途必要です。
- PyInstaller等の依存関係はバージョン固定し、`pip-audit`を実行します。依存関係の脆弱性検査とマルウェア検査は別ものです。
- 署名なしEXEのGoogle Safe Browsing警告をなくすには、検証・必要な場合の誤検知申告・コード署名など別途対応が必要です。
- **こちらの環境ではWindows実機での起動、Chromeのダウンロード判定、VRChat実戦ログは未検証です。**

設定ファイル `%LOCALAPPDATA%\EclipticaMusicCompanion\settings.json` は引き継ぐ設計です。変更前にバックアップしてください。
