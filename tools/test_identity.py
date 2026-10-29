"""Local identity detection fixtures; no VRChat credentials or network access."""
import os
import tempfile
import time
from pathlib import Path
from vrchat_identity import parse_authenticated_name, read_authenticated_name, detect_identity, session_sort_key

UUID = 'usr_c244ca22-2273-4440-9b73-074eb346535e'
assert parse_authenticated_name('2025.07.24 20:43:05 Debug - User Authenticated: Auzlex (' + UUID + ')') == 'Auzlex'
assert parse_authenticated_name('2026.07.24 20:43:05 Log - [Behaviour] User Authenticated: 自分の表示名') == '自分の表示名'
assert parse_authenticated_name('OnPlayerJoined User Authenticated: Fake') == ''  # Ignore ambiguous join lines
assert parse_authenticated_name('2026.01.01 Log - OnPlayerJoined Someone ('+UUID+')') == ''
assert parse_authenticated_name('2025.07.24 Debug - User Authenticated: ') == ''
assert parse_authenticated_name('2025.07.24 Debug - User Authenticated: ' + 'A' * 200) == ''

with tempfile.TemporaryDirectory() as folder:
    base = Path(folder)
    assert not detect_identity(base).name
    first = base/'output_log_2026-10-26_18-01-00.txt'
    first.write_text('Log - OnPlayerJoined OtherUser\n2026.10.26 18:01:00 Debug - User Authenticated: 名前1 (' + UUID + ')\n', encoding='utf8')
    assert read_authenticated_name(first) == '名前1'
    assert detect_identity(base).name == '名前1'
    second = base/'output_log_2026-10-27_18-01-00.txt'
    second.write_text('2026.10.27 18:01:00 Debug - User Authenticated: 名前2 (' + UUID + ')\nLog - OnPlayerJoined 名前1\n', encoding='utf8')
    assert detect_identity(base).name == '名前2'
    # On Windows, two rapid writes may have the exact same filesystem mtime.
    # The log filename date must break ties, rather than filesystem iteration order.
    shared_mtime = max(first.stat().st_mtime, second.stat().st_mtime)
    os.utime(first, (shared_mtime, shared_mtime))
    os.utime(second, (shared_mtime, shared_mtime))
    assert detect_identity(base).name == '名前2'
    assert detect_identity(base,now=time.time()+13*3600).name == ''
    second.write_text('2026.10.27 Debug - OnPlayerJoined Someone Else\n',encoding='utf8')
    assert detect_identity(base).name == ''
    # Regression: touching the *older* log must not override the newer session.
    # This was the cause of the Windows Actions test's line-34 AssertionError.
    first.write_text('2026.10.26 Debug - User Authenticated: OLD (' + UUID + ')\n', encoding='utf8')
    os.utime(first, (time.time() + 3, time.time() + 3))
    assert detect_identity(base).name == ''
    assert max(base.glob('output_log_*.txt'), key=session_sort_key) == second
    # In large logs, the authenticator event can be early or near the end.
    second.write_bytes(('2026.10.27 18:01:00 Debug - User Authenticated: 名前2 (' + UUID + ')\n').encode('utf8')+b'X'*6_100_000)
    assert read_authenticated_name(second) == '名前2'
    with second.open('ab') as handle:
        handle.write(('\n2026.10.27 18:02:00 Debug - User Authenticated: 名前3 (' + UUID + ')\n').encode('utf8'))
    assert read_authenticated_name(second) == '名前3'
    # Do not mistake an incomplete line at EOF or a chunk edge for a full name.
    second.write_bytes(b'2026 Debug - User Authenticated: incomplete')
    assert read_authenticated_name(second) == ''
    second.write_bytes(b'X' * (2_000_000 - 35) + b'\n2026 Debug - User Authenticated: cropped' + b'X' * 4_100_000)
    assert read_authenticated_name(second) == ''
print('VRChat local user identity checks PASS')
