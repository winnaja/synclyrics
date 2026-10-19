"""AI บน GPU (ส่วนที่ 5)

process หลัก: client.py (เปิด/คุย/เฝ้า worker) + scheduler.py (คิวงานตามความสำคัญ)
AI worker process: worker.py + pipeline/* (โหลด torch ที่นี่เท่านั้น — process หลักห้าม import torch)
"""
