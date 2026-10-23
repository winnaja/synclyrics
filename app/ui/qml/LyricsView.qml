// รายการบรรทัดเนื้อเพลง: เลื่อนตามเพลงด้วยสปริง, scroll เองได้ (หยุดตาม 3 วิ), คลิกบรรทัดเพื่อ seek (สั่ง YouTube)
// หาบรรทัดปัจจุบันด้วย clockBridge.lineIndexAt (bisect ฝั่ง Python) ครั้งเดียวต่อเฟรม
// สถานะว่าง (UX UI ข้อ 7.1): รอเชื่อมต่อ / ยังไม่มีเพลง / กำลังค้นหา / ไม่พบเนื้อเพลง — ข้อความสั้น ไม่มี spinner ใหญ่
import QtQuick

Item {
    id: root
    objectName: "lyricsView"

    // ใช้ไล่บั๊กตำแหน่ง/ความสูงของบรรทัด
    function dumpLines(from, to) {
        var out = []
        for (var i = from; i <= to; ++i) {
            var it = list.itemAtIndex(i)
            if (it) out.push(i + ": y=" + Math.round(it.y) + " h=" + Math.round(it.height)
                + " op=" + it.opacity.toFixed(2) + " words=" + it.words.length)
        }
        return out.join("\n")
    }

    // เวลาของเนื้อเพลง (วินาที) ส่งเข้ามาทุกเฟรม
    property real lyricPos: 0
    property int currentLine: -1
    property bool following: true
    readonly property int lineCount: list.count

    // ใช้ซ้ำในหน้าต่างอื่นได้: ส่งทับสี/ขนาด/การจัดวาง/โหมด (ค่าเริ่มต้น = ตาม cfg ของหน้าต่างลอย)
    property real sizeScale: 1.0
    property string forceAlign: ""
    property bool minimalMode: cfg.ov_mode === "minimal"
    property color colText: cfg.ov_text_color
    property color colInactive: cfg.ov_inactive_color
    property color colAccent: cfg.ov_accent_color
    property color colSecondary: cfg.ov_secondary_color
    property real textOpacity: cfg.ov_text_opacity
    property real inactiveOpacity: cfg.ov_inactive_opacity
    property bool showTranslation: cfg.ov_show_translation && player.showTranslation
    property bool showSourceLabel: true
    property bool labelsHidden: false   // ซ่อนป้ายแหล่งเมื่อผู้ใช้ไม่ขยับเมาส์ (โหมดเต็ม)
    property bool clicksBlocked: false  // กันคลิกทะลุไปกรอเพลง (เช่นตอนเมาส์อยู่บนแถบเมนู)
    property real falloff: cfg.ov_falloff
    property int groupFirst: -1   // ท่อนเดียวกับบรรทัดที่ร้องอยู่: [groupFirst, groupLast]
    property int groupLast: -1
    property real blurAmount: cfg.ov_blur
    property bool pastFilled: true
    property real edgeBlur: 0   // เบลอสูงสุดที่ขอบบน/ล่าง (ใช้คู่กับ edgeFade)
    property real edgeFade: 0   // สัดส่วนความสูงที่เนื้อเพลงจางหายที่ขอบบน/ล่าง (0 = ตัดแข็ง)
    property real anchorFrac: 0.5   // ตำแหน่งแนวตั้งของบรรทัดปัจจุบัน (0.5 = กลาง · Apple Music ≈ 0.4)
    property real topInset: 0   // เว้นด้านบน (เช่นแถบควบคุม) ไม่ให้บรรทัดปัจจุบันชนขอบ

    // ไม่ใช้สปริง: ผู้ใช้เลือกลดการเคลื่อนไหว หรือแอนิเมชันแบบ fade ล้วน (เปลี่ยนบรรทัดแล้วกระโดดไปเลย ไม่เลื่อน)
    readonly property bool jump: cfg.ov_reduced_motion

    // แปลงค่า spring/damping ใน settings เป็นของ SpringAnimation (หน่วยของ Qt ต่างจากฟิสิกส์จริง) ปรับตามความแรงแอนิเมชัน
    readonly property real springK: (cfg.ov_animation === "fade" ? 4.5 : 1.8) * Math.max(0.5, cfg.look_spring_stiffness / 60) * Math.max(0.3, cfg.ov_animation_intensity)
        * Math.max(0.3, cfg.ov_anim_speed)
    readonly property real springD: Math.max(0.05, Math.min(0.9,
        0.5 * cfg.look_spring_damping / (2 * Math.sqrt(cfg.look_spring_stiffness))))

    onLyricPosChanged: {
        var i = clockBridge.lineIndexAtLead(lyricPos, cfg.ov_scroll_lead_s)
        if (i !== currentLine)
            currentLine = i
    }
    onCurrentLineChanged: {
        var oldFirst = groupFirst
        updateGroup()
        // ย้ายภายในท่อนเดียวกัน = ไม่เลื่อนจอ (ไฮไลต์ลงมาบรรทัดล่างเอง) · ขึ้นท่อนใหม่ค่อยเลื่อน
        if (following && cfg.ov_auto_scroll && (groupFirst !== oldFirst || currentLine < 0))
            followTo(groupFirst >= 0 ? groupFirst : currentLine)
    }
    function updateGroup() {
        if (currentLine < 0) { groupFirst = -1; groupLast = -1; return }
        var r = cfg.ov_group_lines ? clockBridge.groupRange(currentLine, cfg.ov_group_gap_s) : [currentLine, currentLine]
        groupFirst = r[0]
        groupLast = r[1]
    }
    Connections {
        target: cfg
        function onOv_group_linesChanged() { root.updateGroup() }
        function onOv_group_gap_sChanged() { root.updateGroup() }
    }

    // เลื่อนให้บรรทัด idx อยู่กลางจอ: ให้ ListView คำนวณปลายทาง แล้วคืนค่าเดิมและปล่อยสปริงวิ่งไป
    // contentY ที่ทำให้บรรทัด idx (หรือทั้งท่อนถ้าอยู่ในท่อนหลายบรรทัด) อยู่กลางจอพอดี — คำนวณจากตำแหน่งจริงของบรรทัด
    function targetY(idx) {
        var first = idx, last = idx
        if (groupLast > groupFirst && idx >= groupFirst && idx <= groupLast) { first = groupFirst; last = groupLast }
        var a = list.itemAtIndex(first)
        var b = list.itemAtIndex(last)
        if (!a || !b)
            return NaN
        return (a.y + b.y + b.height) / 2 - list.height * root.anchorFrac
    }

    // ใช้ตรวจ/ไล่บั๊ก: ระยะ (px) ที่บรรทัดปัจจุบัน/ท่อนปัจจุบันอยู่ห่างจากกลางจอ (0 = กลางพอดี) · NaN = ไม่มีบรรทัดปัจจุบัน
    function centerOffset() {
        var y = targetY(currentLine)
        return isNaN(y) ? NaN : y - list.contentY
    }

    // เวลาไหลของแต่ละบรรทัด (ms): critically damped ω=√stiffness (Apple Music ω≈16 → ~0.4 วิ) หารด้วยความเร็วแอนิเมชัน
    function slideMs() {
        return Math.round(6400 / Math.sqrt(Math.max(40, cfg.look_spring_stiffness)) / Math.max(0.3, cfg.ov_anim_speed))
    }
    // ค่าเด้งเกิน (0 = ไม่เด้ง): damping ต่ำกว่าแบบ critical (2√k) มาก = เด้งนิดๆ (ชุด "เด้งนิดๆ")
    function slideBounce() {
        var zeta = cfg.look_spring_damping / (2 * Math.sqrt(Math.max(40, cfg.look_spring_stiffness)))
        return zeta >= 0.8 ? 0 : Math.min(1.6, (0.8 - zeta) * 3.0)
    }

    // เลื่อนให้บรรทัด idx อยู่กลางจอ: รายการกระโดดไปตำแหน่งใหม่ทันที แล้วให้แต่ละบรรทัดไหลมาเอง (บรรทัดล่างเริ่มช้ากว่าบรรทัดบน)
    // instant = true: ไม่ไหล (เปลี่ยนขนาดหน้าต่าง/แก้ตำแหน่งที่คลาดเล็กน้อย)
    function followTo(idx, instant) {
        if (idx < 0 || list.count === 0)
            return
        var y1 = targetY(idx)
        if (isNaN(y1)) {   // บรรทัดยังไม่ถูกสร้าง: ให้ ListView พาไปก่อนแล้วค่อยคำนวณใหม่
            list.positionViewAtIndex(idx, ListView.Center)
            return
        }
        var dy = y1 - list.contentY
        spring.stop()
        if (jump || instant === true || Math.abs(dy) < 1 || Math.abs(dy) > list.height * 1.5) {
            list.contentY = y1        // seek ไกล/ลดการเคลื่อนไหว: กระโดดเลย ไม่ไหลทุกบรรทัด
            return
        }
        var base = list.itemAtIndex(idx)
        var baseY = base ? base.y : 0
        list.contentY = y1
        var ms = slideMs(), bounce = slideBounce()
        var perPx = cfg.ov_wave_ms / 100.0       // ms ต่อพิกเซลที่ห่างลงไปจากบรรทัดปัจจุบัน (Apple Music ≈ 0.3)
        var lo = Math.max(0, idx - 12), hi = Math.min(list.count - 1, idx + 14)
        for (var i = lo; i <= hi; ++i) {
            var it = list.itemAtIndex(i)
            if (!it) continue
            var d = Math.max(0, Math.min(350, (it.y - baseY) * perPx))   // บรรทัดที่อยู่เหนือบรรทัดปัจจุบันไม่รอ
            it.startSlide(dy, d, ms, bounce)
        }
    }

    // ตรวจเป็นระยะว่ายังอยู่กลางจอไหม (ความสูงบรรทัด/ท่อนเปลี่ยนระหว่างเลื่อน ฯลฯ) ถ้าคลาดก็เลื่อนแก้
    Timer {
        interval: 300
        repeat: true
        running: root.following && cfg.ov_auto_scroll && root.currentLine >= 0 && root.visible
        onTriggered: {
            var y = root.targetY(root.currentLine)
            if (!isNaN(y) && Math.abs(list.contentY - y) > 3)
                root.followTo(root.currentLine, Math.abs(list.contentY - y) < 40)
        }
    }

    function userScrolled() {
        following = false
        spring.stop()
        resumeTimer.restart()
    }

    // ผู้ใช้เลื่อนเอง 3 วิแล้วกลับไปตามเพลง (UX UI ข้อ 3.2 C)
    Timer {
        id: resumeTimer
        interval: Math.round(cfg.ov_resume_s * 1000)
        onTriggered: {
            root.following = true
            if (cfg.ov_auto_scroll)
                root.followTo(root.currentLine)
        }
    }

    // เปลี่ยนโหมด/ขนาด -> จัดบรรทัดปัจจุบันให้อยู่กลางใหม่
    onHeightChanged: if (following) Qt.callLater(function() { root.followTo(root.currentLine, true) })

    SpringAnimation {
        id: spring
        target: list
        property: "contentY"
        spring: root.springK
        damping: root.springD
        epsilon: 0.4
    }

    component GapDots: Item {
        id: gd
        property real gapStart: 0
        property real gapEnd: 0
        property real pos: 0
        property bool shown: false
        readonly property bool valid: gapEnd - gapStart >= 4
        readonly property real frac: valid ? Math.max(0, Math.min(1, (pos - gapStart) / (gapEnd - gapStart))) : 0
        width: list.width
        height: valid ? 56 : 0
        Row {
            id: gdRow
            spacing: 10
            visible: gd.valid && gd.shown
            x: (root.forceAlign.length > 0 ? root.forceAlign : cfg.ov_align) === "center" ? (parent.width - width) / 2 : 8
            y: 14
            Repeater {
                model: 3
                delegate: Rectangle {
                    required property int index
                    width: 14 * Math.max(0.7, root.sizeScale)
                    height: width
                    radius: width / 2
                    color: root.colInactive
                    Rectangle {
                        anchors.fill: parent
                        radius: parent.radius
                        color: root.colText
                        opacity: Math.max(0, Math.min(1, gd.frac * 3 - parent.index))
                    }
                }
            }
        }
    }

    ListView {
        id: list
        anchors.fill: parent
        model: lyricsModel
        clip: true
        // สร้างทุกบรรทัดล่วงหน้า (เนื้อเพลงยาวสุดไม่กี่ร้อยบรรทัด) เพื่อให้ความสูงจริงรู้ครบ: positionViewAtIndex จึงเลื่อนไปกลางจอได้แม่นหลัง seek ไกลๆ
        cacheBuffer: 100000
        boundsBehavior: Flickable.StopAtBounds
        topMargin: height * root.anchorFrac
        bottomMargin: height * (1 - root.anchorFrac)
        spacing: 2
        // โหมด minimal ไม่ให้เลื่อนเองด้วยล้อเมาส์ (มีบรรทัดเดียวที่เห็น)
        interactive: !root.minimalMode

        // ช่วงดนตรีก่อนบรรทัดแรก (อินโทร) และหลังบรรทัดสุดท้าย (เอาท์โทร): จุด 3 จุดเติมตามเวลา เมื่อ AI ฟังแล้วไม่มีเสียงร้อง ≥ 4 วิ
        header: GapDots { gapStart: player.edgeGaps[0]; gapEnd: player.edgeGaps[1]; pos: root.lyricPos
            shown: root.currentLine < 0 && root.lyricPos < player.edgeGaps[1] }
        footer: GapDots { gapStart: player.edgeGaps[2]; gapEnd: player.edgeGaps[3]; pos: root.lyricPos
            shown: root.currentLine === list.count - 1 && root.lyricPos >= player.edgeGaps[2] }

        onMovementStarted: root.userScrolled()
        onCountChanged: {
            if (count === 0)
                root.currentLine = -1
            root.following = true
            spring.stop()
        }

        WheelHandler {
            blocking: false
            enabled: !root.minimalMode
            onWheel: root.userScrolled()
        }

        delegate: LyricLine {
            width: list.width
            sizeScale: root.sizeScale
            forceAlign: root.forceAlign
            minimalMode: root.minimalMode
            colText: root.colText
            colInactive: root.colInactive
            colAccent: root.colAccent
            colSecondary: root.colSecondary
            textOpacity: root.textOpacity
            inactiveOpacity: root.inactiveOpacity
            showTranslation: root.showTranslation
            pastFilled: root.pastFilled
            falloff: root.falloff
            groupFirst: root.groupFirst
            groupLast: root.groupLast
            blurAmount: root.blurAmount
            viewY: list.contentY
            viewH: list.height
            edgeFrac: root.edgeFade
            edgeBlurAmt: root.edgeBlur
            currentLine: root.currentLine
            // เฉพาะบรรทัดปัจจุบันที่ผูกกับเวลา บรรทัดอื่นไม่ถูกประเมินซ้ำทุกเฟรม
            lyricPos: index === root.currentLine ? root.lyricPos : 0
            onClicked: if (cfg.ov_click_seek && !root.clicksBlocked) player.seek(start + player.lyricsOffset)
        }
    }

    // ---------- สถานะเมื่อยังไม่มีเนื้อเพลง ----------
    Column {
        anchors.centerIn: parent
        width: parent.width * 0.86
        spacing: 6
        visible: list.count === 0
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            text: {
                if (!player.bridgeConnected)
                    return player.everConnected ? "การเชื่อมต่อกับ YouTube หลุด — กำลังเชื่อมต่อใหม่..." : "กำลังรอการเชื่อมต่อกับ YouTube"
                if (player.unsupportedReason.length > 0) return "วิดีโอนี้ไม่รองรับเนื้อเพลง (" + player.unsupportedReason + ")"
                if (player.title.length === 0 && player.statusText.length === 0) return "เล่นเพลงใน YouTube แล้วเนื้อเพลงจะขึ้นที่นี่"
                if (player.lyricsLoading) return player.statusText.length > 0 ? player.statusText : "กำลังค้นหาเนื้อเพลง..."
                return "ไม่พบเนื้อเพลง"
            }
            color: root.colSecondary
            font.pixelSize: Math.max(14, cfg.ov_font_size * root.sizeScale * 0.55)
            font.family: cfg.look_font_family
            font.weight: Font.DemiBold
            style: cfg.ov_text_shadow > 0.02 ? Text.Raised : Text.Normal
            styleColor: Qt.rgba(0, 0, 0, 0.5 * cfg.ov_text_shadow)
        }
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            visible: player.bridgeConnected && player.title.length > 0 && !player.lyricsLoading
                && player.unsupportedReason.length === 0
            text: "ลองเปลี่ยนเนื้อเพลงตัวอื่นด้วยปุ่ม \"ตัวอื่น\" ที่แถบควบคุม"
            color: root.colInactive
            font.pixelSize: Math.max(12, cfg.ov_font_size * root.sizeScale * 0.4)
            font.family: cfg.look_font_family
        }
    }

    // ป้ายแหล่งเนื้อเพลงมุมขวาล่าง (เล็ก ไม่รบกวน) — ซ่อนในโหมด minimal
    Text {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 6
        visible: opacity > 0.01 && root.showSourceLabel && cfg.ov_show_source && player.sourceLabel.length > 0 && !root.minimalMode && list.count > 0
        opacity: root.labelsHidden ? 0 : 0.8
        Behavior on opacity { NumberAnimation { duration: 300 } }
        // spec ข้อ 4.4: ถ้ามีเวลาแค่ระดับบรรทัด ห้ามอ้างว่าซิงก์ระดับคำแม่นยำ — บอกว่าเป็นการประมาณ
        text: player.sourceLabel + (player.timingApprox ? " · เวลาทีละคำเป็นการประมาณ" : "")
            + (player.aiTranscribed ? " · ถอดเสียงโดย AI อาจมีคำผิด" : "")
        color: root.colInactive
        font.pixelSize: 11
        font.family: cfg.look_font_family
    }
}
