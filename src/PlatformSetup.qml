import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: Math.min(1100, Screen.desktopAvailableWidth - 40)
    height: Math.min(720, Screen.desktopAvailableHeight - 60)
    minimumWidth: 860; minimumHeight: 520
    visible: true
    title: "Tritanic — Platform Control"
    color: "#101821"
    palette.window: "#101821"
    palette.windowText: "#e8eff5"
    palette.text: "#e8eff5"
    palette.base: "#101821"
    palette.button: "#293c4c"
    palette.buttonText: "#e8eff5"
    palette.highlight: "#3ebfae"
    font.family: "Segoe UI"
    font.pixelSize: 13

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth
        ColumnLayout {
            width: window.width - 40
            x: 20; spacing: 12
            Item { Layout.preferredHeight: 12 }
            Label { text: "TRITANIC / MOTOR CONTROL"; color: "#55cfbb"; font.pixelSize: 12; font.letterSpacing: 2 }
            Label { text: "Platform control"; font.pixelSize: 26; font.weight: Font.DemiBold }
            Label { text: "Select a controller and assign its motor outputs to coordinate axes."; color: "#a6b7c8"; Layout.fillWidth: true; wrapMode: Text.WordWrap }

            // Setup and motion stay side by side; the page can scroll vertically on small screens.
            RowLayout {
                Layout.fillWidth: true
                spacing: 16
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 360
                    Layout.alignment: Qt.AlignTop
                    spacing: 16
                    Frame {
                        Layout.fillWidth: true; padding: 16
                        background: Rectangle { color: "#192632"; radius: 12; border.color: "#2a3c4b" }
                        ColumnLayout {
                            anchors.fill: parent; spacing: 12
                            Label { text: "01  Controller"; font.pixelSize: 18; font.bold: true }
                                ComboBox {
                                    enabled: !setup.connected && !setup.busy
                                    Layout.fillWidth: true
                                    model: setup.boards; textRole: "label"
                                    currentIndex: setup.selected
                                    displayText: currentIndex < 0 ? "Select a board…" : currentText
                                    onActivated: function(index) { setup.chooseBoard(index) }
                                }
                            RowLayout {
                                Layout.fillWidth: true
                                Button { text: "Refresh"; enabled: !setup.connected && !setup.busy; onClicked: setup.refresh() }
                                Button {
                                    objectName: "connectButton"
                                    text: setup.connected ? "Disconnect" : "Connect"
                                    enabled: setup.selected >= 0 && !setup.busy
                                    onClicked: setup.toggleConnection()
                                }
                                Rectangle {
                                    objectName: "connectionLed"
                                    Layout.preferredWidth: 12; Layout.preferredHeight: 12
                                    radius: 6
                                    color: setup.connected ? "#40d58b" : "#ed6262"
                                    border.color: setup.connected ? "#8ae9b6" : "#ff9a9a"
                                    Accessible.name: setup.connected ? "Connected" : "Disconnected"
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: "Module address (TMCL)" }
                                SpinBox {
                                    objectName: "boardAddress"
                                    from: 1; to: 255; value: setup.boardAddress
                                    editable: true
                                    enabled: !setup.connected && !setup.busy
                                    onValueModified: setup.setBoardAddress(value)
                                    ToolTip.visible: hovered
                                    ToolTip.text: "TMCL destination address, 1–255. Must match the controller’s configured address."
                                }
                            }
                            Label { text: setup.boardDetails; color: "#a6b7c8"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                            Label {
                                text: "The USB location identifies the socket if the COM number changes. It does not identify the board itself. TMCSTEP is not a unique serial number."
                                color: "#a6b7c8"; font.pixelSize: 12
                                Layout.fillWidth: true; wrapMode: Text.WordWrap
                            }
                        }
                    }
                    Frame {
                        Layout.fillWidth: true; padding: 16
                        background: Rectangle { color: "#192632"; radius: 12; border.color: "#2a3c4b" }
                        ColumnLayout {
                            anchors.fill: parent; spacing: 12
                            ColumnLayout {
                                Layout.fillWidth: true
                                Label { text: "02  Motors and axes"; font.pixelSize: 18; font.bold: true; Layout.fillWidth: true }
                                ComboBox {
                                    enabled: !setup.connected && !setup.busy
                                    model: ["2 motors · XY", "3 motors · XYZ"]
                                    currentIndex: setup.motorCount - 2
                                    onActivated: function(index) { setup.setMotorCount(index + 2) }
                                }
                            }
                            Label { text: "Set the motor count manually. Board outputs are numbered 0, 1 and 2."; color: "#a6b7c8"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                            Repeater {
                                // Only active coordinates are supplied: X/Y or X/Y/Z.
                                model: setup.axisRows
                                delegate: RowLayout {
                                    required property var modelData
                                    Layout.fillWidth: true; spacing: 16
                                    Rectangle {
                                        width: 38; height: 38; radius: 9; color: "#244640"
                                        Label { anchors.centerIn: parent; text: modelData.name; color: "#73dfc8"; font.bold: true; font.pixelSize: 18 }
                                    }
                                    Label { text: "Axis " + modelData.name; Layout.fillWidth: true }
                                    ComboBox {
                                        enabled: !setup.connected && !setup.busy
                                        Layout.preferredWidth: 125
                                        model: ["Output 0", "Output 1", "Output 2"]
                                        currentIndex: modelData.motor
                                        // Python swaps occupied outputs to keep assignments unique.
                                        onActivated: function(index) { setup.assign(modelData.name, index) }
                                    }
                                }
                            }
                            Label { text: "Each output can be used once. Selecting an assigned output swaps the two assignments."; color: "#a6b7c8"; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        }
                    }
                }
                Frame {
                    Layout.fillWidth: true; Layout.preferredWidth: 600; Layout.alignment: Qt.AlignTop; padding: 16
                    background: Rectangle { color: "#192632"; radius: 12; border.color: "#2a3c4b" }
                    ColumnLayout {
                        anchors.fill: parent; spacing: 12
                        Label { text: "03  Motion"; font.pixelSize: 18; font.bold: true }
                        Label {
                            text: "Distance / target is in microsteps. Absolute uses the current controller origin; unchecked means Relative."
                            color: "#a6b7c8"; Layout.fillWidth: true; wrapMode: Text.WordWrap
                        }
                        Repeater {
                            model: setup.axisRows
                            delegate: ColumnLayout {
                                id: motionRow
                                required property var modelData
                                Layout.fillWidth: true; spacing: 8
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 8
                                Label { text: "Axis " + modelData.name; font.bold: true; Layout.preferredWidth: 45 }
                                Label { text: "Dist:" }
                                TextField {
                                    id: distance
                                    objectName: "distance" + modelData.name
                                    Layout.fillWidth: true; Layout.minimumWidth: 80
                                    text: modelData.distance
                                    enabled: !setup.busy
                                    validator: IntValidator { bottom: -2147483648; top: 2147483647 }
                                    onTextEdited: setup.setMotionInput(modelData.name, text, absolute.checked)
                                }
                                CheckBox {
                                    id: absolute
                                    objectName: "absolute" + modelData.name
                                    text: "Absolute"; checked: modelData.absolute
                                    enabled: !setup.busy
                                    onToggled: setup.setMotionInput(modelData.name, distance.text, checked)
                                }
                                Button {
                                    objectName: "move" + modelData.name
                                    text: "Move single axis " + modelData.name
                                    enabled: setup.connected && !setup.busy && distance.acceptableInput
                                    onClicked: {
                                        setup.setMotionInput(modelData.name, distance.text, absolute.checked)
                                        setup.move(modelData.name, speed.value, acceleration.value, timeout.value)
                                    }
                                }
                                }
                                RowLayout {
                                    Layout.fillWidth: true; spacing: 8
                                    Button {
                                        objectName: "setHome" + modelData.name
                                        text: "Set home " + modelData.name
                                        enabled: setup.connected && !setup.busy
                                        ToolTip.visible: hovered
                                        ToolTip.text: "Set the current encoder reading to zero without moving."
                                        onClicked: setup.setHome(modelData.name)
                                    }
                                    Button {
                                        objectName: "goHome" + modelData.name
                                        text: "Go home " + modelData.name
                                        enabled: setup.connected && !setup.busy
                                        ToolTip.visible: hovered
                                        ToolTip.text: "Move this motor back to encoder zero."
                                        onClicked: setup.goHome(modelData.name, speed.value, acceleration.value, timeout.value)
                                    }
                                }
                            }
                        }
                        Label {
                            text: "Home refers to encoder zero. Set home keeps the step-counter origin unchanged."
                            color: "#a6b7c8"; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap
                        }
                        GridLayout {
                            Layout.fillWidth: true; columns: 3; columnSpacing: 12; rowSpacing: 4
                            Label { text: "Speed (AP4)" }
                            Label { text: "Accel. (AP5)" }
                            Label { text: "Timeout (s)" }
                            SpinBox { id: speed; objectName: "motionSpeed"; Layout.fillWidth: true; from: 1; to: 2047; value: 200; editable: true; enabled: !setup.busy }
                            SpinBox { id: acceleration; objectName: "motionAcceleration"; Layout.fillWidth: true; from: 1; to: 2047; value: 100; editable: true; enabled: !setup.busy }
                            SpinBox { id: timeout; Layout.fillWidth: true; from: 1; to: 3600; value: 20; editable: true; enabled: !setup.busy }
                        }
                        Label { text: "Speed and acceleration use TMCL internal units, not microsteps/s or mm/s."; color: "#a6b7c8"; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                        RowLayout {
                            Layout.fillWidth: true
                            Button {
                                objectName: "movePlatform"
                                text: "Move platform"
                                enabled: setup.connected && !setup.busy
                                onClicked: setup.move("", speed.value, acceleration.value, timeout.value)
                            }
                            Button {
                                objectName: "stopMotion"
                                text: "STOP"
                                enabled: setup.connected
                                palette.button: "#873d43"
                                onClicked: setup.stopMotion()
                            }
                        }
                            Button {
                                text: "Apply tested motor settings"
                                enabled: setup.connected && !setup.busy
                                onClicked: setup.configureMotors()
                            }
                        Label {
                            text: "Connect keeps existing settings. Apply tested settings explicitly if needed: 16 microsteps, run current 48, hold 16, encoder scaling 800 (RAM only)."
                            color: "#a6b7c8"; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap
                        }
                        Label { text: setup.motionSummary; color: "#b9d8d1"; visible: text.length > 0; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Label { text: setup.message; color: "#73dfc8"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                Button { text: "Save settings"; enabled: setup.selected >= 0 && !setup.busy; onClicked: setup.save() }
            }
            Label { text: "Motion starts only with a Move button. STOP requests a soft stop and retains holding current."; color: "#a6b7c8"; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            Item { Layout.preferredHeight: 20 }
        }
    }
}
