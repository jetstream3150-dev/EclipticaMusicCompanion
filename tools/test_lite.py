"""Simple static invariants for the deliberately minimized release."""
from pathlib import Path
import re
base=Path(__file__).resolve().parent.parent
py=(base/'EclipticaMusic.py').read_text(encoding='utf-8')
html=(base/'unified.html').read_text(encoding='utf-8')
yaml=(base/'.github/workflows/build.yml').read_text(encoding='utf-8')
for text in (py,html):
    assert 'import yt_dlp' not in text
    assert 'imageio_ffmpeg.get_ffmpeg_exe' not in text
    assert 'download_web_mp3' not in text
assert "if action=='download':raise ValueError" in py
assert 'music-download' not in html
assert 'boss-download' not in html
assert 'lobby-download' not in html
# SteamVR's runtime DLL must be bundled, but downloaders remain excluded.
collected=re.findall(r"'--collect-all',\s*'([^']+)'",yaml)
assert collected and set(collected)=={'openvr'} and len(collected)==yaml.count('--collect-all')
assert "'--exclude-module', 'yt_dlp'" in yaml
assert "'--exclude-module', 'imageio_ffmpeg'" in yaml
assert '--noupx' in yaml
assert 'verify_release.py' in yaml
assert 'combat_meter.py' in yaml
assert 'vrchat_identity.py' in yaml
assert 'test_identity.py' in yaml
print('Lite static checks PASS')
