import os,threading,time,traceback
from http.server import ThreadingHTTPServer
import tkinter as tk
import EclipticaMusic as mod

def exercise(base):
 try:
  from playwright.sync_api import sync_playwright
  with sync_playwright() as playwright:
   browser=playwright.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
   page=browser.new_page(viewport={'width':1300,'height':900},device_scale_factor=1)
   errors=[]
   page.on('pageerror',lambda err: errors.append(str(err)))
   page.set_content(open('/mnt/data/EclipticaMusicCompanion_v1.8_development/unified.html').read(),wait_until='domcontentloaded',timeout=20000)
   page.evaluate("fillBossDropdown(['Jim C. Bringer','Kakarot','Buff Noob'],{});document.getElementById('boss-name').value='Kakarot'")
   page.wait_for_function("document.querySelector('#boss-name').options.length >= 3",timeout=10000)
   count=page.locator('#boss-name option').count()
   assert count>=3,count
   page.locator('button[data-tab=boss]').click()
   page.locator('#boss-name').select_option(label='Jim C. Bringer')
   page.wait_for_timeout(250)
   page.locator('button[data-tab=hud]').click()
   page.locator('#hud-name').fill('MyPlayer')
   page.locator('#hud-show').check()
   page.wait_for_timeout(700)
   assert page.locator('#hud-current-boss').count()==1
   page.screenshot(path='/mnt/data/EclipticaMusicCompanion_v1.8_UI_preview.png',full_page=True)
   cfg={}
   assert page.locator('#hud-show').is_checked()
   assert not errors,errors
   print('Browser integration PASS: options',count,'HUD checked; screen created')
   browser.close()
 except Exception as e:
  print('BROWSER FAILED',repr(e),traceback.format_exc())
 finally:
  root.after(0,root.quit)

server=ThreadingHTTPServer(('127.0.0.1',0),mod.Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
root=tk.Tk();root.withdraw();mod.UI_APP=mod.App(root,server.server_port)
root.after(40,mod.UI_APP.drain_api)
threading.Thread(target=exercise,args=(f'http://127.0.0.1:{server.server_port}',),daemon=True).start()
root.mainloop()
server.shutdown()
mod.UI_APP.close()
