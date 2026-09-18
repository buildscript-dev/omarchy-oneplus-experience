<h1 align="center">OnePlus Experience for Omarchy</h1>

<p align="center">
  <b>The native AirPods-style experience, for OnePlus earbuds.</b><br>
  A HeyMelody alternative for Omarchy: your earbuds' whole control center, one click from the bar.
</p>

<p align="center"><img src="preview.png" alt="The OnePlus Experience control center open from the Omarchy bar" width="380"></p>

On a phone, OnePlus earbuds come alive in HeyMelody. On Linux they're just
another Bluetooth headset. There's no battery per bud, no noise control and
no EQ. OnePlus Experience brings that control center to Omarchy's bar, drawn
in Omarchy's own panel style so it feels built in, the way AirPods feel on a Mac.

## The control center

- **Battery at a glance.** Left, right and case levels in the panel, the lowest
  bud's level next to the bar icon, and charging state for each part.
- **Noise control.** Noise Cancellation with **Max / Moderate / Mild** strength,
  **Smart ANC** that adapts to your surroundings, Transparency and Off.
  Right-click the bar icon to cycle modes without opening anything.
- **Sound.** Switch EQ presets instantly: Balanced, Deep Sea Bass, Pure Vocals,
  Bright & Crisp.
- **Switches.** Wear detection, game mode (low latency) and spatial audio.
- **Connection.** Connect or disconnect from this PC in one click, a
  notification with battery levels when your buds connect, and low-battery
  alerts at 20%, 10% and 5%.
- **Keyboard first.** `n` noise cancellation, `s` Smart ANC, `t` transparency,
  `o` off, `1`–`4` EQ presets, `j`/`k` and Enter to move and select, Esc to close.
- **Live.** The earbuds push changes, so a mode switched from the buds or your
  phone shows up right away. There's no polling.

## Supported earbuds

| Earbuds | Status |
|---|---|
| OnePlus Buds 3 | Full control center, verified on hardware (firmware 127.127.101) |
| Other OnePlus / OPPO / realme buds that use HeyMelody | Battery and basic noise control, untested |

Adding full support for another model means adding its product ID to `MODELS`
in `daemon/onepods.py`. Reports and pull requests are welcome.

## Requirements

- Omarchy 4 (Quattro shell)
- `python3`, `bluez` and `bluez-utils` (`bluetoothctl`). Omarchy ships all of these.
- `libnotify` (`notify-send`), optional, for connect and low-battery notifications
- Earbuds paired through the normal Bluetooth panel

No root access, PyPI packages or network access are needed.

## Install

```bash
omarchy plugin add https://github.com/buildscript-devv/omarchy-oneplus-experience.git --enable
~/.config/omarchy/plugins/io.github.buildscript-devv.oneplus-experience/setup
```

`omarchy plugin add` only clones the plugin. `setup` then does three things,
all as your user:

1. Writes `~/.local/bin/onepods-ctl`, a one-line wrapper around `daemon/onepods.py`.
2. Copies `daemon/onepods.service` to `~/.config/systemd/user/`.
3. Enables and starts that user service.

The daemon opens only a Bluetooth RFCOMM socket to your earbuds and a Unix
socket readable by you alone (mode 0600). It stores the earbuds' MAC address,
RFCOMM channel and last ANC strength in `~/.config/onepods/config.json`.

## Settings

| Setting | Default | |
|---|---|---|
| Hide the icon when disconnected | off | |
| Show the earbud battery next to the icon | on | The lower of the two buds |
| Path to onepods-ctl | empty | Leave empty to find it on `PATH` |

## How it works

- `daemon/onepods.py`: Python standard library only. Keeps one link to the
  buds, writes `~/.local/state/onepods/status.json`, and takes commands on
  `$XDG_RUNTIME_DIR/onepods.sock`.
- `onepods-ctl`: the CLI, e.g. `onepods-ctl noise:anc`, `onepods-ctl level:mild`,
  `onepods-ctl eq:0`, `onepods-ctl feature:game:off`, `onepods-ctl status`.
- `onepods.service`: a systemd user unit, installed by `./setup`.

## Remove

```bash
systemctl --user disable --now onepods
rm ~/.config/systemd/user/onepods.service ~/.local/bin/onepods-ctl
rm -rf ~/.config/onepods ~/.local/state/onepods
omarchy plugin remove io.github.buildscript-devv.oneplus-experience
```

## Credits

The panel design is adapted from
[AirPods Experience](https://github.com/MB-JAMBON/omarchy-pods) by GM and MB-JAMBON (MIT).
The protocol notes come from [OppoPodsWindows](https://github.com/3295074384/OppoPodsWindows),
[oppo-pods](https://github.com/osp54/oppo-pods) and
[oneplus-buds-omarchy](https://github.com/GazzasaurusRex/oneplus-buds-omarchy),
and were checked against real OnePlus Buds 3 hardware.

## Disclaimer

This is an independent project, not affiliated with or endorsed by OnePlus or
OPPO. OnePlus, OPPO, HeyMelody and AirPods are trademarks of their respective
owners, and appear here only to describe compatibility.
