"""Inspect a PyInstaller onedir release; output a full SHA256 file manifest.

This catches accidental extra executables and converter bundles; it does NOT
prove the application is free of malware or bypass browser reputation systems.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys

def verify(root):
    root = Path(root).resolve()
    if not root.is_dir():
        raise RuntimeError(f"Release folder was not created: {root}")
    executable = root / 'EclipticaMusicCompanion.exe'
    if not executable.is_file() or executable.stat().st_size < 100_000:
        raise RuntimeError('Main executable missing or abnormally small')
    allowed_executable = executable.resolve()
    blocked_names = ('yt_dlp', 'imageio_ffmpeg', 'ffmpeg', 'ffprobe')
    entries = []
    for file in sorted(root.rglob('*')):
        if not file.is_file():
            continue
        relative = file.relative_to(root).as_posix()
        low = relative.casefold()
        if file.resolve() == allowed_executable:
            pass
        elif file.suffix.casefold() in ('.exe', '.msi', '.cmd', '.bat', '.ps1', '.vbs', '.scr'):
            raise RuntimeError(f"Unexpected runnable file in app bundle: {relative}")
        if any(word in low for word in blocked_names):
            raise RuntimeError(f"Network downloader/converter unexpectedly bundled: {relative}")
        if low.startswith('_internal/demo_audio/'):
            raise RuntimeError(f"Trial audio unexpectedly bundled: {relative}")
        if relative in ('SHA256SUMS.txt', 'BUNDLE_AUDIT.json', 'DEFENDER_SCAN.txt'):
            continue
        entries.append({'path': relative,
                        'bytes': file.stat().st_size,
                        'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
    required = {'EclipticaMusicCompanion.exe', '_internal/unified.html',
                '_internal/player.html', '_internal/engine.js', '_internal/party.js',
                '_internal/python314.dll',
                '_internal/openvr/libopenvr_api_64.dll',
                '_internal/boss_weakness_data.txt', '_internal/LICENSE_EclipticaHUD-C.txt'}
    found = {e['path'] for e in entries}
    missing = required - found
    if missing:
        raise RuntimeError('Missing required files: '+', '.join(sorted(missing)))
    (root/'SHA256SUMS.txt').write_text(''.join(f"{e['sha256']}  {e['path']}\n" for e in entries), encoding='utf-8')
    (root/'BUNDLE_AUDIT.json').write_text(json.dumps({
        'format': 'Ecliptica Lite packaging inspection v1',
        'files_count': len(entries),
        'files_total_bytes': sum(e['bytes'] for e in entries),
        'main_exe_sha256': next(e['sha256'] for e in entries if e['path']=='EclipticaMusicCompanion.exe'),
        'checks': ['main executable present', 'no unexpected executable types',
                   'no downloader or FFmpeg bundles', 'player/UI assets present'],
        'notice': 'These checks do not constitute an antivirus clearance.',
    }, ensure_ascii=False, indent=2),encoding='utf-8')
    print(f"PASS: {len(entries)} files; wrote SHA256SUMS.txt and BUNDLE_AUDIT.json")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('release_dir')
    args = parser.parse_args()
    try:verify(args.release_dir)
    except Exception as err:
        print(f"RELEASE CHECK FAILED: {err}",file=sys.stderr)
        sys.exit(1)
