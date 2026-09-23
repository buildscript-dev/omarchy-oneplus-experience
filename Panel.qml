import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "io.github.buildscript-dev.oneplus-experience"
  ipcTarget: "oneplus-experience"
  manageIpc: false

  property int cursorIndex: 0
  property bool cursorActive: false

  readonly property bool hideWhenDisconnected: setting("hideWhenDisconnected", false) === true
  readonly property bool showBatteryInBar: setting("showBatteryInBar", true) === true
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property var st: pods.status
  readonly property bool live: pods.linked
  readonly property bool levelsVisible: live && st.levels.length > 0 && st.noiseMode === "anc"
  readonly property var featureRows: st.featureList.filter(function (f) { return Model.FEATURE_TEXT[f] !== undefined })
  readonly property string title: st.modelName !== "" ? st.modelName : (st.deviceName !== "" ? st.deviceName : "OnePlus Buds")
  readonly property bool barLow: pods.budLevel !== Model.LEVEL_UNKNOWN && pods.budLevel <= Model.LOW_BATTERY

  readonly property var cursorRows: {
    var rows = []
    if (pods.daemonReachable) rows.push("connection")
    if (!live) return rows
    for (var i = 0; i < st.modes.length; i++) rows.push("mode:" + st.modes[i])
    if (levelsVisible) for (var j = 0; j < st.levels.length; j++) rows.push("level:" + st.levels[j])
    for (var k = 0; k < st.eqPresets.length; k++) rows.push("eq:" + st.eqPresets[k].id)
    for (var m = 0; m < featureRows.length; m++) rows.push("feature:" + featureRows[m])
    return rows
  }
  readonly property string cursorRow: cursorRows.length === 0 ? ""
    : cursorRows[Math.max(0, Math.min(cursorIndex, cursorRows.length - 1))]

  function rowHasCursor(name) { return cursorActive && cursorRow === name }

  function moveCursor(dy) {
    cursorActive = true
    if (cursorRows.length > 0) cursorIndex = Math.max(0, Math.min(cursorRows.length - 1, cursorIndex + dy))
  }

  function focusRow(name) {
    var at = cursorRows.indexOf(name)
    if (at < 0) return
    cursorActive = true
    cursorIndex = at
  }

  function activate(name) {
    var arg = name.substring(name.indexOf(":") + 1)
    if (name === "connection") pods.toggleConnection()
    else if (name.indexOf("mode:") === 0) pods.setNoiseMode(arg)
    else if (name.indexOf("level:") === 0) pods.setAncLevel(arg)
    else if (name.indexOf("eq:") === 0) pods.setEq(parseInt(arg, 10))
    else if (name.indexOf("feature:") === 0) pods.setFeature(arg, st.features[arg] !== true)
  }

  visible: !hideWhenDisconnected || pods.connected
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onOpenedChanged: if (opened) {
    cursorActive = false
    cursorIndex = 0
    if (panelFlick) panelFlick.contentY = 0
    pods.refresh()
    Qt.callLater(function () { keyCatcher.forceActiveFocus() })
  }

  Service {
    id: pods
    settings: root.settings
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): string { pods.refresh(); return "ok" }
    function noise(): string { pods.cycleNoiseMode(); return "ok" }
    function connection(): string { pods.toggleConnection(); return "ok" }
    function status(): string { return Model.modeName(root.st.noiseMode) }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    readonly property bool showLevel: root.showBatteryInBar && pods.connected && pods.budLevel !== Model.LEVEL_UNKNOWN && !vertical
    text: showLevel ? Model.GLYPH_BUDS + " " + pods.budLevel + "%" : Model.GLYPH_BUDS
    fontSize: showLevel ? Style.font.body : Style.bar.iconFont
    foreground: root.barLow ? root.urgent : (pods.connected ? root.barForeground : Qt.darker(root.barForeground, 1.55))
    tooltipText: !pods.connected ? root.title + " · not connected"
      : "L " + Model.levelText(root.st.left.level) + "  R " + Model.levelText(root.st.right.level)
        + "  Case " + Model.levelText(root.st.caseBattery.level)
        + (root.live ? "\n" + Model.modeName(root.st.noiseMode) + " · right-click to switch" : "")
    onPressed: function (buttonCode) {
      if (buttonCode === Qt.RightButton) pods.cycleNoiseMode()
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(900))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function (dx, dy) {
        if (!root.cursorActive) { root.cursorActive = true; return }
        if (dy !== 0) root.moveCursor(dy)
      }
      onActivateRequested: if (root.cursorActive) root.activate(root.cursorRow)
      onCloseRequested: root.close()
      onTabRequested: function (direction) { root.switchPanel(direction) }
      onTextKey: function (t) {
        var key = String(t).toLowerCase()
        if (key === "r") pods.refresh()
        else if (!root.live) return
        else if (key === "n") pods.setNoiseMode("anc")
        else if (key === "s") pods.setNoiseMode("smart")
        else if (key === "t") pods.setNoiseMode("transparency")
        else if (key === "o") pods.setNoiseMode("off")
        else if (key >= "1" && key <= "9") {
          var preset = root.st.eqPresets[parseInt(key, 10) - 1]
          if (preset) pods.setEq(preset.id)
        }
      }

      Flickable {
        id: panelFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: column
          width: panelFlick.width
          spacing: Style.space(12)

          PanelHero {
            id: hero
            width: parent.width
            title: root.title
            meta: root.live ? (Model.modeName(root.st.noiseMode) + (root.st.firmware !== "" ? "  ·  fw " + root.st.firmware : ""))
              : pods.connected ? "Connected, opening controls…"
              : pods.daemonReachable ? "Not connected"
              : "oneplus-experience service is not running"
            foreground: root.foreground
            fontFamily: root.fontFamily
            iconOpacity: pods.connected ? 1.0 : 0.5
            iconComponent: Component {
              Text {
                text: Model.GLYPH_BUDS
                color: pods.connected ? root.foreground : root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.displayLarge
              }
            }
          }

          Text {
            textFormat: Text.PlainText
            visible: pods.actionStatus !== "" || root.st.lastError !== ""
            width: parent.width
            text: pods.actionStatus !== "" ? pods.actionStatus : root.st.lastError
            color: root.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }

          CursorSurface {
            visible: pods.daemonReachable
            width: parent.width
            implicitHeight: connectionLabel.implicitHeight + Style.spacing.rowPaddingX
            foreground: root.foreground
            hasCursor: root.rowHasCursor("connection")
            opacity: pods.busy ? 0.6 : 1.0

            Text {
              id: connectionLabel
              anchors.centerIn: parent
              text: pods.connectionRequest === "disconnect" ? "Disconnecting…"
                : pods.connectionRequest === "connect" ? "Connecting…"
                : pods.connected ? "Disconnect from this PC" : "Connect to this PC"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              textFormat: Text.PlainText
            }

            MouseArea {
              anchors.fill: parent
              enabled: !pods.busy
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onEntered: root.focusRow("connection")
              onClicked: pods.toggleConnection()
            }
          }

          // Battery
          Column {
            visible: pods.hasBattery
            width: parent.width
            spacing: Style.space(10)

            PanelSectionHeader { text: "BATTERY"; foreground: root.foreground; fontFamily: root.fontFamily }

            Column {
              width: parent.width
              spacing: Style.space(6)
              PartRow { width: parent.width; label: "Left"; part: root.st.left }
              PartRow { width: parent.width; label: "Right"; part: root.st.right }
              PartRow { width: parent.width; label: "Case"; part: root.st.caseBattery }
            }
          }

          PanelSeparator { visible: root.live && root.st.modes.length > 0; foreground: root.foreground }

          // Noise control
          Column {
            visible: root.live && root.st.modes.length > 0
            width: parent.width
            spacing: Style.space(10)

            PanelSectionHeader { text: "NOISE CONTROL"; foreground: root.foreground; fontFamily: root.fontFamily }

            Column {
              width: parent.width
              spacing: Style.space(4)
              Repeater {
                model: root.st.modes
                ChoiceRow {
                  required property var modelData
                  width: parent.width
                  rowName: "mode:" + modelData
                  label: Model.modeName(modelData)
                  selected: root.st.noiseMode === modelData
                }
              }
            }

            // ANC strength, as a segmented row under the modes.
            Column {
              visible: root.levelsVisible
              width: parent.width
              spacing: Style.space(6)

              Text {
                textFormat: Text.PlainText
                text: "Strength"
                color: root.foreground
                opacity: 0.6
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                leftPadding: Style.space(10)
              }

              RowLayout {
                width: parent.width
                spacing: Style.space(6)
                Repeater {
                  model: root.st.levels
                  Segment {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    rowName: "level:" + modelData
                    label: Model.LEVEL_NAMES[modelData] || modelData
                    selected: root.st.ancLevel === modelData
                  }
                }
              }
            }
          }

          PanelSeparator { visible: root.live && root.st.eqPresets.length > 0; foreground: root.foreground }

          // Equalizer
          Column {
            visible: root.live && root.st.eqPresets.length > 0
            width: parent.width
            spacing: Style.space(10)

            PanelSectionHeader { text: "SOUND"; foreground: root.foreground; fontFamily: root.fontFamily }

            GridLayout {
              width: parent.width
              columns: 2
              rowSpacing: Style.space(6)
              columnSpacing: Style.space(6)
              Repeater {
                model: root.st.eqPresets
                Segment {
                  required property var modelData
                  Layout.fillWidth: true
                  Layout.preferredWidth: 1
                  rowName: "eq:" + modelData.id
                  label: modelData.name
                  selected: root.st.eq === modelData.id
                }
              }
            }
          }

          PanelSeparator { visible: root.live && root.featureRows.length > 0; foreground: root.foreground }

          // Switches
          Column {
            visible: root.live && root.featureRows.length > 0
            width: parent.width
            spacing: Style.space(6)

            Repeater {
              model: root.featureRows
              ToggleRow {
                required property var modelData
                width: parent.width
                rowName: "feature:" + modelData
                label: Model.FEATURE_TEXT[modelData][0]
                caption: Model.FEATURE_TEXT[modelData][1]
                checked: root.st.features[modelData] === true
              }
            }
          }

          Text {
            textFormat: Text.PlainText
            visible: !pods.connected || !pods.daemonReachable
            width: parent.width
            text: pods.daemonReachable
              ? "Take your OnePlus Buds out of the case, or press Connect, to see battery and controls."
              : "Start it with: systemctl --user start oneplus-experience"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
          }
        }
      }
    }
  }

  component PartRow: Item {
    id: partRow
    property string label: ""
    property var part: Model.defaultPart()
    readonly property bool low: part.level !== Model.LEVEL_UNKNOWN && part.level <= Model.LOW_BATTERY && !part.charging

    implicitHeight: partLayout.implicitHeight

    RowLayout {
      id: partLayout
      anchors.left: parent.left
      anchors.right: parent.right
      spacing: Style.space(8)

      Text {
        textFormat: Text.PlainText
        text: partRow.label
        color: root.foreground
        opacity: 0.6
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        Layout.preferredWidth: Math.max(Style.space(44), implicitWidth + Style.space(10))
      }

      Rectangle {
        id: track
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignVCenter
        implicitHeight: Style.space(6)
        radius: height / 2
        color: Qt.darker(root.foreground, 3.2)

        Rectangle {
          width: track.width * Model.levelFraction(partRow.part.level)
          height: parent.height
          radius: parent.radius
          color: partRow.low ? root.urgent : root.foreground
          Behavior on width { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
        }
      }

      Text {
        textFormat: Text.PlainText
        text: Model.levelText(partRow.part.level)
        color: partRow.low ? root.urgent : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        horizontalAlignment: Text.AlignRight
        Layout.preferredWidth: Style.space(38)
      }

      Text {
        textFormat: Text.PlainText
        text: Model.partMeta(partRow.part)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
        Layout.preferredWidth: Style.space(56)
      }
    }
  }

  component Segment: CursorSurface {
    id: seg
    property string rowName: ""
    property string label: ""
    property bool selected: false

    implicitHeight: segLabel.implicitHeight + Style.spacing.rowPaddingX
    foreground: root.foreground
    hasCursor: root.rowHasCursor(rowName)
    current: selected
    bordered: true

    Text {
      id: segLabel
      anchors.centerIn: parent
      width: parent.width - Style.space(8)
      horizontalAlignment: Text.AlignHCenter
      elide: Text.ElideRight
      textFormat: Text.PlainText
      text: seg.label
      color: root.foreground
      opacity: seg.selected ? 1.0 : 0.7
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      font.bold: seg.selected
    }
    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: root.focusRow(seg.rowName)
      onClicked: root.activate(seg.rowName)
    }
  }

  component ChoiceRow: CursorSurface {
    id: choiceRow
    property string rowName: ""
    property string label: ""
    property string caption: ""
    property bool selected: false

    hasCursor: root.rowHasCursor(rowName)
    foreground: root.foreground
    implicitHeight: choiceContent.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: root.focusRow(choiceRow.rowName)
      onClicked: root.activate(choiceRow.rowName)
    }

    RowLayout {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(8)

      ColumnLayout {
        id: choiceContent
        Layout.fillWidth: true
        spacing: Style.space(1)

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: choiceRow.label
          color: root.foreground
          opacity: choiceRow.selected ? 1.0 : 0.75
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }
        Text {
          textFormat: Text.PlainText
          visible: choiceRow.caption !== ""
          Layout.fillWidth: true
          text: choiceRow.caption
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }

      Text {
        textFormat: Text.PlainText
        Layout.alignment: Qt.AlignVCenter
        text: Model.GLYPH_CHECK
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.icon
        opacity: choiceRow.selected ? 1.0 : 0.0
      }
    }
  }

  component ToggleRow: CursorSurface {
    id: toggleRow
    property string rowName: ""
    property string label: ""
    property string caption: ""
    property bool checked: false

    hasCursor: root.rowHasCursor(rowName)
    foreground: root.foreground
    implicitHeight: toggleContent.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: root.focusRow(toggleRow.rowName)
      onClicked: root.activate(toggleRow.rowName)
    }

    RowLayout {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(8)

      ColumnLayout {
        id: toggleContent
        Layout.fillWidth: true
        spacing: Style.space(1)

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: toggleRow.label
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }
        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: toggleRow.caption
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }

      ToggleSwitch {
        Layout.alignment: Qt.AlignVCenter
        checked: toggleRow.checked
        busy: pods.busy
        hasCursor: toggleRow.hasCursor
        foreground: root.foreground
        onToggled: root.activate(toggleRow.rowName)
      }
    }
  }
}
