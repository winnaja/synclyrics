"""AutoMix (ส่วนที่ 7): วางแผนการต่อเพลง + กฎเหล็ก + ระบบเรียนรู้จากดาว

ลำดับการตัดสินใจ (planner.plan_transition):
  1. ข้อมูลไม่พร้อม (analysis ยังไม่เสร็จ) / AutoMix พัง -> crossfade ธรรมดา
  2. คะแนนความเข้ากัน (compat) -> < 40 ต่อแบบเรียบ, 40-70 crossfade นุ่ม, >= 70 ให้ bandit เลือก
  3. bandit เลือก action จากรายการที่ "ผ่านกฎเหล็กแล้ว" เท่านั้น (iron_rules.allowed_actions)
  4. สร้าง MixPlan (จุดเข้า/ออก, automation lanes, ทรานซิชั่นภาพ) + decision_log
ไม่แน่ใจเมื่อไหร่ เลือกแบบที่เรียบกว่าเสมอ
"""
