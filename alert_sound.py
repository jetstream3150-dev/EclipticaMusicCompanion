"""Play an optional local notification sound, reporting failure for fallback."""
from array import array
from io import BytesIO
from pathlib import Path
import ctypes
import sys
import uuid
import wave

MAX_SECONDS = 30
MAX_FILE_BYTES = 20 * 1024 * 1024


def _wav_bytes(path, volume):
    # Limit memory and duration. PCM 16-bit preserves the requested volume;
    # unsupported/corrupt WAVs fall back to the built-in alert.
    with wave.open(str(path), 'rb') as source:
        channels, width, rate, frames = (source.getnchannels(), source.getsampwidth(),
                                          source.getframerate(), source.getnframes())
        if (source.getcomptype() != 'NONE' or channels not in (1, 2) or width != 2
                or rate <= 0 or frames <= 0 or frames > rate * MAX_SECONDS):
            raise ValueError('Unsupported WAV format')
        samples = array('h')
        samples.frombytes(source.readframes(frames))
        if len(samples) != frames * channels:
            raise ValueError('Truncated WAV file')
    if sys.byteorder != 'little':
        samples.byteswap()
    gain = max(0, min(100, int(volume))) / 100
    for index, value in enumerate(samples):
        samples[index] = int(value * gain)
    if sys.byteorder != 'little':
        samples.byteswap()
    result = BytesIO()
    with wave.open(result, 'wb') as target:
        target.setnchannels(channels)
        target.setsampwidth(width)
        target.setframerate(rate)
        target.writeframes(samples.tobytes())
    return result.getvalue()


def _windows_mci(command):
    dll = ctypes.WinDLL('winmm', use_last_error=True)
    send = dll.mciSendStringW
    send.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p)
    send.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(128)
    error = send(command, buffer, len(buffer), None)
    return error, buffer.value


def _play_mp3(path, volume, send):
    # A generated alias and a quoted file name prevent MCI command injection.
    name = str(path)
    if any(char in name for char in ('"', '\r', '\n', '\0')):
        return False
    alias = 'emc' + uuid.uuid4().hex
    error, _ = send(f'open "{name}" type mpegvideo alias {alias}')
    if error:
        return False
    try:
        error, _ = send(f'set {alias} time format milliseconds')
        if error:
            return False
        error, length = send(f'status {alias} length')
        if error or not length.isdigit() or not 0 < int(length) <= MAX_SECONDS * 1000:
            return False
        error, _ = send(f'setaudio {alias} volume to {max(0, min(100, int(volume))) * 10}')
        if error:
            return False
        error, _ = send(f'play {alias} wait')
        return error == 0
    finally:
        send(f'close {alias}')


def play_custom_sound(filename, volume, wav_player=None, mci_send=None):
    """Return True only if playback succeeded; never turn failure into silence."""
    try:
        path = Path(filename)
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return False
        if path.suffix.casefold() == '.wav':
            if wav_player is None:
                import winsound
                wav_player = lambda data: winsound.PlaySound(data, winsound.SND_MEMORY)
            wav_player(_wav_bytes(path, volume))
            return True
        if path.suffix.casefold() == '.mp3':
            return _play_mp3(path.resolve(), volume, mci_send or _windows_mci)
    except (OSError, ValueError, OverflowError, wave.Error, EOFError, AttributeError, RuntimeError, TypeError):
        return False
    return False
