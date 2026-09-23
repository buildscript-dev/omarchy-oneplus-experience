"""File, process and text guards of the daemon. Run: python3 -I tests/test_guards.py"""
import importlib.util
import os
import stat
import sys
import tempfile
import time

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ope", os.path.join(here, "..", "daemon", "oneplus-experience.py"))
ope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ope)

# Text from the earbuds or BlueZ: no markup brackets, no control characters, bounded.
assert ope.clean_text("<img src=x>Buds\x1b[31m\n") == "img src=xBuds[31m"
assert len(ope.clean_text("x" * 500)) == 64

# Directories: refused when writable by others (the sticky /tmp) or reached through a link.
try:
    ope.open_dir("/tmp"); raise AssertionError("/tmp accepted")
except OSError:
    pass
base = tempfile.mkdtemp(dir=f"/run/user/{os.getuid()}")
try:
    os.symlink(base, base + "-link")
    try:
        ope.open_dir(base + "-link"); raise AssertionError("symlinked directory accepted")
    except OSError:
        pass
    dfd = ope.open_dir(base + "/state", create=True)
    assert stat.S_IMODE(os.fstat(dfd).st_mode) == 0o700

    # Writes: a fresh 0600 file renamed into place, nothing left behind.
    ope.write_atomic(dfd, "status.json", b"{}")
    assert stat.S_IMODE(os.stat("status.json", dir_fd=dfd).st_mode) == 0o600
    assert os.listdir(dfd) == ["status.json"]
    assert ope.read_capped(dfd, "status.json", 16) == b"{}"

    # Reads: refused for links, FIFOs and anything over the cap.
    os.symlink("/etc/passwd", "link.json", dir_fd=dfd)
    os.mkfifo(os.path.join(base, "state", "fifo.json"))
    with open(os.path.join(base, "state", "big.json"), "wb") as f:
        f.write(b"x" * 100)
    for name, cap in (("link.json", 1 << 20), ("fifo.json", 1 << 20), ("big.json", 99)):
        try:
            ope.read_capped(dfd, name, cap); raise AssertionError(f"{name} accepted")
        except OSError:
            pass
    os.close(dfd)
finally:
    os.system(f"/usr/bin/rm -rf -- '{base}' '{base}-link'")

# Processes: the output cap and the deadline both end the whole group.
assert ope.run_capped(["/usr/bin/yes"], 5, cap=1000) == ""
t = time.monotonic()
assert ope.run_capped(["/usr/bin/sh", "-c", "sleep 30 & sleep 30"], 1) == ""
assert time.monotonic() - t < 4
assert ope.run_capped(["/usr/bin/printf", "ok"], 5) == "ok"
assert ope.run_capped(["/usr/bin/sh", "-c", "echo $PATH $HOME"], 5).split() == ["/usr/bin"]

print("guards: ok")
