"""ของกลางที่ทุก module ใช้ร่วมกัน: path, config, log, ฐานข้อมูล, นาฬิกา, ข้อความระหว่าง process

กฎ: module ใน app/core ห้าม import อะไรจาก app/* ส่วนอื่น (กันวงจร import)
และห้าม import ไลบรารีหนัก (PySide6, torch) ตอนโหลด module
"""
