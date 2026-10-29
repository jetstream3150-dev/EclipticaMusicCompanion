import os, tempfile,sys,time
from combat_meter import CombatMeter

def test_combat():
 m=CombatMeter('MyPlayer',seconds=10)
 assert m.ingest('other random STRIKE damage: 999',now=0)==[]
 assert m.ingest('2026 ECLIPTICA - now fighting boss: GilgameshPhase2 on phase: 2',now=1)==[('boss','GilgameshPhase2')]
 m.ingest('ECLIPTICA - damage dealt: 123 STRIKE',now=2)
 m.ingest('ECLIPTICA - damage dealt: 25 NON-STRIKE',now=3)
 a=m.snapshot(now=4)
 assert a['boss_damage']==148 and a['dps']==14.8 and a['last_strike']==123
 assert a['attack_speed']==.1
 assert m.ingest('ECLIPTICA - boss target: MyPlayer',now=5)==[('target_on','MyPlayer')]
 assert m.snapshot(now=5)['is_targeted']
 assert m.ingest('ECLIPTICA - boss target: Somebody',now=6)==[('target_off','Somebody')]
 assert m.ingest('ECLIPTICA - now fighting boss: GilgameshPhase2 on phase: 3',now=7)==[('phase','3')]
 assert m.snapshot(now=7)['phase_damage']==0
 assert m.snapshot(now=20)['dps']==0
 m.ingest('ECLIPTICA - now in lobby',now=21)
 assert m.snapshot(now=21)['boss']=='待機中'
 print('combat checks PASS')

def test_app():
 import tkinter as tk
 import EclipticaMusic as music
 root=tk.Tk();root.withdraw()
 a=music.App(root,29337)
 root.update()
 assert len(a.api_config()['boss_choices'])>=45
 a.boss_map['Jim C. Bringer']='https://youtu.be/AAAAAAAAAAA'
 seen=[]
 oldplay=a.play
 a.play=lambda track,fallback='':seen.append((track,fallback))
 a.handle_boss('JimBringer')
 assert seen and seen[-1][0].startswith('https://youtu.be/'),seen
 a.play=oldplay
 a.api_action({'action':'add_boss','boss':'TestBossXYZ'})
 assert 'TestBossXYZ' in a.api_config()['boss_choices']
 result=a.api_action({'action':'overlay_settings','show':True,'name':'MyPlayer','auto_name':False,'alert':True,'other_alerts':False,'volume':44,'seconds':10,'opacity':90})
 root.update()
 assert a.hud is not None and a.hud.winfo_exists()
 assert a.api_view()['overlay_visible'] is True
 a.meter.ingest('ECLIPTICA - now fighting boss: JimBringer on phase: 2')
 a.meter.ingest('ECLIPTICA - damage dealt: 320 STRIKE')
 a.update_hud_loop();root.update()
 assert a.api_view()['combat']['boss_damage']==320
 a.meter.ingest('ECLIPTICA - now fighting boss: YukiPhase2(Clone) on phase: 0')
 a.update_hud_loop();root.update()
 assert a.api_view()['weakness']['name']=='Yuki(P2)'
 assert '弱火' in a.hud.weak_lbl.cget('text')
 a.api_action({'action':'overlay_settings','show':True,'name':'MyPlayer','auto_name':False,'alert':True,'other_alerts':False,'show_weakness':False,'sound_path':'C:/test/missing.mp3','volume':44,'seconds':10,'opacity':90})
 a.update_hud_loop();root.update()
 assert a.hud.weak_lbl.cget('text')==''
 assert a.api_config()['overlay']['sound_path']=='C:/test/missing.mp3'
 a.meter.ingest('ECLIPTICA - now in stage: Stage_A on phase: 0.1')
 a.meter.ingest('2026 Debug - spawn token, True, 55')
 a.meter.ingest('2026 Debug - ECLIPTICA saving SESSION ID 11508')
 a.update_hud_loop();root.update()
 assert '1 / 1' in a.hud.tracker_lbl.cget('text')
 a.meter.ingest('ECLIPTICA - now in intermission')
 a.meter.ingest('2026 Debug - Dealing 30 STRIKE damage')
 a.update_hud_loop();root.update()
 assert 'ダミー' in a.hud.tracker_lbl.cget('text')
 a.api_action({'action':'party_roster','rows':[{'name':'Alice','job':'Spellhammer','dps':42.5,'boss_damage':425}]})
 root.update()
 assert a.party_hud is not None and a.party_hud.winfo_exists()
 assert 'Alice' in a.party_hud.list_lbl.cget('text')
 try:a.api_action({'action':'party_roster','rows':[{'name':'Alice','job':'','dps':float('nan'),'boss_damage':0}]})
 except ValueError:pass
 else:raise AssertionError('invalid party metric was accepted')
 a.api_action({'action':'party_roster','rows':[]})
 root.update();assert a.party_hud.state()=='withdrawn'
 a.api_action({'action':'overlay_settings','show':True,'name':'MyPlayer','auto_name':False,'alert':True,'other_alerts':False,'show_weakness':True,'separate_widgets':True,'volume':44,'seconds':10,'opacity':90})
 a.meter.ingest('ECLIPTICA - now fighting boss: YukiPhase2(Clone) on phase: 0')
 a.update_hud_loop();root.update()
 weakness=a.extra_widgets['weakness']
 assert weakness.state()=='normal' and '弱火' in weakness.value.cget('text')
 assert a.hud.weak_lbl.cget('text')==''
 from types import SimpleNamespace
 weakness.drag_start(SimpleNamespace(x_root=weakness.winfo_x()+5,y_root=weakness.winfo_y()+5))
 weakness.drag(SimpleNamespace(x_root=205,y_root=225));root.update();weakness.drag_end(None)
 assert a.api_config()['overlay']['widget_positions']['weakness']==[200,220]
 a.meter.ingest('ECLIPTICA - now in stage: Stage_B on phase: 0.1')
 a.meter.ingest('2026 Debug - spawn token, True, 55')
 a.update_hud_loop();root.update()
 assert a.extra_widgets['tokens'].state()=='normal' and weakness.state()=='withdrawn'
 a.meter.ingest('ECLIPTICA - now in intermission')
 a.meter.ingest('2026 Debug - Dealing 30 STRIKE damage')
 a.update_hud_loop();root.update()
 assert a.extra_widgets['dummy'].state()=='normal' and a.extra_widgets['tokens'].state()=='withdrawn'
 a.api_action({'action':'overlay_settings','show':False,'name':'MyPlayer','auto_name':False,'alert':True,'other_alerts':False,'volume':44,'seconds':10,'opacity':90})
 assert a.api_config()['overlay']['sound_path']=='C:/test/missing.mp3'
 root.update();assert a.hud.state()=='withdrawn' and a.extra_widgets['dummy'].state()=='withdrawn'
 a.api_action({'action':'overlay_settings','show':False,'show_damage':True,'show_target':True,'name':'MyPlayer','auto_name':False,'alert':True,'other_alerts':False,'volume':44,'seconds':10,'opacity':90})
 a.meter.ingest('ECLIPTICA - now fighting boss: Yuki on phase: 1')
 a.meter.ingest('ECLIPTICA - damage dealt: 120 STRIKE')
 a.meter.ingest('ECLIPTICA - boss target: MyPlayer')
 a.update_hud_loop();root.update()
 assert a.extra_widgets['damage'].state()=='normal' and '120' in a.extra_widgets['damage'].value.cget('text')
 assert a.extra_widgets['target'].state()=='normal' and '狙われています' in a.extra_widgets['target'].value.cget('text')
 assert a.hud.state()=='withdrawn'
 damage=a.extra_widgets['damage'];damage.drag_start(SimpleNamespace(x_root=damage.winfo_x()+5,y_root=damage.winfo_y()+5))
 damage.drag(SimpleNamespace(x_root=305,y_root=245));root.update();damage.drag_end(None)
 assert a.api_config()['overlay']['widget_positions']['damage']==[300,240]
 a.close();print('Tk integration checks PASS')

if __name__=='__main__':
 test_combat()
 if '--gui' in sys.argv:test_app()
