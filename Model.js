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
  part.level = isFinite(n) ? n : LEVEL_UNKNOWN
  part.charging = raw.charging === true
  return part
}

function parseStatus(raw) {
  var status = defaultStatus()
  var text = String(raw || "").trim()
  if (text === "") { status.lastError = "The onepods status file is empty"; return status }
  var d
  try { d = JSON.parse(text) } catch (e) { status.lastError = "Could not read the onepods status file"; return status }
  if (!d || typeof d !== "object" || d.schema_version === undefined) {
    status.lastError = "The onepods status file has no schema_version"
    return status
  }
  if (d.schema_version > SUPPORTED_SCHEMA) {
    status.lastError = "onepods speaks status schema " + d.schema_version + ", this panel reads " + SUPPORTED_SCHEMA
    return status
  }
  var s = d.supports || {}
  status.ok = true
  status.lastError = String(d.error || "")
  status.connected = d.connected === true
  status.linked = d.linked === true
  status.deviceName = String(d.device_name || "")
  status.modelName = String(d.model_name || "")
  status.firmware = String(d.firmware || "")
  status.noiseMode = String(d.noise_mode || "")
  status.ancLevel = String(d.anc_level || "")
  status.eq = typeof d.eq === "number" ? d.eq : -1
  status.features = d.features && typeof d.features === "object" ? d.features : {}
  status.left = partFrom(d.left)
  status.right = partFrom(d.right)
  status.caseBattery = partFrom(d["case"])
  status.modes = Array.isArray(s.modes) ? s.modes : []
  status.levels = Array.isArray(s.levels) ? s.levels : []
  status.eqPresets = Array.isArray(s.eq) ? s.eq : []
  status.featureList = Array.isArray(s.features) ? s.features : []
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
  var text = String(message || "").trim()
  return text.length > 140 ? text.substring(0, 137) + "…" : text
}
