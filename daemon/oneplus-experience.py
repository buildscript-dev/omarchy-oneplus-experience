#!/usr/bin/python3 -I
"""OnePlus Buds daemon for the Omarchy bar.

Holds one RFCOMM link to the connected OnePlus/OPPO earbuds (the HeyMelody
protocol), publishes their state to /run/user/<uid>/oneplus-experience/status.json
and takes commands on the socket next to it. Standard library only.

  oneplus-experience.py daemon        run the daemon (what the systemd unit does)
  oneplus-experience.py ctl VERB      send VERB to the daemon, e.g. `noise:anc`
  oneplus-experience.py status        print the published status
"""

from __future__ import annotations

import json
import os
import re
import secrets
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
import time

SCHEMA_VERSION = 1
SPP_UUID = "0000079a-d102-11e1-9b23-00025b00a5a5"
# HeyMelody's control channel on Buds 3 is 15; older OPPO parts use 12 or 13.
RFCOMM_CHANNELS = (15, 12, 13)

UID = os.getuid()
# Live state and the control socket sit in a private directory under the
# login's runtime directory (root-created, per-user, 0700); remembered
# settings (last earbuds, RFCOMM channel, ANC strength) in ~/.config.
RUNTIME_DIR = f"/run/user/{UID}/oneplus-experience"
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "oneplus-experience")
STATUS_NAME, SOCKET_NAME, CONFIG_NAME = "status.json", "oneplus-experience.sock", "config.json"
STATUS_MAX, CONFIG_MAX = 64 * 1024, 64 * 1024

BLUETOOTHCTL = "/usr/bin/bluetoothctl"
NOTIFY_SEND = "/usr/bin/notify-send"
MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")

DEVICE_POLL_S = 4.0
BATTERY_REFRESH_S = 60.0
LOW_BATTERY_STEPS = (20, 10, 5)

# ---------------------------------------------------------------------------
# Protocol: AA <len> 00 00 <cmd lo> <cmd hi> <seq> <payload len lo> <hi> <payload>
# ---------------------------------------------------------------------------

HELLO = bytes.fromhex("AA 07 00 00 00 01 23 00 00 12")
Q_PRODUCT, Q_VERSION, Q_BATTERY = 0x0103, 0x0105, 0x0106
Q_ANC, Q_FEATURES, Q_EQ = 0x010C, 0x010D, 0x010F
Q_BROADCAST_CODES, SUBSCRIBE, NOTIFY = 0x0200, 0x0205, 0x0204
SET_FEATURE, SET_ANC, SET_EQ = 0x0403, 0x0404, 0x0406
FEATURE_QUERY = bytes.fromhex("0B 05 04 0B 11 13 18 06 1B 1C 27 28")

# Feature switch ids, as HeyMelody numbers them.
FEATURES = {
    "wear": 0x04,       # pause media when a bud comes out
    "game": 0x06,       # low-latency mode
    "spatial": 0x1B,    # spatial sound
}

# Noise-control bit indices. The Buds read back a different bit than they are
# written with for Off and Transparency; HeyMelody's catalogue lists both.
NOISE_BITS_READ = {0: "off", 3: "off", 1: "anc", 2: "transparency", 8: "transparency",
                   4: "anc", 5: "anc", 6: "anc", 7: "smart"}
LEVEL_BITS = {4: "max", 5: "moderate", 6: "mild"}
NOISE_BITS_WRITE = {"off": 0, "transparency": 2, "smart": 7}
LEVEL_WRITE = {"max": 4, "moderate": 5, "mild": 6}

# Product ids (little-endian as sent, printed big-endian) -> model.
MODELS = {
    "063C14": {
        "name": "OnePlus Buds 3",
        "modes": ["anc", "smart", "transparency", "off"],
        "levels": ["max", "moderate", "mild"],
        # protocol index -> name, from HeyMelody's equalizerMode for this id.
        "eq": {0: "Balanced", 1: "Deep Sea Bass", 2: "Pure Vocals", 3: "Bright & Crisp"},
        "features": ["wear", "game", "spatial"],
    },
}
GENERIC_MODEL = {"name": "", "modes": ["anc", "transparency", "off"], "levels": [], "eq": {}, "features": []}


def encode(cmd: int, seq: int, payload: bytes = b"") -> bytes:
    return bytes((0xAA, 7 + len(payload), 0, 0, cmd & 0xFF, cmd >> 8, seq & 0xFF,
                  len(payload) & 0xFF, len(payload) >> 8)) + payload


class FrameReader:
    def __init__(self) -> None:
        self.buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        self.buf.extend(data)
        frames = []
        while True:
            start = self.buf.find(0xAA)
            if start < 0:
                self.buf.clear()
                return frames
            del self.buf[:start]
            if len(self.buf) < 2:
                return frames
            size = self.buf[1] + 2
            if size < 9:
                del self.buf[0]
                continue
            if len(self.buf) < size:
                return frames
            raw = bytes(self.buf[:size])
            del self.buf[:size]
            frames.append((raw[4] | raw[5] << 8, raw[9:]))


def log(*args) -> None:
    print(*args, file=sys.stderr, flush=True)


def clean_text(value, limit: int = 64) -> str:
    """Names and versions reported by the earbuds or BlueZ, safe to show anywhere:
    no control characters, no markup brackets, bounded length."""
    text = re.sub(r"[\x00-\x1f\x7f<>]", "", str(value or ""))
    return text[:limit]


# ---------------------------------------------------------------------------
# Files: every path is walked from / one directory descriptor at a time, never
# following a symlink, and each directory must belong to root or this user and
# be writable by nobody else. Reads are capped; writes go to a fresh random
# 0600 file in the same directory and are renamed into place.
# ---------------------------------------------------------------------------

DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _check_dir(fd: int, path: str) -> None:
    st = os.fstat(fd)
    if st.st_uid not in (0, UID) or st.st_mode & 0o022:
        raise OSError(f"refusing {path}: owned by uid {st.st_uid} or writable by others")


def open_dir(path: str, create: bool = False) -> int:
    """A verified descriptor for an absolute directory path, creating the missing
    tail (mode 0700) when asked."""
    fd = os.open("/", DIR_FLAGS)
    try:
        _check_dir(fd, "/")
        walked = ""
        for part in [p for p in path.split("/") if p]:
            if part in (".", ".."):
                raise OSError(f"refusing {path}")
            walked += "/" + part
            try:
                nxt = os.open(part, DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                nxt = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nxt
            _check_dir(fd, walked)
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_capped(dfd: int, name: str, cap: int) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dfd)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != UID or st.st_nlink != 1 or st.st_size > cap:
            raise OSError(f"refusing {name}")
        data = b""
        while len(data) <= cap:
            chunk = os.read(fd, cap + 1 - len(data))
            if not chunk:
                break
            data += chunk
        if len(data) > cap:
            raise OSError(f"{name} is larger than {cap} bytes")
        return data
    finally:
        os.close(fd)


def write_atomic(dfd: int, name: str, data: bytes) -> None:
    tmp = f".{name}.{secrets.token_hex(8)}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dfd)
    try:
        with os.fdopen(fd, "wb", closefd=False) as f:
            f.write(data)
            f.flush()
            os.fsync(fd)
    except BaseException:
        os.close(fd)
        os.unlink(tmp, dir_fd=dfd)
        raise
    os.close(fd)
    os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)


def unlink_quiet(dfd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=dfd)
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Child processes: a fixed executable, a closed environment, its own process
# group, a deadline, and output read with a hard cap. On overrun the whole
# group is terminated and reaped here, by the parent that started it.
# ---------------------------------------------------------------------------

def child_env(session: bool = False) -> dict:
    env = {"PATH": "/usr/bin", "LANG": "C.UTF-8"}
    if session:
        bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        if re.fullmatch(rf"unix:path=/run/user/{UID}/bus", bus):
            env["DBUS_SESSION_BUS_ADDRESS"] = bus
        env["XDG_RUNTIME_DIR"] = f"/run/user/{UID}"
    return env


def run_capped(argv: list[str], timeout: float, cap: int = 64 * 1024, session: bool = False) -> str:
    try:
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             env=child_env(session), start_new_session=True, close_fds=True)
    except OSError:
        return ""
    out, end, over = b"", time.monotonic() + timeout, False
    try:
        while True:
            left = end - time.monotonic()
            if left <= 0:
                over = True
                break
            ready, _, _ = select.select([p.stdout], [], [], left)
            if not ready:
                continue
            chunk = os.read(p.stdout.fileno(), 4096)
            if not chunk:
                break
            out += chunk
            if len(out) > cap:
                over = True
                break
    finally:
        p.stdout.close()
        if over or p.poll() is None:
            for sig, wait in ((signal.SIGTERM, 1.0), (signal.SIGKILL, None)):
                try:
                    os.killpg(p.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    p.wait(timeout=wait)
                    break
                except subprocess.TimeoutExpired:
                    continue
        p.wait()
    return "" if over else out.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# Bluetooth helpers
# ---------------------------------------------------------------------------

def bluetoothctl(*args: str, timeout: float = 10) -> str:
    return run_capped([BLUETOOTHCTL, *args], timeout)


def load_config() -> dict:
    try:
        dfd = open_dir(CONFIG_DIR)
        try:
            raw = json.loads(read_capped(dfd, CONFIG_NAME, CONFIG_MAX))
        finally:
            os.close(dfd)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    # Only the keys this daemon writes, each checked for its type and range.
    cfg = {}
    if isinstance(raw.get("mac"), str) and MAC_RE.match(raw["mac"]):
        cfg["mac"] = raw["mac"]
    if isinstance(raw.get("name"), str):
        cfg["name"] = clean_text(raw["name"])
    if isinstance(raw.get("channel"), int) and 1 <= raw["channel"] <= 30:
        cfg["channel"] = raw["channel"]
    if raw.get("anc_level") in LEVEL_WRITE:
        cfg["anc_level"] = raw["anc_level"]
    if isinstance(raw.get("notify_connect"), bool):
        cfg["notify_connect"] = raw["notify_connect"]
    return cfg


def save_config(cfg: dict) -> None:
    try:
        dfd = open_dir(CONFIG_DIR, create=True)
        try:
            write_atomic(dfd, CONFIG_NAME, json.dumps(cfg, indent=2).encode())
        finally:
            os.close(dfd)
    except OSError as e:
        log(f"could not save settings: {e}")


def is_oppo_device(mac: str) -> bool:
    return SPP_UUID in bluetoothctl("info", mac).lower()


def find_device(cfg: dict) -> tuple[str | None, str, bool]:
    """Return (mac, name, connected) for the earbuds, remembering the last ones seen."""
    for line in bluetoothctl("devices", "Connected").splitlines()[:64]:
        parts = line.split(" ", 2)
        if len(parts) >= 2 and parts[0] == "Device" and MAC_RE.match(parts[1]):
            # The name is whatever the device advertises.
            mac, name = parts[1], clean_text(parts[2] if len(parts) > 2 else parts[1])
            if mac == cfg.get("mac") or is_oppo_device(mac):
                if cfg.get("mac") != mac or cfg.get("name") != name:
                    cfg.update(mac=mac, name=name)
                    save_config(cfg)
                return mac, name, True
    return cfg.get("mac"), cfg.get("name", ""), False


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------

class Daemon:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.sock: socket.socket | None = None
        self.reader = FrameReader()
        self.seq = 0
        self.last_poll = 0.0
        self.last_battery = 0.0
        self.pending_refresh = 0.0
        self.alerted: dict[str, int] = {}
        self.announced = False
        self.reset_state()
        self.last_written = ""
        self.runtime_fd = -1

    def reset_state(self) -> None:
        mac, name = self.cfg.get("mac"), self.cfg.get("name", "")
        self.state = {
            "schema_version": SCHEMA_VERSION,
            "connected": False,
            "linked": False,
            "mac": mac or "",
            "device_name": name,
            "model_name": "",
            "product_id": "",
            "firmware": "",
            "noise_mode": "",
            "anc_level": "",
            "eq": -1,
            "features": {},
            "left": {"available": False, "level": -1, "charging": False},
            "right": {"available": False, "level": -1, "charging": False},
            "case": {"available": False, "level": -1, "charging": False},
            "supports": {"modes": [], "levels": [], "eq": [], "features": []},
            "error": "",
        }

    # -- status ------------------------------------------------------------

    def model(self) -> dict:
        return MODELS.get(self.state["product_id"], GENERIC_MODEL)

    def publish(self) -> None:
        m = self.model()
        self.state["supports"] = {
            "modes": m["modes"],
            "levels": m["levels"],
            "eq": [{"id": k, "name": v} for k, v in sorted(m["eq"].items())],
            "features": [f for f in m["features"]],
        }
        if m["name"]:
            self.state["model_name"] = m["name"]
        text = json.dumps(self.state, sort_keys=True)
        if text == self.last_written or self.runtime_fd < 0:
            return
        write_atomic(self.runtime_fd, STATUS_NAME, (text + "\n").encode())
        self.last_written = text

    def notify(self, title: str, body: str, urgency: str = "normal", tag: str = "oneplus-experience") -> None:
        # notify-send is optional; without it the bar still shows everything.
        if os.path.isfile(NOTIFY_SEND):
            run_capped([NOTIFY_SEND, "-a", "OnePlus Buds", "-u", urgency, "-i", "audio-headphones",
                        "-h", f"string:x-canonical-private-synchronous:{tag}", "--", title, body],
                       5, 4096, session=True)

    def check_low_battery(self) -> None:
        buds = [self.state[k] for k in ("left", "right") if self.state[k]["available"]]
        groups = {"buds": buds, "case": [self.state["case"]] if self.state["case"]["available"] else []}
        for key, parts in groups.items():
            if not parts:
                continue
            if any(p["charging"] for p in parts):
                self.alerted.pop(key, None)
                continue
            level = min(p["level"] for p in parts)
            for step in LOW_BATTERY_STEPS:
                if level <= step < self.alerted.get(key, 101):
                    self.alerted[key] = step
                    what = "Earbuds" if key == "buds" else "Charging case"
                    self.notify(f"{what} battery low", f"{level}% remaining",
                                "critical" if step <= 10 else "normal", f"oneplus-experience-{key}")
                    break

    def announce(self) -> None:
        if self.announced or not self.cfg.get("notify_connect", True):
            return
        parts = []
        for key, label in (("left", "L"), ("right", "R"), ("case", "Case")):
            p = self.state[key]
            if p["available"]:
                parts.append(f"{label} {p['level']}%" + (" ⚡" if p["charging"] else ""))
        if not parts:
            return
        self.announced = True
        mode = {"anc": "Noise cancellation", "smart": "Smart ANC", "transparency": "Transparency",
                "off": "Noise control off"}.get(self.state["noise_mode"], "")
        self.notify(self.state["model_name"] or self.state["device_name"] or "Earbuds connected",
                    "   ".join(parts) + (f"\n{mode}" if mode else ""), tag="oneplus-experience-connect")

    # -- link --------------------------------------------------------------

    def send(self, cmd: int, payload: bytes = b"") -> None:
        if not self.sock:
            raise OSError("earbuds are not linked")
        self.seq = (self.seq % 0xEF) + 1
        self.sock.sendall(encode(cmd, self.seq, payload))

    def open_link(self, mac: str) -> bool:
        channels = [self.cfg["channel"]] if self.cfg.get("channel") else []
        channels += [c for c in RFCOMM_CHANNELS if c not in channels]
        for ch in channels:
            s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            s.settimeout(4)
            try:
                s.connect((mac, ch))
                s.sendall(HELLO)
                s.sendall(encode(Q_PRODUCT, 1))
                reply = self._await(s, 0x8103, 1.5)
            except OSError:
                s.close()
                continue
            if reply is None:
                s.close()
                continue
            s.setblocking(False)
            self.sock, self.reader = s, FrameReader()
            if self.cfg.get("channel") != ch:
                self.cfg["channel"] = ch
                save_config(self.cfg)
            self.state["linked"] = True
            self.handle(0x8103, reply)
            log(f"linked to {mac} on RFCOMM channel {ch}, product {self.state['product_id']}")
            self.query_all()
            self.send(Q_BROADCAST_CODES)
            return True
        return False

    def _await(self, s: socket.socket, want: int, timeout: float) -> bytes | None:
        reader, end = FrameReader(), time.monotonic() + timeout
        while time.monotonic() < end:
            s.settimeout(max(0.05, end - time.monotonic()))
            try:
                data = s.recv(4096)
            except socket.timeout:
                break
            if not data:
                break
            for cmd, payload in reader.feed(data):
                if cmd == want:
                    return payload
        return None

    def close_link(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        self.state["linked"] = False

    def query_all(self) -> None:
        self.send(Q_VERSION)
        self.query_state()
        self.last_battery = time.monotonic()

    def query_state(self) -> None:
        self.send(Q_BATTERY)
        self.send(Q_ANC, b"\x01\x01")
        self.send(Q_FEATURES, FEATURE_QUERY)
        self.send(Q_EQ)

    # -- incoming ----------------------------------------------------------

    def set_battery(self, pairs: bytes, complete: bool) -> None:
        seen = set()
        for i in range(0, len(pairs) - 1, 2):
            name = {1: "left", 2: "right", 3: "case"}.get(pairs[i])
            if not name:
                continue
            raw = pairs[i + 1]
            level, charging = raw & 0x7F, bool(raw & 0x80)
            seen.add(name)
            if name == "case" and level == 0 and not charging:
                # The case reports 0 while closed and out of range; keep the last reading.
                continue
            self.state[name] = {"available": True, "level": level, "charging": charging}
        if complete:
            # A full reply that omits a bud means that bud is not talking to us (e.g. in the closed case).
            for name in ("left", "right"):
                if name not in seen:
                    self.state[name] = {**self.state[name], "available": False}
        self.check_low_battery()

    def handle(self, cmd: int, p: bytes) -> None:
        if cmd == 0x8103 and len(p) >= 4 and p[0] == 0:
            self.state["product_id"] = p[1:4][::-1].hex().upper()
        elif cmd == 0x8105 and len(p) >= 2 and p[0] == 0:
            fields = p[2:].decode("ascii", "replace").split(",")
            parts = {}
            for i in range(0, len(fields) - 2, 3):
                if fields[i + 1] == "2" and re.fullmatch(r"[0-9A-Za-z._-]{1,16}", fields[i + 2]):
                    parts[fields[i]] = fields[i + 2]
            self.state["firmware"] = ".".join(parts[k] for k in ("1", "2", "3") if k in parts)[:48]
        elif cmd == 0x8106 and len(p) >= 2 and p[0] == 0:
            self.set_battery(p[2:2 + p[1] * 2], complete=True)
        elif cmd == 0x810C and len(p) >= 4 and p[0] == 0:
            self.set_noise(p[1:])
        elif cmd == 0x810D and len(p) >= 2 and p[0] == 0:
            names = {v: k for k, v in FEATURES.items()}
            feats = dict(self.state["features"])
            for i in range(2, 2 + p[1] * 2, 2):
                if i + 1 < len(p) and p[i] in names:
                    feats[names[p[i]]] = p[i + 1] == 1
            self.state["features"] = feats
        elif cmd == 0x810F and len(p) >= 2 and p[0] == 0:
            self.state["eq"] = p[1]
        elif cmd == 0x0504 and len(p) == 1:
            self.state["eq"] = p[0]
        elif cmd == 0x8200 and len(p) >= 2 and p[0] == 0:
            codes = p[2:2 + p[1]]
            self.send(SUBSCRIBE, bytes([len(codes)]) + codes)
        elif cmd == NOTIFY and p:
            if p[0] == 0x01 and len(p) >= 2:
                self.set_battery(p[2:2 + p[1] * 2], complete=False)
            else:
                # Mode, wear and link changes arrive in several shapes; a re-read is exact.
                self.pending_refresh = time.monotonic() + 0.3
        elif cmd in (0x8404, 0x8403, 0x8406):
            self.pending_refresh = time.monotonic() + 0.2

    def set_noise(self, p: bytes) -> None:
        at = p.find(b"\x01\x01")
        if at < 0 or at + 2 >= len(p):
            return
        bitmap = int.from_bytes(p[at + 2:], "little")
        if not bitmap:
            return
        bit = (bitmap & -bitmap).bit_length() - 1
        mode = NOISE_BITS_READ.get(bit)
        if mode:
            self.state["noise_mode"] = mode
        if bit in LEVEL_BITS:
            self.state["anc_level"] = LEVEL_BITS[bit]
            self.cfg["anc_level"] = LEVEL_BITS[bit]

    # -- commands ----------------------------------------------------------

    def command(self, verb: str) -> str:
        verb = verb.strip()
        mac = self.state["mac"] or self.cfg.get("mac")
        if mac and not MAC_RE.match(mac):
            mac = None
        if verb == "connect":
            if not mac:
                return "error: no earbuds have been seen yet"
            out = bluetoothctl("connect", mac, timeout=20)
            self.last_poll = 0
            return "ok" if "successful" in out.lower() else f"error: {clean_text(out.strip().splitlines()[-1], 120) if out.strip() else 'connect failed'}"
        if verb == "disconnect":
            if not mac:
                return "error: no earbuds have been seen yet"
            self.close_link()
            bluetoothctl("disconnect", mac)
            self.last_poll = 0
            return "ok"
        if verb == "refresh":
            if self.sock:
                self.query_state()
            return "ok"
        if not self.sock:
            return "error: earbuds are not connected"

        m = self.model()
        kind, _, arg = verb.partition(":")
        if kind == "noise":
            if arg not in m["modes"]:
                return f"error: {self.state['model_name'] or 'these earbuds'} have no '{arg}' mode"
            if arg == "anc":
                level = self.cfg.get("anc_level", "max")
                bit = LEVEL_WRITE.get(level, 1) if m["levels"] else 1
            else:
                bit = NOISE_BITS_WRITE[arg]
            self.write_noise(bit)
            self.state["noise_mode"] = arg
        elif kind == "level":
            if arg not in m["levels"]:
                return f"error: unknown ANC strength '{arg}'"
            self.cfg["anc_level"] = arg
            save_config(self.cfg)
            self.write_noise(LEVEL_WRITE[arg])
            self.state.update(noise_mode="anc", anc_level=arg)
        elif kind == "eq":
            try:
                preset = int(arg)
            except ValueError:
                return "error: eq takes a preset number"
            if preset not in m["eq"]:
                return f"error: no EQ preset {preset}"
            self.send(SET_EQ, bytes([preset]))
            self.state["eq"] = preset
        elif kind == "feature":
            name, _, value = arg.partition(":")
            if name not in FEATURES or name not in m["features"] or value not in ("on", "off"):
                return "error: usage feature:<wear|game|spatial>:<on|off>"
            self.send(SET_FEATURE, bytes([FEATURES[name], 1 if value == "on" else 0]))
            self.state["features"] = {**self.state["features"], name: value == "on"}
        else:
            return f"error: unknown command '{verb}'"
        self.publish()
        return "ok"

    def write_noise(self, bit: int) -> None:
        width = bit // 8 + 1
        mask = (1 << bit).to_bytes(width, "little")
        self.send(SET_ANC, b"\x01\x01" + mask)

    # -- main loop ---------------------------------------------------------

    def poll_device(self) -> None:
        mac, name, connected = find_device(self.cfg)
        self.state["mac"], self.state["device_name"] = mac or "", name
        if connected and not self.sock:
            self.state["connected"] = True
            self.state["error"] = ""
            if not self.open_link(mac):
                self.state["error"] = "Could not open the HeyMelody control channel"
        elif not connected:
            if self.state["connected"]:
                log("earbuds disconnected")
            self.close_link()
            self.state["connected"] = False
            self.announced = False
            for k in ("left", "right"):
                self.state[k] = {**self.state[k], "available": False}
        self.publish()

    def run(self) -> None:
        self.runtime_fd = open_dir(RUNTIME_DIR, create=True)
        if os.fstat(self.runtime_fd).st_mode & 0o077:
            raise SystemExit(f"{RUNTIME_DIR} must be private (0700)")
        server = bind_socket(self.runtime_fd)
        server.setblocking(False)
        if not os.path.isfile(BLUETOOTHCTL):
            self.state["error"] = "bluetoothctl is missing, install bluez-utils"
        self.publish()
        log("oneplus-experience daemon started")
        try:
            while True:
                now = time.monotonic()
                if now - self.last_poll >= DEVICE_POLL_S:
                    self.last_poll = now
                    self.poll_device()
                if self.sock and self.pending_refresh and now >= self.pending_refresh:
                    self.pending_refresh = 0.0
                    self._safe(self.query_state)
                if self.sock and now - self.last_battery >= BATTERY_REFRESH_S:
                    self.last_battery = now
                    self._safe(lambda: self.send(Q_BATTERY))

                watch = [server] + ([self.sock] if self.sock else [])
                ready, _, _ = select.select(watch, [], [], 0.5)
                if self.sock in ready:
                    try:
                        data = self.sock.recv(4096)
                    except BlockingIOError:
                        data = b"\0"
                    except OSError:
                        data = b""
                    if not data:
                        log("control link dropped")
                        self.close_link()
                        self.last_poll = 0
                    elif data != b"\0":
                        for cmd, payload in self.reader.feed(data):
                            self._safe(lambda: self.handle(cmd, payload))
                        if self.state["connected"]:
                            self.announce()
                        self.publish()
                if server in ready:
                    self.serve(server)
        finally:
            self.close_link()
            unlink_quiet(self.runtime_fd, SOCKET_NAME)
            unlink_quiet(self.runtime_fd, STATUS_NAME)

    def _safe(self, fn) -> None:
        try:
            fn()
        except OSError as e:
            log(f"link error: {e}")
            self.close_link()
            self.last_poll = 0

    def serve(self, server: socket.socket) -> None:
        try:
            conn, _ = server.accept()
        except BlockingIOError:
            return
        with conn:
            conn.settimeout(2)
            try:
                if peer_uid(conn) != UID:
                    return
                verb = conn.recv(256).decode("utf-8", "replace")
                try:
                    reply = self.command(verb)
                except OSError as e:
                    self.close_link()
                    self.last_poll = 0
                    reply = f"error: {e}"
                conn.sendall(reply.encode())
            except OSError:
                pass


def peer_uid(conn: socket.socket) -> int:
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", creds)[1]


def socket_path(dfd: int) -> str:
    # Bound and reached through the verified directory descriptor, so the
    # socket is the one inside the checked directory whatever the path says.
    return f"/proc/self/fd/{dfd}/{SOCKET_NAME}"


def bind_socket(dfd: int) -> socket.socket:
    try:
        st = os.stat(SOCKET_NAME, dir_fd=dfd, follow_symlinks=False)
    except FileNotFoundError:
        st = None
    if st is not None:
        if not stat.S_ISSOCK(st.st_mode) or st.st_uid != UID:
            raise SystemExit(f"{RUNTIME_DIR}/{SOCKET_NAME} is not this daemon's socket")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(1)
        try:
            probe.connect(socket_path(dfd))
            raise SystemExit("another oneplus-experience daemon is already running")
        except OSError:
            unlink_quiet(dfd, SOCKET_NAME)  # left behind by a daemon that died
        finally:
            probe.close()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        server.bind(socket_path(dfd))
    finally:
        os.umask(old)
    server.listen(4)
    return server


def ctl(verb: str) -> int:
    try:
        dfd = open_dir(RUNTIME_DIR)
    except OSError:
        print("The oneplus-experience daemon is not running", file=sys.stderr)
        return 2
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(30)
    try:
        s.connect(socket_path(dfd))
        if peer_uid(s) != UID:
            raise OSError("socket is not served by this user")
    except OSError:
        s.close()
        os.close(dfd)
        print("The oneplus-experience daemon is not running", file=sys.stderr)
        return 2
    os.close(dfd)
    with s:
        s.sendall(verb[:256].encode())
        reply = s.recv(1024).decode("utf-8", "replace")
    if reply.startswith("error: "):
        print(clean_text(reply[7:], 200), file=sys.stderr)
        return 1
    print(clean_text(reply, 200))
    return 0


def status() -> int:
    try:
        dfd = open_dir(RUNTIME_DIR)
        try:
            data = read_capped(dfd, STATUS_NAME, STATUS_MAX)
        finally:
            os.close(dfd)
    except OSError:
        print("The oneplus-experience daemon is not running", file=sys.stderr)
        return 2
    sys.stdout.write(data.decode("utf-8", "replace").strip() + "\n")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["daemon"]:
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        try:
            Daemon().run()
        except KeyboardInterrupt:
            pass
        return 0
    if args[:1] == ["status"]:
        return status()
    if len(args) == 2 and args[0] == "ctl":
        return ctl(args[1])
    if len(args) == 1:
        return ctl(args[0])
    print(__doc__.strip())
    return 64


if __name__ == "__main__":
    sys.exit(main())
