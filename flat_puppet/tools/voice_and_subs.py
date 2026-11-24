"""Automated Hindi Neural TTS synthesis, SFX generation, audio mixing, and ASS subtitle building."""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import wave
from typing import Dict, List, Optional, Tuple

from flat_puppet.utils.ffmpeg import _format_ass_time, find_ffmpeg


def _find_edge_tts_python() -> str:
    """Locate a Python interpreter that has `edge_tts` installed."""
    try:
        import edge_tts  # noqa: F401
        return sys.executable
    except ImportError:
        pass
    cache_venv = Path(r"E:\antigravity-cache\packages\venvs\automation\Scripts\python.exe")
    if cache_venv.is_file():
        return str(cache_venv)
    return sys.executable


def wav_duration(wav_path: Path) -> float:
    """Return exact duration in seconds from PCM WAV header."""
    with wave.open(str(wav_path), "rb") as wf:
        return wf.getnframes() / max(wf.getframerate(), 1)


def synthesize_tts_line(
    text: str,
    out_wav: Path,
    *,
    voice: str = "hi-IN-MadhurNeural",
    rate: str = "+10%",
    pitch: str = "+0Hz",
    cache_dir: Optional[Path] = None,
) -> float:
    """Generate trimmed mono 22050Hz WAV via `edge-tts` with hash caching, returning exact duration."""
    key_raw = f"{voice}|{rate}|{pitch}|{text}".encode("utf-8")
    line_hash = hashlib.sha1(key_raw).hexdigest()[:12]
    work = cache_dir or out_wav.parent / ".tts_cache"
    work.mkdir(parents=True, exist_ok=True)
    cached_wav = work / f"{line_hash}.wav"

    if not cached_wav.is_file():
        raw_mp3 = work / f"{line_hash}.raw.mp3"
        py_exe = _find_edge_tts_python()
        helper = (
            "import asyncio, sys, edge_tts\n"
            "async def main():\n"
            "    c = edge_tts.Communicate(sys.argv[1], sys.argv[2], rate=sys.argv[3], pitch=sys.argv[4])\n"
            "    await c.save(sys.argv[5])\n"
            "asyncio.run(main())\n"
        )
        subprocess.run(
            [py_exe, "-c", helper, text, voice, rate, pitch, str(raw_mp3)],
            check=True,
        )
        ff = find_ffmpeg()
        subprocess.run(
            [
                ff,
                "-y",
                "-v",
                "error",
                "-i",
                str(raw_mp3),
                "-af",
                "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                "silenceremove=start_periods=1:start_threshold=-45dB,areverse",
                "-ac",
                "1",
                "-ar",
                "22050",
                str(cached_wav),
            ],
            check=True,
        )
        if raw_mp3.is_file():
            raw_mp3.unlink()

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if cached_wav.resolve() != out_wav.resolve():
        out_wav.write_bytes(cached_wav.read_bytes())
    return wav_duration(out_wav)


def write_parrot_chirp_wav(out_wav: Path, sr: int = 22050) -> float:
    """Synthesize a clean two-note cartoon bird chirp WAV and return its duration."""
    notes = [(0.02, 0.11, 1450.0, 2250.0), (0.17, 0.27, 1600.0, 2480.0)]
    dur = 0.32
    n = int(sr * dur)
    samples: List[int] = []
    for i in range(n):
        t = i / sr
        val = 0.0
        for s0, s1, f0, f1 in notes:
            if s0 <= t <= s1:
                u = (t - s0) / (s1 - s0)
                env = math.sin(math.pi * u) ** 1.2
                f = f0 + (f1 - f0) * (u * u)
                val += 0.28 * env * (
                    0.75 * math.sin(2.0 * math.pi * f * t)
                    + 0.25 * math.sin(4.0 * math.pi * f * t)
                )
        samples.append(int(max(-1.0, min(1.0, val)) * 32767))
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return dur


def mix_audio_events(
    events: List[Tuple[Path, float, float]],
    out_wav: Path,
    total_duration: float,
) -> Path:
    """Delay and mix `(wav_path, start_sec, volume)` tracks into one aligned mono WAV."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    ff = find_ffmpeg()
    if not events:
        subprocess.run(
            [
                ff,
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=22050:cl=mono",
                "-t",
                f"{total_duration:.3f}",
                str(out_wav),
            ],
            check=True,
        )
        return out_wav

    cmd: List[str] = [ff, "-y", "-v", "error"]
    filter_parts: List[str] = []
    labels: List[str] = []
    for idx, (path, start_s, vol) in enumerate(events):
        cmd.extend(["-i", str(path)])
        delay_ms = max(0, int(round(start_s * 1000)))
        lbl = f"[a{idx}]"
        filter_parts.append(
            f"[{idx}:a]aresample=22050,volume={vol:.3f},adelay={delay_ms}|{delay_ms},apad=whole_dur={total_duration:.3f}{lbl}"
        )
        labels.append(lbl)

    mix_expr = "".join(labels) + f"amix=inputs={len(labels)}:normalize=0,alimiter=limit=0.95[out]"
    filter_parts.append(mix_expr)
    cmd.extend([
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[out]",
        "-ac",
        "1",
        "-ar",
        "22050",
        "-t",
        f"{total_duration:.3f}",
        str(out_wav),
    ])
    subprocess.run(cmd, check=True)
    return out_wav


def write_ass_file(
    entries: List[Tuple[float, float, str, str]],
    out_ass: Path,
    style_colors: Optional[Dict[str, str]] = None,
    width: int = 1280,
    height: int = 720,
) -> Path:
    """Write ASS subtitles from `(start_sec, end_sec, style_name, text)` entries."""
    colors = style_colors or {"Default": "&H00FFFFFF"}
    lines: List[str] = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    ]
    used_styles = set(colors.keys()) | {st for _, _, st, _ in entries}
    for st in sorted(used_styles):
        col = colors.get(st, "&H00FFFFFF")
        lines.append(
            f"Style: {st},Noto Sans Devanagari,34,{col},&H000000FF,&H00000000,&H78000000,"
            "-1,0,0,0,100,100,0,0,1,3,1,2,40,40,34,1"
        )
    lines.extend([
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])
    for start_s, end_s, style, txt in entries:
        lines.append(f"Dialogue: 0,{_format_ass_time(start_s)},{_format_ass_time(end_s)},{style},,0,0,0,,{txt}")

    out_ass.parent.mkdir(parents=True, exist_ok=True)
    out_ass.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_ass
