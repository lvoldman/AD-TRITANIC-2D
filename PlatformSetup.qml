import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 860; height: 760
    minimumWidth: 700; minimumHeight: 680
    visible: true
    title: "Tritanic — Platform Setup"
    color: "#101821"
    palette.window: "#101821"
    palette.windowText: "#e8eff5"
    palette.text: "#e8eff5"
    palette.base: "#101821"
    palette.button: "#293c4c"
    palette.buttonText: "#e8eff5"
    palette.highlight: "#3ebfae"
    font.family: "Segoe UI"
    font.pixelSize: 14

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth
        ColumnLayout {
            width: window.width - 64
            x: 32; spacing: 18
            Item { Layout.preferredHeight: 12 }
            Label { text: "TRITANIC / MOTOR CONTROL"; color: "#55cfbb"; font.pixelSize: 12; font.letterSpacing: 2 }
            Label { text: "Platform setup"; font.pixelSize: 30; font.weight: Font.DemiBold }
            Label { text: "Select a controller and assign its motor outputs to coordinate axes."; color: "#a6b7c8"; Layout.fillWidth: true; wrapMode: Text.WordWrap }

            Frame {
                Layout.fillWidth: true; padding: 20
                background: Rectangle { color: "#192632"; radius: 12; border.color: "#2a3c4b" }
                ColumnLayout {
                    anchors.fill: parent; spacing: 12
                    Label { text: "01  Controller"; font.pixelSize: 18; font.bold: true }
                    RowLayout {
                        Layout.fillWidth: true
                        ComboBox {
                            Layout.fillWidth: true
                            model: setup.boards; textRole: "label"
                            currentIndex: setup.selected
                            displayText: currentIndex < 0 ? "Select a board…" : currentText
                            onActivated: function(index) { setup.chooseBoard(index) }
                        }
                        Button { text: "Refresh"; onClicked: setup.refresh() }
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
                Layout.fillWidth: true; padding: 20
                background: Rectangle { color: "#192632"; radius: 12; border.color: "#2a3c4b" }
                ColumnLayout {
                    anchors.fill: parent; spacing: 12
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "02  Motors and axes"; font.pixelSize: 18; font.bold: true; Layout.fillWidth: true }
                        ComboBox {
                            model: ["2 motors · XY", "3 motors · XYZ"]
                            currentIndex: setup.motorCount - 2
                            onActivated: function(index) { setup.setMotorCount(index + 2) }
                        }
                    }
                    Label { text: "Set the motor count manually. Board outputs are numbered 0, 1 and 2."; color: "#a6b7c8"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                    Repeater {
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
                                Layout.preferredWidth: 220
                                model: ["Output 0", "Output 1", "Output 2"]
                                currentIndex: modelData.motor
                                onActivated: function(index) { setup.assign(modelData.name, index) }
                            }
                        }
                    }
                    Label { text: "Each output can be used once. Selecting an assigned output swaps the two assignments."; color: "#a6b7c8"; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Label { text: setup.message; color: "#73dfc8"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                Button { text: "Save settings"; enabled: setup.selected >= 0; onClicked: setup.save() }
            }
            Label { text: "Setup does not move motors or open a COM port."; color: "#a6b7c8"; font.pixelSize: 12 }
            Item { Layout.preferredHeight: 20 }
        }
    }
}
