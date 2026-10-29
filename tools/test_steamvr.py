import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from steamvr_hud import SteamVRHUD, make_frame


class FakeOverlay:
    def __init__(self):
        self.shown=threading.Event();self.destroyed=threading.Event();self.frames=0
    def createOverlay(self, key, name):
        assert key and name
        return 123
    def setOverlayTransformTrackedDeviceRelative(self, handle, index, matrix):
        assert handle==123 and index==0 and matrix.m[2][3]<0
    def setOverlayWidthInMeters(self, handle, width):
        assert handle==123 and 0<width<1
    def setOverlayRaw(self, handle, pixels, width, height, depth):
        assert handle==123 and (width,height,depth)==(720,224,4)
        assert len(pixels)>=width*height*depth
        self.frames+=1
    def showOverlay(self, handle):self.shown.set()
    def destroyOverlay(self, handle):self.destroyed.set()


class SteamVRTests(unittest.TestCase):
    def test_frame_contains_expected_size_and_transparency(self):
        image=make_frame({'boss':'Yuki','target':'Alice','dps':12,'boss_damage':345,'is_targeted':True})
        self.assertEqual((image.mode,image.size),('RGBA',(720,224)))
        self.assertNotEqual(image.getpixel((2,110)),image.getpixel((700,210)))

    def test_opt_in_overlay_updates_and_cleans_up(self):
        overlay=FakeOverlay();calls=[]
        fake=SimpleNamespace(VRApplication_Overlay=2,k_unTrackedDeviceIndex_Hmd=0,
            HmdMatrix34_t=lambda:SimpleNamespace(m=[[0.0]*4 for _ in range(3)]),
            init=lambda kind:calls.append(('init',kind)),VROverlay=lambda:overlay,
            shutdown=lambda:calls.append(('shutdown',)))
        hud=SteamVRHUD()
        with patch.dict(sys.modules,{'openvr':fake}):
            self.assertEqual(calls,[])
            hud.update({'boss':'Yuki','dps':5,'boss_damage':20,'target':'Alice'})
            hud.enable(True)
            self.assertTrue(overlay.shown.wait(3))
            self.assertGreaterEqual(overlay.frames,1)
            hud.enable(False)
            self.assertTrue(overlay.destroyed.wait(3))
            hud.close()
        self.assertIn(('shutdown',),calls)

    def test_missing_runtime_is_reported_without_crashing_app(self):
        def unavailable(kind):raise RuntimeError('SteamVR is not running')
        fake=SimpleNamespace(VRApplication_Overlay=2,init=unavailable)
        hud=SteamVRHUD()
        try:
            with patch.dict(sys.modules,{'openvr':fake}):
                hud.enable(True)
                end=time.monotonic()+3
                while time.monotonic()<end and '未接続' not in hud.status():time.sleep(.02)
                self.assertIn('SteamVR HUD未接続',hud.status())
        finally:hud.close()


if __name__ == '__main__':
    unittest.main()
