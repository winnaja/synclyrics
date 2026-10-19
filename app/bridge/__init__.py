"""การเชื่อมกับส่วนขยาย Chrome (ส่วนที่ 10)

  ส่วนขยาย --(Native Messaging stdio)--> host.py (process เล็ก Chrome เปิดให้)
            --(named pipe)--> pipe_server.py (ในโปรแกรมหลัก)
รูปแบบข้อความทั้งหมดอยู่ใน app/core/messages.py
"""
