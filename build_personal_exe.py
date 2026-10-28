"""Build a personal Windows test EXE from the reviewed source, locally.

This script never uploads the application or publishes a release.  It installs
build tools into a temporary virtual environment, then deletes that environment.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

# Some Windows consoles cannot encode Japanese. Status output must not make
# an otherwise valid build fail when that occurs.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="backslashreplace")


ROOT = Path(__file__).resolve().parent
SOURCE_FILES = {
    "EclipticaMusic.py", "combat_meter.py", "vrchat_identity.py",
    "boss_weakness.py", "alert_sound.py", "boss_weakness_data.txt",
    "LICENSE_EclipticaHUD-C.txt", "player.html", "unified.html",
    "engine.js", "party.js", "requirements.txt", "tools/verify_release.py",
    "build_personal_exe.py", "BUILD_EXE.cmd",
}


def verify_sources() -> None:
    manifest = json.loads((ROOT / "SOURCE_SHA256.json").read_text(encoding="utf-8"))
    if set(manifest) != SOURCE_FILES:
        raise RuntimeError("ソースの確認用ファイルが不正です。")
    for name, expected in manifest.items():
        path = ROOT / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"ファイルが変更されているか見つかりません: {name}")


def run(command: list[str], *, env: dict[str, str] | None = None, timeout: int | None = None) -> None:
    subprocess.run(command, cwd=ROOT, env=env, timeout=timeout, check=True)


def smoke_test(executable: Path, option: str, env: dict[str, str], report: Path) -> None:
    try:
        run([str(executable), option], env=env, timeout=40)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = report.read_text(encoding="utf-8", errors="replace") if report.is_file() else str(exc)
        raise RuntimeError(f"EXEの起動テストに失敗しました: {detail}") from exc


def main() -> None:
    if sys.platform != "win32":
        raise RuntimeError("Windows上で実行してください。")
    if not ((3, 14, 10) <= sys.version_info[:3] < (3, 15, 0)):
        raise RuntimeError("Python 3.14.10以降の3.14系が必要です。")
    verify_sources()
    print("ソースを確認しました。ビルド用ツールを一時領域に準備します。", flush=True)
    output = Path(tempfile.mkdtemp(prefix="Ecliptica_EXE_", dir=ROOT))
    with tempfile.TemporaryDirectory(prefix="ecliptica-personal-build-") as temp_name:
        temp = Path(temp_name)
        venv = temp / "venv"
        build_env = os.environ.copy()
        build_env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        build_env["PYTHONNOUSERSITE"] = "1"
        run([sys.executable, "-m", "venv", str(venv)], env=build_env)
        py = str(venv / "Scripts" / "python.exe")
        pip = [py, "-m", "pip", "--isolated", "install", "--no-cache-dir", "--only-binary=:all:",
               "--index-url", "https://pypi.org/simple"]
        run(pip + ["-r", "requirements.txt"], env=build_env)
        run(pip + ["pip-audit==2.10.1"], env=build_env)
        print("依存関係の脆弱性を確認しています。", flush=True)
        run([py, "-m", "pip_audit", "--cache-dir", str(temp / "audit-cache"),
             "--index-url", "https://pypi.org/simple",
             "-r", "requirements.txt"], env=build_env)
        run([py, "-m", "compileall", "-q", "EclipticaMusic.py", "combat_meter.py",
             "vrchat_identity.py", "boss_weakness.py", "alert_sound.py"], env=build_env)
        spec = temp / "spec"
        spec.mkdir()
        args = [py, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
                "--windowed", "--noupx", "--name", "EclipticaMusicCompanion",
                "--distpath", str(output), "--workpath", str(temp / "work"),
                "--specpath", str(spec), "--exclude-module", "yt_dlp",
                "--exclude-module", "imageio_ffmpeg"]
        for asset in ("player.html", "unified.html", "engine.js", "party.js",
                      "boss_weakness_data.txt", "LICENSE_EclipticaHUD-C.txt"):
            args.extend(["--add-data", asset + ";."])
        run(args + ["EclipticaMusic.py"], env=build_env)
        app_folder = output / "EclipticaMusicCompanion"
        executable = app_folder / "EclipticaMusicCompanion.exe"
        run([py, "tools/verify_release.py", str(app_folder)], env=build_env)
        test_env = build_env.copy()
        test_env["LOCALAPPDATA"] = str(temp / "test-appdata")
        tk_report = temp / "tk-error.txt"
        gui_report = temp / "gui-error.txt"
        test_env["ECLIPTICA_TK_SELF_TEST_REPORT"] = str(tk_report)
        test_env["ECLIPTICA_GUI_SELF_TEST_REPORT"] = str(gui_report)
        print("作成したEXEの起動とHUDを確認しています。", flush=True)
        smoke_test(executable, "--tk-self-test", test_env, tk_report)
        smoke_test(executable, "--gui-self-test", test_env, gui_report)
    print("\nEXEを作成しました:", executable, flush=True)
    if os.environ.get("ECLIPTICA_BUILDER_CI") != "1":
        print("フォルダーを開きます。EXEをダブルクリックしてください。", flush=True)
        os.startfile(str(app_folder))  # type: ignore[attr-defined]


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\n作成できませんでした: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)
