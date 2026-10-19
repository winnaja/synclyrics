// รายการบรรทัดเนื้อเพลง: เลื่อนตามเพลงด้วยสปริง, scroll เองได้ (หยุดตาม 3 วิ), คลิกบรรทัดเพื่อ seek
// หาบรรทัดปัจจุบันด้วย clockBridge.lineIndexAt (bisect ฝั่ง Python) ครั้งเดียวต่อเฟรม
import QtQuick

Item {
    id: root
    objectName: "lyricsView"

    // ใช้ไล่บั๊กตำแหน่ง/ความสูงของบรรทัด (เรียกจาก test/สคริปต์ตรวจ)
    function dumpTree(idx) {
        var it = list.itemAtIndex(idx)
        if (!it) return "no item"
        var out = []
        function walk(o, depth, pre) {
            var t = (o.text !== undefined) ? (" text='" + o.text + "'") : ""
            out.push(pre + "[" + depth + "] x=" + Math.round(o.x) + " y=" + Math.round(o.y) + " w=" + Math.round(o.width) + " h=" + Math.round(o.height)
                + " vis=" + o.visible + " op=" + o.opacity + " sc=" + o.scale + t)
            if (depth < 4) for (var i = 0; i < o.children.length && i < 40; ++i) walk(o.children[i], depth + 1, pre + "  ")
        }
        walk(it, 0, "")
        return out.join("
")
    }

    function dumpLines(from, to) {
        var out = []
        for (var i = from; i <= to; ++i) {
            var it = list.itemAtIndex(i)
            if (it) out.push(i + ": y=" + Math.round(it.y) + " h=" + Math.round(it.height) + " ih=" + Math.round(it.implicitHeight)
                + " flowH=" + Math.round(it.children[0].implicitHeight) + " words=" + it.words.length)
        }
        return out.join("
")
    }

    // เวลาของเนื้อเพลง (วินาที) ส่งเข้ามาจาก Main ทุกเฟรม
    property real lyricPos: 0
    property int currentLine: -1
    property bool following: true

    // แปลงค่า spring/damping ใน settings เป็นของ SpringAnimation (หน่วยของ Qt ต่างจากฟิสิกส์จริง)
    readonly property real springK: Math.max(0.5, look.spring_stiffness / 60)
    readonly property real springD: Math.max(0.05, Math.min(0.9,
        0.5 * look.spring_damping / (2 * Math.sqrt(look.spring_stiffness))))

    onLyricPosChanged: {
        var i = clockBridge.lineIndexAt(lyricPos)
        if (i !== currentLine)
            currentLine = i
    }
    onCurrentLineChanged: if (following) followTo(currentLine)

    // เลื่อนให้บรรทัด idx อยู่กลางจอ: ให้ ListView คำนวณปลายทาง แล้วคืนค่าเดิมและปล่อยสปริงวิ่งไป
    function followTo(idx) {
        if (idx < 0 || list.count === 0)
            return
        var y0 = list.contentY
        list.positionViewAtIndex(idx, ListView.Center)
        var y1 = list.contentY
        list.contentY = y0
        spring.to = y1
        if (!spring.running)
            spring.start()
    }

    function userScrolled() {
        following = false
        spring.stop()
        resumeTimer.restart()
    }

    // ผู้ใช้เลื่อนเอง 3 วิแล้วกลับไปตามเพลง
    Timer {
        id: resumeTimer
        interval: 3000
        onTriggered: {
            root.following = true
            root.followTo(root.currentLine)
        }
    }

    SpringAnimation {
        id: spring
        target: list
        property: "contentY"
        spring: root.springK
        damping: root.springD
        epsilon: 0.4
    }

    ListView {
        id: list
        anchors.fill: parent
        model: lyricsModel
        clip: true
        // สร้างทุกบรรทัดล่วงหน้า (เนื้อเพลงยาวสุดไม่กี่ร้อยบรรทัด) เพื่อให้ความสูงจริงรู้ครบ: positionViewAtIndex จึงเลื่อนไปกลางจอได้แม่นหลัง seek ไกลๆ
        cacheBuffer: 100000
        boundsBehavior: Flickable.StopAtBounds
        topMargin: height / 2
        bottomMargin: height / 2
        spacing: 4

        onMovementStarted: root.userScrolled()
        onCountChanged: {
            if (count === 0)
                root.currentLine = -1
            root.following = true
            spring.stop()
        }

        WheelHandler {
            blocking: false
            onWheel: root.userScrolled()
        }

        delegate: LyricLine {
            width: list.width
            currentLine: root.currentLine
            // เฉพาะบรรทัดปัจจุบันที่ผูกกับเวลา บรรทัดอื่นไม่ถูกประเมินซ้ำทุกเฟรม
            lyricPos: index === root.currentLine ? root.lyricPos : 0
            onClicked: player.seek(start + player.lyricsOffset)
        }
    }

    // ยังไม่มีเนื้อเพลง
    Text {
        anchors.centerIn: parent
        width: parent.width * 0.8
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        visible: list.count === 0
        text: player.statusText.length > 0 ? player.statusText : "เนื้อเพลงจะแสดงที่นี่"
        color: "#80ffffff"
        font.pixelSize: 20
        font.family: look.font_family
    }

    // ป้ายแหล่งเนื้อเพลงมุมขวาบน
    Text {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 4
        visible: player.sourceLabel.length > 0
        text: player.sourceLabel
        color: "#99ffffff"
        font.pixelSize: 12
        font.family: look.font_family
    }
}
