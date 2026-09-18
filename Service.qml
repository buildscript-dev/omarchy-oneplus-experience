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

  readonly property string ctlPath: String(setting("ctlPath", "") || "onepods-ctl")
  readonly property string statePath: (Quickshell.env("XDG_STATE_HOME")
    || Quickshell.env("HOME") + "/.local/state") + "/onepods/status.json"

  // Optimistic value shown until the daemon confirms or the hold expires.
  property var _pending: ({})
  property var _queue: []

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function refresh() { stateFile.reload() }

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
    commandProcess.command = [ctlPath, verb]
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

  function cycleNoiseMode() {
    var modes = status.modes
    if (!linked || modes.length === 0) return
    var at = modes.indexOf(status.noiseMode)
    setNoiseMode(modes[(at + 1) % modes.length])
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
    connectionProcess.command = [ctlPath, connectionRequest]
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
    id: stateFile
    path: root.statePath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.applyLine(text())
    onLoadFailed: root.stateGone()
  }

  Process {
    id: commandProcess
    stderr: StdioCollector { id: commandErr; waitForEnd: true }
    onExited: function (exitCode) {
      if (exitCode !== 0) {
        root._pending = ({})
        root.refresh()
        root.showError(commandErr.text || "onepods-ctl rejected the command")
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
    stderr: StdioCollector { id: connectionErr; waitForEnd: true }
    onExited: function (exitCode) {
      if (exitCode !== 0) {
        root.connectionRequest = ""
        connectionTimer.stop()
        root.showError(connectionErr.text || "Could not reach the earbuds")
      }
      root.refresh()
    }
  }
}
