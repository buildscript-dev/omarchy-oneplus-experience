import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

Item {
  id: root

  property var settings: ({})
  signal statusUpdated()

  property bool daemonReachable: false
  property var status: Model.defaultStatus()
  property string actionStatus: ""
  property string connectionRequest: ""

  readonly property bool connected: status.connected
  readonly property bool linked: status.connected && status.linked
  readonly property bool hasBattery: daemonReachable
    && (status.left.level !== Model.LEVEL_UNKNOWN
      || status.right.level !== Model.LEVEL_UNKNOWN
      || status.caseBattery.level !== Model.LEVEL_UNKNOWN)
  // The lowest bud, which is what runs out first.
  readonly property int budLevel: {
    var l = status.left.level, r = status.right.level
    if (l === Model.LEVEL_UNKNOWN) return r
    if (r === Model.LEVEL_UNKNOWN) return l
    return Math.min(l, r)
  }
  readonly property bool busy: commandProcess.running || connectionRequest !== ""

  // The panel talks to the daemon by running this plugin's own helper with the
  // system interpreter in isolated mode: no lookup on PATH, no wrapper, and a
  // closed environment. GNU timeout ends the whole process group, and output
  // is capped while it is written (Model.command).
  readonly property string helperPath: {
    var u = String(Qt.resolvedUrl("daemon/oneplus-experience.py"))
    return u.indexOf("file://") === 0 ? decodeURIComponent(u.slice(7)) : ""
  }
  readonly property string runtimeDir: {
    var d = String(Quickshell.env("XDG_RUNTIME_DIR") || "")
    return /^\/run\/user\/[0-9]+$/.test(d) ? d + "/oneplus-experience" : ""
  }
  readonly property var childEnv: ({ PATH: "/usr/bin", LANG: "C.UTF-8" })

  // Optimistic value shown until the daemon confirms or the hold expires.
  property var _pending: ({})
  property var _queue: []

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  // The status file is only watched; its bytes come from the helper, which
  // reads it through verified, non-following descriptors with a size cap.
  function refresh() { if (!statusRead.running) statusRead.running = true }

  function applyLine(raw) {
    daemonReachable = true
    var s = Model.parseStatus(raw)
    if (_pending.noiseMode !== undefined) {
      if (s.noiseMode === _pending.noiseMode) delete _pending.noiseMode
      else s.noiseMode = _pending.noiseMode
    }
    if (_pending.ancLevel !== undefined) {
      if (s.ancLevel === _pending.ancLevel) delete _pending.ancLevel
      else s.ancLevel = _pending.ancLevel
    }
    if (_pending.eq !== undefined) {
      if (s.eq === _pending.eq) delete _pending.eq
      else s.eq = _pending.eq
    }
    status = s
    if ((connectionRequest === "connect" && s.connected) || (connectionRequest === "disconnect" && !s.connected)) {
      connectionRequest = ""
      connectionTimer.stop()
    }
    statusUpdated()
  }

  function stateGone() {
    daemonReachable = false
    status = Model.defaultStatus()
    connectionRequest = ""
  }

  function _run(verb) {
    if (commandProcess.running) { _queue = [verb]; return }
    commandProcess.command = Model.command(root.helperPath, ["ctl", verb], 30)
    commandProcess.running = true
  }

  function _hold(field, value) {
    var p = Object.assign({}, _pending)
    p[field] = value
    _pending = p
    var s = Object.assign({}, status)
    s[field] = value
    status = s
    settleTimer.restart()
  }

  function setNoiseMode(mode) {
    if (!linked || status.modes.indexOf(mode) < 0) return
    _hold("noiseMode", mode)
    _run("noise:" + mode)
  }

  // The daemon owns the cycle (and any automatic override it cancels).
  function cycleNoiseMode() {
    if (!linked) return
    _run("noise:next")
  }

  // Add or drop a mode from the right-click / stem cycle; two at least.
  function toggleCycle(mode) {
    var c = status.cycle.slice()
    var at = c.indexOf(mode)
    if (at >= 0) { if (c.length <= 2) return; c.splice(at, 1) }
    else c = status.modes.filter(function (m) { return m === mode || c.indexOf(m) >= 0 })
    var s = Object.assign({}, status); s.cycle = c; status = s
    _run("cycle:" + c.join(","))
  }

  function setAuto(on) {
    var s = Object.assign({}, status); s.auto = on; status = s
    _run("auto:" + (on ? "on" : "off"))
  }

  function setAncLevel(level) {
    if (!linked || status.levels.indexOf(level) < 0) return
    _hold("noiseMode", "anc")
    _hold("ancLevel", level)
    _run("level:" + level)
  }

  function setEq(id) {
    if (!linked) return
    _hold("eq", id)
    _run("eq:" + id)
  }

  function setFeature(name, on) {
    if (!linked) return
    var s = Object.assign({}, status)
    var f = Object.assign({}, s.features)
    f[name] = on
    s.features = f
    status = s
    _run("feature:" + name + ":" + (on ? "on" : "off"))
  }

  function toggleConnection() {
    if (busy || !daemonReachable) return
    actionStatus = ""
    connectionRequest = status.connected ? "disconnect" : "connect"
    connectionProcess.command = Model.command(root.helperPath, ["ctl", connectionRequest], 30)
    connectionProcess.running = true
    connectionTimer.restart()
  }

  function showError(message) {
    actionStatus = Model.elideError(message)
    actionStatusTimer.restart()
  }

  Timer {
    id: settleTimer
    interval: 4000
    onTriggered: { root._pending = ({}); root.refresh() }
  }

  Timer {
    id: actionStatusTimer
    interval: 3000
    onTriggered: root.actionStatus = ""
  }

  Timer {
    id: connectionTimer
    interval: 20000
    onTriggered: {
      root.connectionRequest = ""
      root.showError("The earbuds did not respond. Check they're out of the case and try again.")
    }
  }

  FileView {
    path: root.runtimeDir === "" ? "" : root.runtimeDir + "/status.json"
    preload: false
    watchChanges: true
    printErrors: false
    onFileChanged: root.refresh()
  }
  // A watch on a file that doesn't exist yet can't fire, so a slow poll picks
  // the daemon up when it starts.
  Timer { interval: 10000; repeat: true; running: true; triggeredOnStart: true; onTriggered: root.refresh() }

  Process {
    id: statusRead
    command: Model.command(root.helperPath, ["status"], 5)
    environment: root.childEnv
    clearEnvironment: true
    stdout: StdioCollector { id: statusOut }
    onExited: function (exitCode) {
      var text = Model.capped(statusOut.text)
      if (exitCode === 0 && text !== null) root.applyLine(text)
      else root.stateGone()
    }
  }

  Process {
    id: commandProcess
    environment: root.childEnv
    clearEnvironment: true
    stdout: StdioCollector { id: commandErr }
    onExited: function (exitCode) {
      if (exitCode !== 0) {
        root._pending = ({})
        root.refresh()
        root.showError(Model.capped(commandErr.text) || "The earbuds rejected the command")
      }
      if (root._queue.length > 0) {
        var next = root._queue[0]
        root._queue = []
        root._run(next)
      }
    }
  }

  Process {
    id: connectionProcess
    environment: root.childEnv
    clearEnvironment: true
    stdout: StdioCollector { id: connectionErr }
    onExited: function (exitCode) {
      if (exitCode !== 0) {
        root.connectionRequest = ""
        connectionTimer.stop()
        root.showError(Model.capped(connectionErr.text) || "Could not reach the earbuds")
      }
      root.refresh()
    }
  }
}
