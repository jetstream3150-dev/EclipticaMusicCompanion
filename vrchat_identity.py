"""Local-only detection of the VRChat account shown in output_log_*.txt.

Only an explicit successful authentication event can establish the local user.
OnPlayerJoined and other player-name events are deliberately NOT used.
No API calls, credentials, or external packages are needed.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import NamedTuple

# A real VRChat log line looks like:
# 2025.07.24 20:43:05 Debug - User Authenticated: Name (usr_UUID)
# Some releases add a [Behaviour] prefix.
AUTH_EVENT = re.compile(r'(?:^|\s+-\s+|\[Behaviour\]\s+)User Authenticated:\s*(.+?)\s*$', re.I)
USER_ID_SUFFIX = re.compile(r'\s+\(usr_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\)\s*$', re.I)
# VRChat creates output_log_YYYY-MM-DD_HH-MM-SS.txt on startup. A log's
# filesystem mtime can change later (or have coarse resolution on Windows).
# Order sessions by the timestamp embedded in their filenames, not solely by
# mtime; never fall back to an older session's authenticated name.
LOG_FILENAME = re.compile(r'^output_log_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\.txt$', re.I)
AUTH_MARKER_BYTES = re.compile(rb'User Authenticated:', re.I)

def session_sort_key(path: Path):
    """Prefer the latest named VRChat session, even if an older log is touched."""
    match = LOG_FILENAME.fullmatch(path.name)
    mtime = path.stat().st_mtime_ns
    if match:
        return (1, match.group(1), match.group(2), mtime, path.name)
    return (0, '', '', mtime, path.name)


class IdentityResult(NamedTuple):
    name: str
    message: str
    log_path: str = ''


def parse_authenticated_name(line: str) -> str:
    """Return only the account in a successful auth event (never a join event)."""
    match = AUTH_EVENT.search(line)
    if not match:
        return ''
    name = USER_ID_SUFFIX.sub('', match.group(1)).strip()
    if not name or len(name) > 90 or any(ch in name for ch in '\r\n\x00'):
        return ''
    # Avoid interpreting malformed/incomplete lines as the user name.
    if name.startswith('(') or name.endswith(' (usr_'):
        return ''
    return name


def read_authenticated_name(path: Path) -> str:
    """Inspect only the beginning and end of a log, not potentially huge full logs."""
    size = path.stat().st_size
    with path.open('rb') as handle:
        if size <= 6_000_000:
            raw = handle.read(size)
        else:
            first = handle.read(2_000_000)
            # A chunk boundary can bisect a name; use complete lines only.
            first = first[:first.rfind(b'\n') + 1]
            handle.seek(max(0, size - 4_000_000))
            tail = handle.read(4_000_000)
            # The first line of an arbitrary tail chunk may be incomplete.
            tail = tail.partition(b'\n')[2] if tail else b''
            raw = first + b'\n' + tail
    # A still-growing log may end in half of an authentication event.
    raw = raw[:raw.rfind(b'\n') + 1]
    result = ''
    for line in raw.splitlines():
        if not AUTH_MARKER_BYTES.search(line):
            continue
        found = parse_authenticated_name(line.decode('utf-8', 'replace'))
        if found:
            result = found
    return result


def detect_identity(log_dir: Path, *, now: float | None = None,
                    max_age_seconds: float = 12 * 3600) -> IdentityResult:
    """Find the current local identity, or fail closed with an explanation."""
    now = time.time() if now is None else now
    try:
        logs = sorted(log_dir.glob('output_log_*.txt'),
                      key=session_sort_key, reverse=True)
    except OSError:
        logs = []
    if not logs:
        return IdentityResult('', 'VRChatのログが見つかりません。VRChatを起動してください。')
    newest = logs[0]
    try:
        if now - newest.stat().st_mtime > max_age_seconds:
            return IdentityResult('', 'ログが古いため自動取得できません。VRChatを起動してください。', str(newest))
        name = read_authenticated_name(newest)
    except (OSError, UnicodeError) as exc:
        return IdentityResult('', 'ログを読み取れません: ' + str(exc)[:100], str(newest))
    if name:
        return IdentityResult(name, 'VRChatログから自動取得しました', str(newest))
    return IdentityResult('', '認証成功の記録がありません。VRChatでログインし直すか手入力してください。', str(newest))
