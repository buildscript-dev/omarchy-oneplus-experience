"""Automatic switching and hold-to-listen, on a simulated clock.
Run: python3 -I tests/test_auto.py"""
import importlib.util
import os

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ope", os.path.join(here, "..", "daemon", "oneplus-experience.py"))
ope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ope)

clock = [1000.0]
ope.time.monotonic = lambda: clock[0]
ope.save_config = lambda cfg: None

d = ope.Daemon()
d.cfg = {}
d.sock = object()
d.state.update(product_id="063C14", noise_mode="anc")
d.write_noise = lambda bit: None
d.publish = lambda: None
world = {"mic": False, "playing": False}
d.mic_in_use = lambda: world["mic"]
d.media_playing = lambda: world["playing"]


def tick(seconds=4):
    clock[0] += seconds
    d.auto_tick()
    return d.state["noise_mode"]


# Silence you chose is left alone: nothing ever played.
assert tick(60) == "anc"

# Music plays, pauses; 30 s later the room comes in, and play puts ANC back.
world["playing"] = True
assert tick() == "anc"
world["playing"] = False
assert tick(10) == "anc"
assert tick(24) == "transparency"
world["playing"] = True
assert tick() == "anc"

# A mode picked by hand during the override wins until the pause ends.
world["playing"] = False
tick(40)
assert d.command("noise:off") == "ok" and d.state["noise_mode"] == "off"
assert tick(60) == "off"

# A call brings in transparency and gives the previous mode back afterwards.
world["mic"] = True
assert tick() == "transparency"
world["mic"] = False
assert tick() == "off"

# Hold-to-listen wins over everything and restores exactly what was on.
d.command("noise:smart")
assert d.command("listen:on") == "ok" and d.state["noise_mode"] == "transparency"
world["mic"] = True
assert tick() == "transparency" and d.override == "listen"
assert d.command("listen:off") == "ok" and d.state["noise_mode"] == "smart"
assert tick() == "transparency"          # the call is still on
world["mic"] = False
assert tick() == "smart"

# Switched off, nothing automatic happens.
d.command("auto:off")
world["mic"] = True
assert tick() == "smart"

# The cycle steps through the chosen modes only.
d.command("cycle:anc,vocal")
d.command("noise:next")
assert d.state["noise_mode"] == "anc"
d.command("noise:next")
assert d.state["noise_mode"] == "vocal"
assert d.command("cycle:anc").startswith("error")

print("auto: ok")
