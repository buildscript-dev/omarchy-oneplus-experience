// No QML imports, so this runs in a plain JS harness too.

var SUPPORTED_SCHEMA = 1
var LEVEL_UNKNOWN = -1
var LOW_BATTERY = 20

// nf-md-check and nf-md-earbuds.
var GLYPH_CHECK = "󰄬"
var GLYPH_BUDS = "󱡏"

var MODE_NAMES = {
  anc: "Noise Cancellation",
  smart: "Smart ANC",
  transparency: "Transparency",
  off: "Off"
}
var LEVEL_NAMES = { max: "Max", moderate: "Moderate", mild: "Mild" }
var FEATURE_TEXT = {
  wear: ["Wear detection", "Pause when you take a bud out"],
  game: ["Game mode", "Lower latency, for games and video"],
  spatial: ["Spatial audio", "Wider, surround-style sound"]
}

// ---------------------------------------------------------------------------
// Running the helper. Everything it prints is capped while it is produced
// (head -c, with pipefail), stderr is folded into the same capped stream, and
// GNU timeout ends the whole process group, then KILLs it.
var OUTPUT_MAX = 65536

function command(helperPath, args, seconds) {
  return ["/usr/bin/timeout", "-k", "2", String(seconds), "/usr/bin/bash", "-c",
          "set -o pipefail; \"$@\" 2>&1 | /usr/bin/head -c " + (OUTPUT_MAX + 1), "helper",
          "/usr/bin/python3", "-I", String(helperPath)].concat(args.map(String))
}

// The collected output, or null when it ran past the cap. The UTF-8 size is
// counted from the decoded text; a stray byte decodes to U+FFFD (three bytes),
// so the count never comes out smaller than what was read.
function capped(text) {
  var t = String(text || "")
  var n = 0
  for (var i = 0; i < t.length; i++) {
    var c = t.charCodeAt(i)
    n += c < 0x80 ? 1 : c < 0x800 ? 2 : (c >= 0xd800 && c <= 0xdbff) ? (i++, 4) : 3
  }
  return n > OUTPUT_MAX ? null : t
}

// Names and versions come from the earbuds and from BlueZ, so whatever they
// say is stripped of markup brackets and control characters and kept short
// before it reaches any text in the bar, its tooltip or the panel.
function safeText(value, limit) {
  var t = String(value === undefined || value === null ? "" : value).replace(/[\u0000-\u001f\u007f<>]/g, "")
  return t.length > limit ? t.substring(0, limit - 1) + "…" : t
}

function words(list, max) {
  var out = []
  if (!Array.isArray(list)) return out
  for (var i = 0; i < list.length && out.length < max; i++)
    if (/^[a-z]{1,16}$/.test(String(list[i]))) out.push(String(list[i]))
  return out
}

function defaultPart() {
  return { level: LEVEL_UNKNOWN, charging: false }
}

function defaultStatus() {
  return {
    ok: false,
    lastError: "",
    connected: false,
    linked: false,
    deviceName: "",
    modelName: "",
    firmware: "",
    noiseMode: "",
    ancLevel: "",
    eq: -1,
    features: {},
    left: defaultPart(),
    right: defaultPart(),
    caseBattery: defaultPart(),
    modes: [],
    levels: [],
    eqPresets: [],
    featureList: []
  }
}

function partFrom(raw) {
  var part = defaultPart()
  if (!raw || raw.available !== true) return part
  var n = parseInt(raw.level, 10)
  part.level = isFinite(n) && n >= 0 && n <= 100 ? n : LEVEL_UNKNOWN
  part.charging = raw.charging === true
  return part
}

function parseStatus(raw) {
  var status = defaultStatus()
  var text = String(raw || "").trim()
  if (text === "") { status.lastError = "The oneplus-experience status file is empty"; return status }
  var d
  try { d = JSON.parse(text) } catch (e) { status.lastError = "Could not read the oneplus-experience status file"; return status }
  if (!d || typeof d !== "object" || d.schema_version === undefined) {
    status.lastError = "The oneplus-experience status file has no schema_version"
    return status
  }
  if (d.schema_version > SUPPORTED_SCHEMA) {
    status.lastError = "oneplus-experience speaks status schema " + d.schema_version + ", this panel reads " + SUPPORTED_SCHEMA
    return status
  }
  var s = d.supports || {}
  status.ok = true
  status.lastError = safeText(d.error, 140)
  status.connected = d.connected === true
  status.linked = d.linked === true
  status.deviceName = safeText(d.device_name, 64)
  status.modelName = safeText(d.model_name, 64)
  status.firmware = safeText(d.firmware, 48)
  status.noiseMode = words([d.noise_mode], 1)[0] || ""
  status.ancLevel = words([d.anc_level], 1)[0] || ""
  status.eq = typeof d.eq === "number" && d.eq >= -1 && d.eq < 256 ? Math.floor(d.eq) : -1
  var features = {}
  var raw = d.features && typeof d.features === "object" ? d.features : {}
  for (var k in raw) if (FEATURE_TEXT[k] !== undefined) features[k] = raw[k] === true
  status.features = features
  status.left = partFrom(d.left)
  status.right = partFrom(d.right)
  status.caseBattery = partFrom(d["case"])
  status.modes = words(s.modes, 8)
  status.levels = words(s.levels, 8)
  var presets = []
  var eq = Array.isArray(s.eq) ? s.eq : []
  for (var j = 0; j < eq.length && presets.length < 16; j++) {
    var id = eq[j] ? eq[j].id : undefined
    if (typeof id === "number" && id >= 0 && id < 256) presets.push({ id: Math.floor(id), name: safeText(eq[j].name, 32) })
  }
  status.eqPresets = presets
  status.featureList = words(s.features, 8)
  return status
}

function levelText(level) {
  return level === LEVEL_UNKNOWN ? "—" : level + "%"
}

function levelFraction(level) {
  return level === LEVEL_UNKNOWN ? 0 : Math.max(0, Math.min(1, level / 100))
}

function partMeta(part) {
  if (part.level === LEVEL_UNKNOWN) return ""
  return part.charging ? "Charging" : ""
}

function modeName(mode) {
  return MODE_NAMES[mode] || "Unknown"
}

function elideError(message) {
  return safeText(String(message || "").trim(), 140)
}
