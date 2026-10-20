"""โมเดลภาษาเล็กในเครื่อง (Qwen3-4B-Instruct-2507 แบบ CTranslate2 int8) — ให้ AI "คิด/วิเคราะห์" เนื้อเพลง
ผู้ใช้สั่ง 2026-10-21: แบ่งท่อน/เลือกคำเน้น/แยกเสียงประสาน ด้วยโมเดลที่อ่านความหมายได้ ไม่ใช่แค่ฟังเสียง

ใช้ ctranslate2.Generator (มีอยู่แล้วในชุด AI ใช้กับ NLLB) + tokenizers (ของ huggingface_hub) — ไม่ต้องติดตั้ง transformers
รันใน AI worker เท่านั้น: โหลดตอนจะใช้ แล้วปล่อยคืน VRAM (4B int8 ≈ 4.3 GB: ไม่พอจะค้างพร้อม Whisper/Demucs บน 8 GB)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

IM_START, IM_END = "<|im_start|>", "<|im_end|>"


class LyricsLLM:
    def __init__(self, model_dir: str | Path, device: str = "cuda", compute_type: str = "int8_float16") -> None:
        import ctranslate2
        from tokenizers import Tokenizer

        model_dir = Path(model_dir)
        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.gen = ctranslate2.Generator(str(model_dir), device=device, compute_type=compute_type if device == "cuda" else "int8")

    def chat(self, system: str, user: str, max_new_tokens: int = 700, no_think: bool = True) -> str:
        """ถามหนึ่งรอบ (greedy = คำตอบเดิมทุกครั้ง) คืนข้อความตอบ · no_think: ข้ามช่วง "คิดยาว" ของ Qwen3 รุ่นที่มี <think> (ไม่งั้นกินโทเคนหลายร้อยตัว)"""
        prompt = f"{IM_START}system\n{system}{IM_END}\n{IM_START}user\n{user}{IM_END}\n{IM_START}assistant\n"
        if no_think:
            prompt += "<think>\n\n</think>\n\n"
        ids = self.tok.encode(prompt, add_special_tokens=False).tokens
        res = self.gen.generate_batch([ids], max_length=max_new_tokens, sampling_topk=1, include_prompt_in_result=False,
                                      end_token=IM_END, repetition_penalty=1.05)
        out_ids = res[0].sequences_ids[0]
        return self.tok.decode(out_ids, skip_special_tokens=True).strip()

    def close(self) -> None:
        self.gen = None


# ---------------------------------------------------------------------------
# วิเคราะห์เนื้อเพลง
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are a music lyrics editor. You receive numbered lyric lines of one song. "
    "Reply with ONE JSON object only, no prose, with these keys:\n"
    '"sections": list of {"label": "intro|verse|prechorus|chorus|bridge|outro", "from": first line number, "to": last line number} '
    "covering the lines in order without gaps (group lines that belong together like a stanza; repeated lines are usually the chorus),\n"
    '"backing": line numbers that are backing vocals, echoes, ad-libs or choir answering the lead (usually short, repeated, or in parentheses),\n'
    '"emphasis": list of {"line": number, "word": the single most impactful word of that line} — only for lines with a clear emotional peak '
    "(at most one per 3 lines, prefer the hook, the title word, strong emotion words),\n"
    '"junk": line numbers that are NOT lyrics (credits, tags like [Chorus], writer names, instructions).\n'
    "Use only line numbers that exist. Keep arrays short. If unsure, leave a list empty."
)


def build_user_prompt(lines: list[str], title: str = "", artist: str = "", language: str = "") -> str:
    head = f"Song: {title or '?'} — {artist or '?'}\nLanguage: {language or '?'}\n\n"
    body = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(lines))
    return head + body


_JSON_RE = re.compile(r"\{.*\}", re.S)


def parse_analysis(text: str, n_lines: int) -> dict[str, Any] | None:
    """ตอบของโมเดล -> dict ที่ตรวจแล้ว (เลขบรรทัดเริ่ม 0, อยู่ในช่วง, เรียงต่อเนื่อง) · อ่านไม่ได้/ไม่ถูกรูปแบบ = None (ไม่ใช้ผล)"""
    m = _JSON_RE.search(text or "")
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None

    def ints(v: Any) -> list[int]:
        out = []
        for x in v if isinstance(v, list) else []:
            try:
                k = int(x) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= k < n_lines and k not in out:
                out.append(k)
        return sorted(out)

    sections: list[dict[str, Any]] = []
    cur = 0
    for sec in raw.get("sections", []) if isinstance(raw.get("sections"), list) else []:
        try:
            a, b = int(sec["from"]) - 1, int(sec["to"]) - 1
        except (KeyError, TypeError, ValueError):
            continue
        a, b = max(a, cur), min(b, n_lines - 1)
        if b < a:
            continue
        if a > cur:     # ช่องว่างระหว่างท่อน: ให้เป็นท่อนของตัวเอง (ไม่มีป้าย)
            sections.append({"label": "", "from": cur, "to": a - 1})
        sections.append({"label": str(sec.get("label", ""))[:12], "from": a, "to": b})
        cur = b + 1
    if cur < n_lines and sections:
        sections.append({"label": "", "from": cur, "to": n_lines - 1})
    emph: list[dict[str, Any]] = []
    for e in raw.get("emphasis", []) if isinstance(raw.get("emphasis"), list) else []:
        try:
            k = int(e["line"]) - 1
            w = str(e["word"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= k < n_lines and w and len(w) <= 40:
            emph.append({"line": k, "word": w})
    return {"sections": sections, "backing": ints(raw.get("backing")), "emphasis": emph[: max(1, n_lines // 3)], "junk": ints(raw.get("junk"))}


# ---------------------------------------------------------------------------
# รุ่นกะทัดรัด (เร็วกว่า: ตอบไม่กี่สิบโทเคน) — ท่อนใช้ app/lyrics/sections.py แล้ว LLM ทำเฉพาะเรื่องความหมาย
# ---------------------------------------------------------------------------
COMPACT_SYSTEM = (
    "You edit song lyrics. The user gives numbered lines. Answer in exactly this format, nothing else:\n"
    "BACK: comma-separated line numbers that are backing vocals/echo/ad-libs answering the lead (short, parenthesised, or a repeated echo of the previous line); NONE if none\n"
    "EMPH: semicolon-separated entries 'line=word' choosing the single most impactful word of the emotional peak lines (the hook, title word, "
    "strongest emotion); at most one entry per 4 lines; NONE if unsure\n"
    "JUNK: line numbers that are not lyrics (credits, [Chorus] tags); NONE if none\n"
    "Never copy numbers from these instructions; use only the real line numbers you were given."
)


def parse_compact(text: str, lines: list[str]) -> dict[str, Any] | None:
    """ตอบรูปแบบ BACK/EMPH/JUNK -> {"backing": [idx], "emphasis": [{"line","word"}], "junk": [idx]} (เลขเริ่ม 0) · ไม่มีสักหัวข้อ = None
    คำเน้นต้องเป็นคำที่อยู่ในบรรทัดนั้นจริง (กันโมเดลแต่งคำเอง)"""
    n = len(lines)
    found = False
    out: dict[str, Any] = {"backing": [], "emphasis": [], "junk": []}

    def nums(s: str) -> list[int]:
        res = []
        for m in re.finditer(r"\d+", s):
            k = int(m.group(0)) - 1
            if 0 <= k < n and k not in res:
                res.append(k)
        return res

    for raw in (text or "").splitlines():
        head, _, rest = raw.partition(":")
        h = head.strip().upper()
        if h == "BACK":
            found = True
            out["backing"] = nums(rest)
        elif h == "JUNK":
            found = True
            out["junk"] = nums(rest)
        elif h == "EMPH":
            found = True
            for ent in rest.split(";"):
                m = re.match(r"\s*(\d+)\s*=\s*(.+?)\s*$", ent)
                if not m:
                    continue
                k = int(m.group(1)) - 1
                w = m.group(2).strip().strip("\"'")
                if 0 <= k < n and w and w.casefold() in re.sub(r"[^\w\s']", " ", lines[k].casefold()).split():
                    out["emphasis"].append({"line": k, "word": w})
    return out if found else None
