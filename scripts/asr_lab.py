"""ห้องทดลอง ASR: เทียบวิธีให้ AI "ฟังเสียงร้อง" หลายแบบ โดยวัดว่าข้อความที่ได้ยินตรงกับเนื้อเพลงจากเว็บแค่ไหน

ใช้เสียงร้องที่ Demucs แยกไว้แล้ว (cache/stems/<id>/vocals16k.npy) จึงทดลองได้เร็ว ไม่ต้องแยกเสียงซ้ำ
ตัวชี้วัด (ยิ่งสูงยิ่งดี): free = สัดส่วนข้อความที่ได้ยินซึ่งตรงกับเนื้อเพลง (ไม่สนลำดับ) · mono = ตรงตามลำดับ · loops = สัดส่วนคำที่เป็นการวนซ้ำมั่ว (ยิ่งต่ำยิ่งดี)
ใช้:  .venv\\Scripts\\python scripts\\asr_lab.py <videoId>[,<videoId>...] [--models turbo,large-v3] [--variants a,b,c]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


CACHE = ROOT / "ai_runtime" / "lab"


def lyrics_input_for(video_id: str):
    """บรรทัดเนื้อเพลง (รูปแบบส่งเข้า worker) จาก cache ไฟล์ — ดึงจากเว็บครั้งเดียวต่อคลิป (กันค้างที่เครือข่าย)"""
    import json

    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{video_id}.lyrics.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    from app.ai.aligner import lyrics_to_input

    lyr = lyrics_for(video_id)
    data = {"language": lyr.language if lyr else None, "lines": lyrics_to_input(lyr) if lyr else []}
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def lyrics_for(video_id: str):
    from app.audio.decoder import find_ffmpeg
    from app.core.config import Settings, load_model
    from app.core.paths import get_paths
    from app.lyrics.service import LyricsService
    from app.media.youtube import YouTubeClient

    paths = get_paths()
    settings, _ = load_model(paths, "settings.yaml", Settings)
    ff = find_ffmpeg()
    media = YouTubeClient(paths.cookies_file, ffmpeg_dir=ff.parent if ff else None)
    svc = LyricsService(paths.db_file, settings.lyrics_sources)

    async def go():
        info = await asyncio.to_thread(media.fetch_info, video_id)
        return await svc.find(info.track, info.duration, {"subtitles": info.subtitles}, lambda r: None)

    res = asyncio.run(go())
    return res.chosen


VARIANTS = {
    # ชื่อ: พารามิเตอร์ของ model.transcribe
    "base": dict(vad_filter=True, condition_on_previous_text=False, beam_size=5),
    "novad": dict(vad_filter=False, condition_on_previous_text=False, beam_size=5),
    "cond": dict(vad_filter=True, condition_on_previous_text=True, beam_size=5),
    "beam10": dict(vad_filter=True, condition_on_previous_text=False, beam_size=10, best_of=5),
    "temp": dict(vad_filter=True, condition_on_previous_text=False, beam_size=5, temperature=[0.0, 0.2, 0.4, 0.6]),
    "prompt": dict(vad_filter=True, condition_on_previous_text=False, beam_size=5, _prompt=True),
    "prompt_cond": dict(vad_filter=True, condition_on_previous_text=True, beam_size=5, _prompt=True),
    "strict": dict(vad_filter=True, condition_on_previous_text=False, beam_size=5, compression_ratio_threshold=1.8,
                   log_prob_threshold=-0.8, no_speech_threshold=0.5, repetition_penalty=1.15, no_repeat_ngram_size=4),
}


def run_variant(model, audio, language, kw, lyric_text: str):
    from app.ai.pipeline.match import TWord

    kw = dict(kw)
    use_prompt = kw.pop("_prompt", False)
    prompt = lyric_text[:600] if use_prompt else None
    segs, info = model.transcribe(audio, language=language, word_timestamps=True, initial_prompt=prompt, **kw)
    words = []
    for s in segs:
        for w in s.words or []:
            t = w.word.strip()
            if t:
                words.append(TWord(t, float(w.start), float(w.end), float(w.probability)))
    return words


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids")
    ap.add_argument("--models", default="turbo")
    ap.add_argument("--variants", default="base,prompt")
    args = ap.parse_args()

    import numpy as np

    from app.ai.env import setup_ai_environment
    from app.ai.pipeline.match import InLine, clean_transcript, match_lines, reconstruct_by_transcript, NOSPACE_LANGS
    from app.core.config import ModelsConfig, load_model
    from app.core.paths import get_paths

    paths = get_paths()
    models_cfg, _ = load_model(paths, "models.yaml", ModelsConfig)
    setup_ai_environment(models_cfg.model_dump())
    import torch  # noqa: F401  (ต้อง import ก่อน: torch ใส่ path ของ DLL CUDA ที่ ctranslate2 ใช้)
    from faster_whisper import WhisperModel

    names = {"turbo": "large-v3-turbo"}
    for mname in args.models.split(","):
        model = WhisperModel(names.get(mname, mname), device="cuda", compute_type="float16",
                             download_root=str(Path(models_cfg.model_dir) / "whisper"))
        for vid in args.ids.split(","):
            data = lyrics_input_for(vid)
            inp = data["lines"]
            if not inp:
                print(vid, "no lyrics")
                continue
            audio = np.load(paths.stems_cache_dir / vid / "vocals16k.npy").astype("float32")
            lines = [InLine(words=l["words"], start=l["start"], end=l["end"]) for l in inp]
            text = " ".join("".join(l["words"]) for l in inp)
            lang = data["language"]
            for vname in args.variants.split(","):
                t0 = time.time()
                try:
                    words = run_variant(model, audio, lang, VARIANTS[vname], text)
                except Exception as e:  # noqa: BLE001
                    print(f"{mname:12s} {vid:12s} {vname:12s} ERROR {e}")
                    continue
                dt = time.time() - t0
                clean = clean_transcript(words)
                loops = 1 - len(clean) / max(1, len(words))
                rr = reconstruct_by_transcript(lines, clean, nospace=lang in NOSPACE_LANGS)
                mono = match_lines(lines, clean)
                print(f"{mname:12s} {vid:12s} {vname:12s} words={len(words):4d} loops={loops:4.0%} free={rr.coverage:4.0%} mono={mono.coverage:4.0%} time={dt:4.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
