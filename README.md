# OnePlus Buds for Omarchy

A OnePlus Buds 3 version of the AirPods Experience plugin
(io.github.mb-jambon.omapods). It uses the same panel layout, but speaks
HeyMelody's protocol (`0xAA` frames over RFCOMM channel 15) instead of Apple's AAP.

- Battery for each bud and the case, plus the lowest bud's level in the bar
- Noise Cancellation (Max / Moderate / Mild), Smart ANC, Transparency, Off
- EQ presets: Balanced, Deep Sea Bass, Pure Vocals, Bright & Crisp
- Wear detection, game mode and spatial audio switches
- Connect/disconnect, a notification on connect, and low-battery alerts at 20/10/5%

<p align="center"><img src="preview.png" alt="The OnePlus Buds panel in the Omarchy bar" width="380"></p>

## Requirements

- Omarchy 4 (Quattro shell)
- `python3`, `bluez` and `bluez-utils` (`bluetoothctl`). Omarchy ships all of these.
- `libnotify` (`notify-send`), optional, for connect and low-battery notifications
- Earbuds paired through the normal Bluetooth panel

No root access, PyPI packages or network access are needed.

## Install

```bash
omarchy plugin add https://github.com/buildscript-devv/omarchy-onepods.git --enable
~/.config/omarchy/plugins/io.github.buildscript-devv.onepods/setup
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

## Use

Right-click the bar icon to cycle noise modes. In the panel: `n` noise
cancellation, `s` Smart ANC, `t` transparency, `o` off, `1`–`4` EQ presets,
`j`/`k` and Enter to move and select.

## Pieces

- `daemon/onepods.py`: Python standard library only. Keeps one link to the
  buds, writes `~/.local/state/onepods/status.json`, and takes commands on
  `$XDG_RUNTIME_DIR/onepods.sock`.
- `onepods-ctl`: the CLI, e.g. `onepods-ctl noise:anc`, `onepods-ctl level:mild`,
  `onepods-ctl eq:0`, `onepods-ctl feature:game:off`, `onepods-ctl status`.
- `onepods.service`: a systemd user unit, installed by `./setup`.

Other OPPO/OnePlus/realme buds get battery and basic ANC. Adding a model means
adding its product ID to `MODELS` in `daemon/onepods.py`.

## Remove

```bash
systemctl --user disable --now onepods
rm ~/.config/systemd/user/onepods.service ~/.local/bin/onepods-ctl
rm -rf ~/.config/onepods ~/.local/state/onepods
omarchy plugin remove io.github.buildscript-devv.onepods
```

Protocol details come from OppoPodsWindows, oppo-pods (osp54) and
oneplus-buds-omarchy (GazzasaurusRex), and were checked against real Buds 3
hardware (firmware 127.127.101).
