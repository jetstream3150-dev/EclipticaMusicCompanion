"""Optional SteamVR overlay. No VR connection is attempted until enabled."""
import ctypes
import os
import threading
from pathlib import Path


def make_frame(snapshot, kind='combined'):
    from PIL import Image, ImageDraw, ImageFont
    size = (720, 224) if kind == 'combined' else (640, 136)
    image = Image.new('RGBA', size, (9, 20, 30, 220))
    draw = ImageDraw.Draw(image)
    fonts = [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / x
             for x in ('meiryo.ttc', 'YuGothR.ttc', 'msgothic.ttc')]
    def font(size):
        for candidate in fonts:
            try:
                return ImageFont.truetype(str(candidate), size)
            except (OSError, ValueError):
                pass
        return ImageFont.load_default()
    normal, big = font(25), font(31)
    boss = str(snapshot.get('boss', '待機中'))[:35]
    target = 'あなたがターゲット（推定）' if snapshot.get('is_targeted') else str(snapshot.get('target', '未検出'))[:28]
    border = (255, 110, 120, 255) if kind == 'target' and snapshot.get('is_targeted') else (80, 210, 205, 255)
    draw.rounded_rectangle((2, 2, size[0]-3, size[1]-3), radius=18, outline=border, width=3)
    if kind == 'damage':
        draw.text((24, 12), 'DAMAGE  /  estimated', font=normal, fill=(111, 237, 219, 255))
        draw.text((24, 62), 'DPS  %.1f    DMG  %.0f' % (snapshot.get('dps', 0), snapshot.get('boss_damage', 0)), font=big, fill=(245, 250, 255, 255))
        return image
    if kind == 'target':
        draw.text((24, 12), 'TARGET  /  estimated', font=normal, fill=(111, 237, 219, 255))
        draw.text((24, 62), target, font=big, fill=(255, 130, 139, 255) if snapshot.get('is_targeted') else (245, 250, 255, 255))
        return image
    draw.text((24, 15), 'ECLIPTICA  /  VR HUD', font=normal, fill=(111, 237, 219, 255))
    draw.text((24, 56), 'BOSS  ' + boss, font=big, fill=(245, 250, 255, 255))
    draw.text((24, 108), 'DPS  %.1f     DMG  %.0f' % (snapshot.get('dps', 0), snapshot.get('boss_damage', 0)),
              font=big, fill=(245, 250, 255, 255))
    draw.text((24, 160), 'TARGET  ' + target, font=normal,
              fill=(255, 130, 139, 255) if snapshot.get('is_targeted') else (180, 219, 226, 255))
    return image


class SteamVRHUD:
    def __init__(self):
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._closed = False
        self._enabled = False
        self._split = False
        self._thread = None
        self._snapshot = {}
        self._status = 'OFF'

    def status(self):
        with self._lock:
            return self._status

    def _set_status(self, value):
        with self._lock:
            self._status = value

    def enable(self, enabled, split=False):
        with self._lock:
            self._enabled = bool(enabled)
            self._split = bool(split)
            if not enabled:
                self._status = 'OFF'
            elif self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, daemon=True, name='SteamVR HUD')
                self._thread.start()
        self._wake.set()

    def update(self, snapshot):
        with self._lock:
            self._snapshot = dict(snapshot)

    def close(self):
        with self._lock:
            self._closed = True
            self._enabled = False
            thread = self._thread
        self._wake.set()
        if thread:
            thread.join(timeout=2)

    def _wait(self, seconds):
        self._wake.wait(seconds)
        self._wake.clear()

    def _run(self):
        while True:
            with self._lock:
                enabled, closed, split = self._enabled, self._closed, self._split
            if closed:
                return
            if not enabled:
                self._wait(1)
                continue
            vr = overlay = None
            handles = []
            initialized = False
            layout_changed = False
            try:
                import openvr
                vr = openvr
                self._set_status('SteamVRに接続中')
                vr.init(vr.VRApplication_Overlay)
                initialized = True
                overlay = vr.VROverlay()
                layouts = [('damage', -0.37, .56), ('target', 0.37, .56)] if split else [('combined', -0.35, .75)]
                for kind, x, width in layouts:
                    key = 'com.ecliptica.musiccompanion.hud' + ('.' + kind if split else '')
                    handle = overlay.createOverlay(key, 'Ecliptica ' + kind + ' HUD')
                    handles.append((kind, handle))
                    matrix = vr.HmdMatrix34_t()
                    for i in range(3):
                        matrix.m[i][i] = 1.0
                    matrix.m[0][3] = x
                    matrix.m[1][3] = -0.35
                    matrix.m[2][3] = -1.4
                    overlay.setOverlayTransformTrackedDeviceRelative(handle, vr.k_unTrackedDeviceIndex_Hmd, matrix)
                    overlay.setOverlayWidthInMeters(handle, width)
                while True:
                    with self._lock:
                        enabled, closed, desired_split, snapshot = self._enabled, self._closed, self._split, dict(self._snapshot)
                    if closed or not enabled:
                        break
                    if desired_split != split:
                        layout_changed = True
                        break
                    for kind, handle in handles:
                        frame = make_frame(snapshot, kind)
                        pixels = ctypes.create_string_buffer(frame.tobytes())
                        overlay.setOverlayRaw(handle, pixels, frame.width, frame.height, 4)
                        overlay.showOverlay(handle)
                    self._set_status('SteamVR HUDに表示中（実機で確認してください）')
                    self._wait(.5)
            except Exception as exc:
                self._set_status('SteamVR HUD未接続: ' + str(exc)[:160])
            finally:
                if overlay is not None:
                    for _, handle in handles:
                        try:
                            overlay.destroyOverlay(handle)
                        except Exception:
                            pass
                if initialized:
                    try:
                        vr.shutdown()
                    except Exception:
                        pass
            with self._lock:
                closed, enabled = self._closed, self._enabled
                if not enabled and not closed:
                    self._status = 'OFF'
            if closed:
                return
            if enabled and not layout_changed:
                self._wait(5)
