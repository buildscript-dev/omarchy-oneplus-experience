// What the panel accepts from the status file. Run: node tests/test-model.mjs
import { readFileSync } from "node:fs"
import assert from "node:assert/strict"
const src = readFileSync(new URL("../Model.js", import.meta.url), "utf8")
const M = new Function(src + "\nreturn { parseStatus, command, capped, OUTPUT_MAX }")()

const s = M.parseStatus(JSON.stringify({
  schema_version: 1, connected: true, linked: true,
  device_name: "<img src='http://x/y'>Buds\u001b", model_name: "x".repeat(300), firmware: "1.<b>2</b>",
  noise_mode: "anc<script>", eq: 1e9, features: { wear: true, evil: true },
  left: { available: true, level: 250 },
  supports: { modes: ["anc", "<b>", "off"], eq: [{ id: 0, name: "<i>Bass</i>" }, { id: "x" }], features: ["wear", "<x>"] }
}))
assert.equal(s.deviceName, "img src='http://x/y'Buds")
assert.equal(s.modelName.length, 64)
assert.equal(s.firmware, "1.b2/b")
assert.equal(s.noiseMode, "")
assert.equal(s.eq, -1)
assert.deepEqual(s.features, { wear: true })
assert.equal(s.left.level, -1)
assert.deepEqual(s.modes, ["anc", "off"])
assert.deepEqual(s.eqPresets, [{ id: 0, name: "iBass/i" }])
assert.deepEqual(s.featureList, ["wear"])

const c = M.command("/p/daemon.py", ["ctl", "noise:anc"], 30)
assert.deepEqual(c.slice(0, 4), ["/usr/bin/timeout", "-k", "2", "30"])
assert.deepEqual(c.slice(-5), ["/usr/bin/python3", "-I", "/p/daemon.py", "ctl", "noise:anc"])
assert.equal(M.capped("x".repeat(M.OUTPUT_MAX + 1)), null)
assert.equal(M.capped("ok"), "ok")
console.log("model: ok")
