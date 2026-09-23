<h1 align="center">OnePlus Experience for Omarchy</h1>

<p align="center"><b>Your OnePlus earbuds' full control center, one click from the bar.</b></p>

<p align="center"><img src="preview.png" alt="The OnePlus Experience control center open from the Omarchy bar" width="420"></p>

<!-- Demo video: drag an .mp4 or .webm into any GitHub issue or PR comment box,
     copy the https://github.com/user-attachments/assets/... URL it gives you,
     and paste that URL on its own line right here. GitHub renders it inline. -->

## What you get

- **The ANC controls Linux never had.** Not just on/off: **Max / Moderate / Mild**
  strength and **Smart ANC** that adapts to the noise around you. These live in the
  earbuds' own protocol, but no Linux tool exposes them, and on a phone they are
  buried inside HeyMelody.
- **Battery per bud, and the case.** Left, right and case, with charging state. The
  lower bud shows next to the bar icon.
- **EQ presets.** Balanced, Deep Sea Bass, Pure Vocals, Bright & Crisp.
- **Switches.** Wear detection, game mode, spatial audio.
- **Live, not polled.** The buds push changes, so a mode you switch on the buds or
  from your phone appears right away.
- **Keyboard first.** `n` ANC, `s` Smart ANC, `t` transparency, `o` off, `1`–`4` EQ,
  `j`/`k` and Enter to move, Esc to close. Right-click the bar icon to cycle modes.

## What Linux gave you before

| | Controls available | |
|---|---|---|
| Plain Bluetooth (bluez) | `█░░░░░░░░░` | 1 of 10 — one combined battery number |
| HeyMelody (phone only) | `██████████` | 10 of 10 — nothing on the desktop |
| **OnePlus Experience** | `██████████` | **10 of 10, on your PC** |

Counted over: per-bud battery, case battery, ANC, ANC strength, Smart ANC,
transparency, EQ presets, wear detection, game mode, spatial audio.

## What it costs to run

1.2 against 1.0.x (`303997d`), both driving the same OnePlus Buds 3 on the same machine,
each through the exact command chain its own panel uses:

| | 1.0.x | 1.2 |
|---|---|---|
| Mode switches confirmed by the buds | 20/20 | 20/20 |
| `status`, median / p95 (30 runs) | 43.0 / 71.3 ms | 39.9 / 81.0 ms |
| Mode switch, median / p95 (20 runs) | 69.5 / 73.9 ms | 77.7 / 82.5 ms |
| Link after start | 0.6 s | 0.7 s |
| CPU, idle and linked (120 s) | 0.18% of one core | 0.92% of one core |
| Memory (RSS) | 16.3 MB | 20.5 MB |
| PyPI packages | 0 | 0 |
| Download | 120 KB | 150 KB |

Commands respond as fast as before. Every command now runs under a deadline and an
output cap. The extra idle CPU comes from Automatic mode, which checks the mic, the
media players and, when per-network modes are set, the Wi-Fi network every 4 s.
Turning Automatic off stops the mic and player checks.

Measured on Omarchy with Python 3.14. CPU counts the daemon plus every program it starts.

## Supported earbuds

| Earbuds | Status |
|---|---|
| OnePlus Buds 3 | Everything above, verified on hardware (firmware 127.127.101) |
| Other OnePlus / OPPO / realme buds on HeyMelody | Battery and basic noise control, untested |

To add full support for another model, add its product ID to `MODELS` in
`daemon/oneplus-experience.py`. Reports and pull requests are welcome.

## Install

```bash
omarchy plugin add https://github.com/buildscript-dev/omarchy-oneplus-experience.git --enable
~/.config/omarchy/plugins/io.github.buildscript-dev.oneplus-experience/setup
```

`omarchy plugin add` clones the plugin. `setup` installs and starts one
systemd **user** service, `~/.config/systemd/user/oneplus-experience.service`.
Nothing else is installed. No root, no network.

**Needs:** Omarchy 4, `bluez` and `bluez-utils`, and your earbuds already paired.
`libnotify` is optional, for connect and low-battery notifications. Omarchy ships
all of these.

## Noise control

| Mode | What it does |
|---|---|
| Adaptive | ANC that sets its own strength for the room (the buds' Smart ANC) |
| Noise Cancellation | fixed ANC at the strength you pick: Max, Moderate or Mild |
| Transparency | lets the room in |
| Conversation | transparency with voices brought forward (OPPO's vocal enhancement; HeyMelody doesn't offer it on Buds 3, but the firmware accepts it) |
| Off | nothing on top of the music |

- **Right-click cycle.** Right-click the bar icon (or `noise:next`) to step
  through the modes you picked in the panel's cycle row. The default is Noise
  Cancellation ↔ Transparency, as on AirPods.
- **Hold to listen.** While a key is held, the buds switch to Transparency.
  On release, whatever was on before comes back. Bind the press and the
  release in `~/.config/hypr/bindings.lua`:

  ```lua
  local ope = "/usr/bin/python3 -I " .. os.getenv("HOME") .. "/.config/omarchy/plugins/io.github.buildscript-dev.oneplus-experience/daemon/oneplus-experience.py"
  o.bind("SUPER + ALT + T", "Buds: hold to listen", ope .. " listen:on")
  o.bind("SUPER + ALT + T", "Buds: stop listening", ope .. " listen:off", { release = true })
  o.bind("SUPER + ALT + N", "Buds: next noise mode", ope .. " noise:next")
  ```

- **Automatic switching** (on by default, toggled in the panel). The buds
  switch to Transparency when a call or meeting opens the microphone, and
  when music has been paused for 30 seconds. They go back when the call ends
  or the music plays again.
  - Silence you chose is left alone: only a pause counts, not music that
    never played.
  - A mode you pick by hand wins until that call or pause is over.
- **Per-network modes and tuning.** `~/.config/oneplus-experience/config.json`
  takes these keys; run `$ope reload` after editing:

  ```json
  {
    "auto_wifi": { "Office Wi-Fi": "anc", "Home": "smart" },
    "auto_call": "transparency",
    "auto_idle": "transparency",
    "auto_idle_s": 30,
    "listen_mode": "vocal"
  }
  ```

  Set `auto_call` or `auto_idle` to `""` to turn off just that rule.

## Settings

| Setting | Default |
|---|---|
| Hide the icon when disconnected | off |
| Show the earbud battery next to the icon | on |

## From the terminal

```bash
ope="python3 -I ~/.config/omarchy/plugins/io.github.buildscript-dev.oneplus-experience/daemon/oneplus-experience.py"
$ope status
$ope noise:anc          # smart, anc, transparency, vocal, off, next
$ope listen:on / listen:off
$ope cycle:anc,transparency
$ope auto:on / auto:off
$ope level:mild
$ope eq:0
$ope feature:game:off
```

## What it runs

- **The daemon.** The service runs `/usr/bin/python3 -I` on this plugin's
  `daemon/oneplus-experience.py` (standard library only). It holds one
  Bluetooth RFCOMM link to the earbuds and makes no network connections.
- **Commands the panel sends.** The panel runs that same file in the same
  way, with a closed environment and a fixed `PATH`. It does not look
  anything up on your `PATH`.
  - Every call runs under GNU `timeout`, which ends the whole process group.
  - Output is capped while it is written.
- **Programs the daemon starts.** The daemon runs only `/usr/bin/bluetoothctl`
  and, if it is installed, `/usr/bin/notify-send`. Each one gets:
  - a closed environment;
  - its own process group;
  - a deadline;
  - a hard cap on what it reads back.
- **Its files.**
  - Live state and the control socket are in
    `/run/user/<uid>/oneplus-experience` (0700, in memory).
  - Remembered settings are in `~/.config/oneplus-experience/config.json`.
  - Every directory is opened one level at a time from `/`, without
    following links. Each must belong to root or to you and be writable by
    no one else.
  - Reads are size-capped.
  - Writes go to a fresh random 0600 file that is renamed into place.
- **The socket.** It answers only processes running as you.
- **What the earbuds report.** Names and versions from the earbuds and BlueZ
  are stripped of markup and control characters and shortened, before they
  reach the bar, its tooltip, the panel or a notification.

## Remove

```bash
systemctl --user disable --now oneplus-experience
rm ~/.config/systemd/user/oneplus-experience.service
rm -rf ~/.config/oneplus-experience
# Only if you installed a version before 1.1:
rm -f ~/.local/bin/oneplus-experience-ctl
rm -rf ~/.local/state/oneplus-experience
omarchy plugin remove io.github.buildscript-dev.oneplus-experience
```

## Credits

Panel design adapted from [AirPods Experience](https://github.com/MB-JAMBON/omarchy-pods)
by GM and MB-JAMBON (MIT). Protocol notes from
[OppoPodsWindows](https://github.com/3295074384/OppoPodsWindows),
[oppo-pods](https://github.com/osp54/oppo-pods) and
[oneplus-buds-omarchy](https://github.com/GazzasaurusRex/oneplus-buds-omarchy),
checked against real OnePlus Buds 3 hardware.

Only protocol facts were used from those projects, never their code. In
particular [OppoPodsWindows](https://github.com/3295074384/OppoPodsWindows) is
GPL-3.0 and none of it is copied, linked or redistributed here: this daemon is
an independent Python implementation of the same wire format, written for
interoperability with earbuds their owner already has. Preset and mode names are
the earbuds' own labels, as HeyMelody reports them. This project is MIT.

## Disclaimer

An independent project, not affiliated with or endorsed by OnePlus or OPPO.
OnePlus, OPPO, HeyMelody and AirPods are trademarks of their respective owners,
and appear here only to describe compatibility.
