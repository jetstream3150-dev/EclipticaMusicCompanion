Ecliptica Music Companion v1.0 - ZIP配布準備版

一般ユーザーの使い方（Windows）
1. GitHub ReleasesのZIPをダウンロードし、右クリック→すべて展開。
2. EclipticaMusicCompanion.exeを起動。_internalフォルダは移動・削除しない。
3. 起動したEdgeのBGMプレイヤーで「再生を有効化」。
4. 難易度別BGMタブでURLまたは音楽ファイルを設定し、「保存」。
5. VRChatを起動後「監視開始」。ログが見つからなければ「最新ログ」。
6. 自動検知ができないフェーズは難易度とフェーズを選んで「選択した曲を再生」。

制限事項
- Windows/Edgeが必要。音楽は自分のPCでのみ再生され、VRChat内には送信されません。
- YouTubeは動画の埋め込み制限・自動再生制限により再生できない場合があります。
- 自動監視はVRChatログのstage/bossイベントのみ試験対応。難易度・準備・終了・休憩の自動判定は未実装。
- ログが切り替わった場合、画面の案内に従って「監視開始」を押してください。
- MP3などローカルファイルの設定は他のPCには移行できません。設定復元後にファイルを再指定してください。
- 設定は %LOCALAPPDATA%\EclipticaMusicCompanion\settings.json に保存。ZIP更新でも維持されます。
- Windows実機・他のPC・セキュリティソフトでの動作検証は未実施。
- EXEは未署名。Windows SmartScreenの警告が出る可能性があります。警告を無条件に無視するよう利用者へ案内しないでください。
- 音楽の著作権・YouTube利用条件を確認して使用してください。

開発者向けビルド
GitHubへ EclipticaMusic.py, player.html, requirements.txt, .github/workflows/build.yml を配置。
Actions > Build Windows App > Run workflow を実行し、Artifactsから生成フォルダをダウンロード。
生成フォルダ全体をZIP化して配布してください。Artifactsは自動的にZIPでダウンロードされます。
配布前に別PCで動作・ログ検出・音楽再生・更新後の設定保持をテストしてください。
