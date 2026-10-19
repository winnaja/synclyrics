"""ขั้นตอนของ pipeline ต่อเพลง (ข้อ 5.1) — ทุกไฟล์ในนี้รันใน AI worker เท่านั้น

stems.py           แยก vocals/instrumental ด้วย Demucs (ทีละช่วง)
beats.py           BPM/beats/downbeats/ท่อน: allin1 ถ้ามี ไม่งั้น beat_this + ตัวแบ่งท่อนแบบง่าย
key_loudness.py    key (librosa chroma + Krumhansl-Schmuckler) และ LUFS (pyloudnorm)
vocal_activity.py  ช่วงที่มีเสียงร้องจาก stem vocals
align.py           forced alignment ทีละบรรทัด (torchaudio MMS_FA + uroman)
transcribe.py      faster-whisper: ถอดเนื้อเพลง / หาเวลาบรรทัดเมื่อเนื้อเพลงไม่มีเวลา
offset.py          ตรวจ offset ระหว่างเนื้อเพลงกับเสียง (เช่น MV มีช่วงเปิดเรื่อง)
"""
