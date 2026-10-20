"""งานแปลเนื้อเพลงทั้งเพลงเป็นภาษาไทยด้วยโมเดลแปลในเครื่อง (NLLB-200 1.3B ผ่าน CTranslate2 int8) — รันใน AI worker เท่านั้น

ทำไมไม่แปลทีละบรรทัดโดดๆ: เพลงเดียวกันมีท่อนซ้ำ (ฮุก) ต้องแปลให้ตรงกันทุกครั้ง และบรรทัดสั้นๆ ที่ไม่มีบริบทแปลผิดบ่อย
  - บรรทัดที่ซ้ำกัน (หลัง normalize) แปลครั้งเดียวแล้วใช้ซ้ำ
  - (plan() ยังคำนวณ context_for ของบรรทัดสั้นไว้ แต่ไม่ได้ใช้ — วัดจริงแล้ว NLLB ปนคำแปลบริบทเข้าผล)
  - แปลเป็นชุด (batch) เรียงตามความยาวเพื่อเร็วและกิน VRAM คงที่
โมเดลโหลดตอนใช้และคืน VRAM หลังเสร็จ (translate.keep_loaded=false) เพื่อไม่ชนงบ VRAM ของ Demucs/Whisper
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# ISO 639-1 -> รหัสภาษาของ NLLB-200
NLLB_CODES = {
    "en": "eng_Latn", "ja": "jpn_Jpan", "ko": "kor_Hang", "zh": "zho_Hans", "yue": "yue_Hant", "th": "tha_Thai",
    "es": "spa_Latn", "fr": "fra_Latn", "de": "deu_Latn", "it": "ita_Latn", "pt": "por_Latn", "ru": "rus_Cyrl",
    "id": "ind_Latn", "ms": "zsm_Latn", "vi": "vie_Latn", "tl": "tgl_Latn", "hi": "hin_Deva", "ar": "arb_Arab",
    "tr": "tur_Latn", "nl": "nld_Latn", "pl": "pol_Latn", "sv": "swe_Latn",
}
DEFAULT_SRC = "eng_Latn"
SHORT_WORDS = 2
BATCH = 16


def nllb_code(lang: str | None) -> str:
    return NLLB_CODES.get((lang or "").lower().split("-")[0], DEFAULT_SRC)


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.casefold())


def plan(lines: list[str]) -> tuple[list[str], dict[int, int], dict[str, str]]:
    """แผนการแปล: (ข้อความที่ต้องแปลไม่ซ้ำกัน, บรรทัดที่ i -> ลำดับในรายการนั้น, ข้อความที่ต้องใส่บริบทก่อนหน้า)

    คืน unique_texts เรียงตามที่เจอครั้งแรก · index_of[i] = ตำแหน่งของบรรทัด i ใน unique_texts (บรรทัดว่างไม่มี key)
    context_for[text] = ข้อความบรรทัดก่อนหน้า (เฉพาะบรรทัดสั้น)
    """
    unique: list[str] = []
    seen: dict[str, int] = {}
    index_of: dict[int, int] = {}
    context_for: dict[str, str] = {}
    prev = ""
    for i, raw in enumerate(lines):
        text = " ".join(raw.split())
        if not _norm(text):
            prev = ""
            continue
        key = _norm(text)
        if key not in seen:
            seen[key] = len(unique)
            unique.append(text)
            if len(text.split()) <= SHORT_WORDS and prev:
                context_for[text] = prev
        index_of[i] = seen[key]
        prev = text
    return unique, index_of, context_for


def load(worker: Any) -> tuple[Any, Any]:
    """โหลด NLLB แบบ CTranslate2 int8 (เล็ก/เร็วกว่ารุ่น torch มาก ไม่ต้องใช้ transformers) + sentencepiece tokenizer
    ครั้งแรกต้องออกเน็ตโหลดโมเดลราว 1.4 GB ไป model_dir/nllb (ใช้ huggingface_hub ที่มากับ faster-whisper)"""
    import ctranslate2
    import sentencepiece as spm
    from huggingface_hub import snapshot_download

    tcfg = worker.mcfg.get("translate", {})
    md = worker.mcfg.get("model_dir") or ""
    path = snapshot_download(str(tcfg.get("model", "JustFrederik/nllb-200-distilled-1.3B-ct2-int8")),
                             cache_dir=str(Path(md) / "nllb") if md else None)
    translator = ctranslate2.Translator(path, device=worker.device, compute_type="int8_float16" if worker.device == "cuda" else "int8")
    sp = spm.SentencePieceProcessor()
    sp.load(str(Path(path) / "sentencepiece.bpe.model"))
    return translator, sp


def translate_texts(worker: Any, model: Any, tok: Any, texts: list[str], src: str, tgt: str, beam: int) -> list[str]:
    """สูตรของ CTranslate2 สำหรับ NLLB: โทเค็นต้นทาง = [รหัสภาษาต้นทาง] + sentencepiece + </s> · บังคับขึ้นต้นผลลัพธ์ด้วยรหัสภาษาปลายทาง"""
    out: list[str] = [""] * len(texts)
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    for b in range(0, len(order), BATCH):
        idx = order[b:b + BATCH]
        batch = [[src] + tok.encode(texts[i], out_type=str)[:120] + ["</s>"] for i in idx]
        res = model.translate_batch(batch, target_prefix=[[tgt]] * len(batch), beam_size=beam, max_decoding_length=160,
                                    repetition_penalty=1.1, no_repeat_ngram_size=3)
        for i, r in zip(idx, res):
            toks = r.hypotheses[0]
            if toks and toks[0] == tgt:
                toks = toks[1:]
            out[i] = tok.decode(toks).strip()
    return out


def run(worker: Any, p: dict[str, Any]) -> None:
    lines = [str(x) for x in p.get("lines", [])]
    src = nllb_code(p.get("source_lang"))
    tgt = str(p.get("target_lang") or worker.mcfg.get("translate", {}).get("target_lang", "tha_Thai"))
    beam = int(worker.mcfg.get("translate", {}).get("beam_size", 4))
    unique, index_of, context_for = plan(lines)
    if worker._nllb is None:
        worker._nllb = load(worker)   # (Translator, SentencePieceProcessor)
    model, tok = worker._nllb
    worker._check_cancel(p)
    # (ลองใส่บรรทัดก่อนหน้าเป็นบริบทให้บรรทัดสั้นแล้ว: NLLB ปนคำแปลบริบทเข้ามาในผล ตัดออกไม่ได้เสถียร จึงแปลทีละบรรทัดไม่ซ้ำกัน)
    result = translate_texts(worker, model, tok, unique, src, tgt, beam)
    translations = [result[index_of[i]] if i in index_of else "" for i in range(len(lines))]
    worker.emit("result", {"job_id": p["job_id"], "kind": "translate_final", "data": {
        "video_id": p.get("video_id"), "translations": translations, "target": tgt, "model": worker.mcfg.get("translate", {}).get("model")}})
    if not worker.mcfg.get("translate", {}).get("keep_loaded", False):
        worker._nllb = None   # คืน VRAM (Translator ถูกปล่อยเมื่อไม่มีผู้อ้างอิง)
