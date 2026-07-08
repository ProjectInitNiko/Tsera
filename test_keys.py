"""Diagnostic clavier : hook global + polling GetAsyncKeyState, 15 secondes."""

import ctypes
import time

import keyboard

u = ctypes.windll.user32
hook_events = []
poll_events = []

keyboard.hook(lambda e: hook_events.append(f"{e.event_type} {e.name!r} scan={e.scan_code}"))

VK = {"right ctrl": 0xA3, "left ctrl": 0xA2, "right alt (AltGr)": 0xA5, "space": 0x20}
state = {k: False for k in VK}

print()
print("=== GO — presse des touches MAINTENANT (Ctrl droit, espace, ce que tu veux) ===")
print("=== 15 secondes ===")
print()

start = time.time()
while time.time() - start < 15:
    for name, vk in VK.items():
        down = bool(u.GetAsyncKeyState(vk) & 0x8000)
        if down != state[name]:
            state[name] = down
            poll_events.append(f"{time.time()-start:4.1f}s {name} {'DOWN' if down else 'UP'}")
    time.sleep(0.02)

keyboard.unhook_all()
print(f"HOOK  ({len(hook_events)} événements) : {hook_events[:20]}")
print(f"POLL  ({len(poll_events)} événements) : {poll_events[:20]}")
