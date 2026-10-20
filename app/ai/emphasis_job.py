"""งานเลือก "คำเน้น" ของเพลงด้วยโมเดลภาษาในเครื่อง (Qwen3-4B-Instruct ผ่าน CTranslate2 int8) — รันใน AI worker เท่านั้น

ขอให้โมเดลเลือกทีละบรรทัดว่าคำไหนมีน้ำหนักทางอารมณ์ที่สุด (few-shot รูปแบบ "N: word") — ทดลองแล้วได้ผลดีกว่าการให้วิเคราะห์ทั้งเพลงรอบเดียว
(แบบนั้นโมเดลเล็กตอบมั่ว/ลอกตัวอย่าง) · ผลเป็นคำต่อบรรทัด ตัวเลือกบรรทัดที่เน้นจริงอยู่ที่ app/ai/emphasis.py
VRAM: 4B int8 ≈ 4.3 GB บน 8 GB — ปล่อย Whisper/Demucs/MMS ก่อนโหลด (โหลดกลับเองเมื่อมีงานถัดไป) แล้วปล่อยโมเดลภาษาทันทีหลังจบ
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

CHUNK = 50      # จำนวนบรรทัดต่อรอบถาม (ยาวกว่านี้โมเดลเริ่มหลงเลขบรรทัด)

SYSTEM = (
    "You choose emphasis words for animated song lyrics. For each numbered lyric line you receive, output ONE word that carries the most "
    "emotional impact in that line (a word of the original line, exactly as written), or '-' if the line has no strong word "
    "(filler, ad-libs, very short lines).\n"
    "Answer with one line per input line in the form 'N: word'. No explanations."
)
SHOT_IN = "1. I'm walking down this lonely road\n2. Yeah yeah\n3. And I can't stop the burning in my heart\n4. Take me home"
SHOT_OUT = "1: lonely\n2: -\n3: burning\n4: home"


def model_path(worker: Any) -> Path:
    """โฟลเดอร์โมเดล: <model_dir>/llm/<ชื่อ> — ไม่มี = โหลดจาก Hugging Face ครั้งแรก (~4 GB)"""
    cfg = worker.mcfg.get("emphasis", {})
    md = Path(worker.mcfg.get("model_dir") or ".")
    local = md / "llm" / str(cfg.get("local_name", "qwen3-4b-instruct-2507-ct2-int8"))
    if not (local / "model.bin").exists():
        from huggingface_hub import snapshot_download

        snapshot_download(str(cfg.get("model", "jncraton/Qwen3-4B-Instruct-2507-ct2-int8")), local_dir=str(local))
    return local


def build_prompt(lines: list[str]) -> str:
    user = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(lines))
    return (f"<|im_start|>system\n{SYSTEM}<|im_end|>\n<|im_start|>user\n{SHOT_IN}<|im_end|>\n<|im_start|>assistant\n{SHOT_OUT}<|im_end|>\n"
            f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n")


def parse_answers(text: str, lines: list[str]) -> dict[int, str]:
    """'N: word' ทุกบรรทัดของคำตอบ -> {ดัชนีบรรทัด(เริ่ม 0): คำ} · เก็บเฉพาะคำที่อยู่ในบรรทัดนั้นจริง (ตัวพิมพ์/เครื่องหมายไม่สน) และไม่ใช่ '-'"""
    out: dict[int, str] = {}
    for m in re.finditer(r"(\d+)\s*[:：]\s*(.+)", text or ""):
        k = int(m.group(1)) - 1
        w = m.group(2).strip().strip("\"'`.,!?")
        if not (0 <= k < len(lines)) or not w or w == "-":
            continue
        toks = [t.strip("\"'`.,!?()[]") for t in lines[k].split()]
        hit = next((t for t in toks if t.casefold() == w.casefold()), None)
        if hit:
            out[k] = hit
    return out


def run(worker: Any, p: dict[str, Any]) -> None:
    lines = [str(x) for x in p.get("lines", [])]
    answers: dict[int, str] = {}
    if lines:
        from app.ai.llm import LyricsLLM

        worker._whisper = None
        worker._demucs = None
        worker._mms = None
        if worker.device == "cuda":
            worker._torch.cuda.empty_cache()
        worker._check_cancel(p)
        llm = LyricsLLM(model_path(worker), worker.device)
        try:
            for a in range(0, len(lines), CHUNK):
                worker._check_cancel(p)
                chunk = lines[a:a + CHUNK]
                ids = llm.tok.encode(build_prompt(chunk), add_special_tokens=False).tokens
                res = llm.gen.generate_batch([ids], max_length=60 + 12 * len(chunk), sampling_topk=1, include_prompt_in_result=False,
                                             end_token="<|im_end|>", repetition_penalty=1.0)
                text = llm.tok.decode(res[0].sequences_ids[0], skip_special_tokens=True)
                for k, w in parse_answers(text, chunk).items():
                    answers[a + k] = w
        finally:
            llm.close()
            del llm
            if worker.device == "cuda":
                worker._torch.cuda.empty_cache()
    worker.emit("result", {"job_id": p["job_id"], "kind": "emphasis_final",
                           "data": {"video_id": p.get("video_id"), "answers": {str(k): v for k, v in answers.items()}}})
