"""Cross-platform FFmpeg discovery, audio conversion, subtitle handling, and encoding."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def find_ffmpeg() -> str:
    """Locate ffmpeg executable across PATH, env var, Antigravity cache, and common Windows locations."""
    env_bin = os.environ.get("FFMPEG_BINARY")
    if env_bin and Path(env_bin).is_file():
        return env_bin

    in_path = shutil.which("ffmpeg")
    if in_path:
        return in_path

    candidates = [
        Path(r"E:\antigravity-cache\binaries\ffmpeg.exe"),
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe")),
        Path("/usr/bin/ffmpeg"),
        Path("/usr/local/bin/ffmpeg"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    raise FileNotFoundError(
        "FFmpeg binary not found. Install FFmpeg on PATH, set FFMPEG_BINARY, "
        "or place ffmpeg.exe at E:\\antigravity-cache\\binaries\\ffmpeg.exe."
    )


def _has_windows_font(font_prefix: str) -> bool:
    if os.name != "nt":
        return True
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if not fonts_dir.is_dir():
        return False
    prefix_lower = font_prefix.lower().replace(" ", "")
    for item in fonts_dir.iterdir():
        if prefix_lower in item.name.lower().replace(" ", ""):
            return True
    return False


def _parse_ass_time(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600.0 + int(m) * 60.0 + float(s)


def _format_ass_time(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60.0
    return f"{h}:{m:02d}:{s:05.2f}"


def _shift_ass_timestamps(content: str, delta_sec: float) -> str:
    if abs(delta_sec) < 1e-3:
        return content
    out_lines: list[str] = []
    pat = re.compile(r"^(Dialogue:\s*\d+,)(\d+:\d{2}:\d{2}\.\d{2}),(\d+:\d{2}:\d{2}\.\d{2})(,.*)$")
    for line in content.splitlines():
        m = pat.match(line)
        if m:
            s_new = _format_ass_time(_parse_ass_time(m.group(2)) + delta_sec)
            e_new = _format_ass_time(_parse_ass_time(m.group(3)) + delta_sec)
            out_lines.append(f"{m.group(1)}{s_new},{e_new}{m.group(4)}")
        else:
            out_lines.append(line)
    return "\n".join(out_lines) + ("\n" if content.endswith("\n") else "")


def prepare_ass_subtitles(
    ass_path: Path,
    work_dir: Path,
    time_shift_sec: float = 0.0,
) -> Path:
    """Ensure ASS subtitle file uses an installed Devanagari font on Windows and syncs timestamps."""
    if not ass_path.is_file():
        raise FileNotFoundError(f"Subtitle file not found: {ass_path}")

    content = ass_path.read_text(encoding="utf-8")
    modified = False

    if abs(time_shift_sec) >= 1e-3:
        content = _shift_ass_timestamps(content, time_shift_sec)
        modified = True

    if os.name == "nt" and "Noto Sans Devanagari" in content and not _has_windows_font("NotoSansDevanagari"):
        fallback = "Nirmala UI" if _has_windows_font("Nirmala") else "Mangal"
        content = content.replace("Noto Sans Devanagari", fallback)
        modified = True

    if modified:
        work_dir.mkdir(parents=True, exist_ok=True)
        out_ass = work_dir / f"{ass_path.stem}.resolved.ass"
        out_ass.write_text(content, encoding="utf-8")
        return out_ass
    return ass_path


def _ffmpeg_filter_path(path: Path) -> str:
    """Escape path safely for FFmpeg libass filter_complex argument (especially Windows drive colons)."""
    posix = path.resolve().as_posix()
    # Escape drive colon e.g. C:/... -> C\:/...
    return re.sub(r"^([A-Za-z]):", r"\1\\:", posix)


def convert_to_wav(src_audio: Path, dst_wav: Path, sample_rate: int = 22050) -> Path:
    """Convert any audio file to mono 16-bit PCM WAV using FFmpeg if stale or missing."""
    if not src_audio.is_file():
        raise FileNotFoundError(f"Audio file not found: {src_audio}")

    if dst_wav.is_file() and dst_wav.stat().st_mtime >= src_audio.stat().st_mtime:
        return dst_wav

    dst_wav.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = find_ffmpeg()
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-i",
            str(src_audio),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            str(dst_wav),
        ],
        check=True,
    )
    return dst_wav


def build_encode_command(
    *,
    width: int,
    height: int,
    fps: int,
    duration: float,
    output_mp4: Path,
    voice_path: Optional[Path] = None,
    voice_delay_sec: float = 0.0,
    bgm_path: Optional[Path] = None,
    bgm_volume: float = 0.22,
    ass_path: Optional[Path] = None,
    ass_shift_sec: float = 0.0,
    frames_pattern: Optional[str] = None,
    use_pipe: bool = True,
    work_dir: Optional[Path] = None,
) -> list[str]:
    """Build the FFmpeg command for either stdin rawvideo pipe or PNG image sequence."""
    ffmpeg_bin = find_ffmpeg()
    cmd: list[str] = [ffmpeg_bin, "-y", "-v", "warning", "-stats"]

    if use_pipe:
        cmd.extend([
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{width}x{height}",
            "-pix_fmt", "rgb24",
            "-r", str(fps),
            "-i", "-",
        ])
    else:
        if not frames_pattern:
            raise ValueError("frames_pattern is required when use_pipe=False")
        cmd.extend(["-framerate", str(fps), "-i", frames_pattern])

    input_idx = 1
    voice_idx: Optional[int] = None
    bgm_idx: Optional[int] = None

    if voice_path and voice_path.is_file():
        cmd.extend(["-i", str(voice_path)])
        voice_idx = input_idx
        input_idx += 1

    if bgm_path and bgm_path.is_file():
        cmd.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
        bgm_idx = input_idx
        input_idx += 1

    filter_parts: list[str] = []
    video_map = "0:v"

    if ass_path and ass_path.is_file():
        resolved_ass = prepare_ass_subtitles(
            ass_path, work_dir or output_mp4.parent, time_shift_sec=ass_shift_sec
        )
        ass_escaped = _ffmpeg_filter_path(resolved_ass)
        filter_parts.append(f"[0:v]ass='{ass_escaped}'[v]")
        video_map = "[v]"

    audio_map: Optional[str] = None
    if voice_idx is not None and bgm_idx is not None:
        delay_ms = int(round(voice_delay_sec * 1000))
        filter_parts.append(f"[{voice_idx}:a]aresample=44100,adelay={delay_ms}|{delay_ms}[a1]")
        filter_parts.append(f"[{bgm_idx}:a]volume={bgm_volume},atrim=0:{duration}[a2]")
        filter_parts.append("[a1][a2]amix=inputs=2:normalize=0[a]")
        audio_map = "[a]"
    elif voice_idx is not None:
        delay_ms = int(round(voice_delay_sec * 1000))
        filter_parts.append(f"[{voice_idx}:a]aresample=44100,adelay={delay_ms}|{delay_ms}[a]")
        audio_map = "[a]"
    elif bgm_idx is not None:
        filter_parts.append(f"[{bgm_idx}:a]volume={bgm_volume},atrim=0:{duration}[a]")
        audio_map = "[a]"

    if filter_parts:
        cmd.extend(["-filter_complex", ";".join(filter_parts)])

    cmd.extend(["-map", video_map])
    if audio_map:
        cmd.extend(["-map", audio_map, "-c:a", "aac", "-ar", "44100", "-ac", "2"])

    cmd.extend([
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-t", f"{duration:.3f}",
        str(output_mp4),
    ])
    return cmd
