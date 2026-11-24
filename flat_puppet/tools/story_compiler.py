"""High-level Story Script Compiler -> Auto-timed Scenes -> Incremental Multi-Shot 30-Min Renderer."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
from typing import Dict, List, Optional, Tuple

from flat_puppet.core.kinematics import procedural_blinks
from flat_puppet.core.puppet import bake_all_puppets
from flat_puppet.render.engine import encode_video
from flat_puppet.tools.voice_and_subs import (
    mix_audio_events,
    synthesize_tts_line,
    write_ass_file,
    write_parrot_chirp_wav,
)
from flat_puppet.utils.ffmpeg import find_ffmpeg


def _rel_or_abs(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def stride_matched_walk_cps(
    walk_x_start: float,
    walk_x_end: float,
    walk_duration: float,
    stride_px: float = 142.0,
) -> float:
    """Compute walk_cycles_per_sec so Option 4 foot travel matches x speed with zero foot slide."""
    if walk_duration <= 0.05:
        return 0.8
    dist = abs(walk_x_end - walk_x_start)
    cps = dist / max(stride_px * walk_duration, 1e-3)
    return round(max(0.55, min(1.05, cps)), 3)


def _auto_gesture_windows(start_t: float, dur: float, max_win: float = 1.25) -> List[List[float]]:
    """Split a speaking turn smoothly into 1 or 2 IK hand-gesture arcs."""
    if dur <= 0.6:
        return []
    if dur <= 1.7:
        return [[round(start_t + 0.08, 3), round(start_t + dur - 0.05, 3)]]
    mid = start_t + dur * 0.52
    return [
        [round(start_t + 0.08, 3), round(mid - 0.06, 3)],
        [round(mid + 0.06, 3), round(min(start_t + dur - 0.05, mid + max_win), 3)],
    ]


def compile_story_to_scenes(
    root: Path,
    story_path: Path,
    work_dir: Optional[Path] = None,
) -> Tuple[dict, List[Path]]:
    """Compile a concise Story Script JSON into self-contained scene JSONs, audio mixes, and subtitles."""
    story = json.loads(story_path.read_text(encoding="utf-8"))
    story_name = story["name"]
    fps = int(story.get("fps", 25))
    width = int(story.get("width", 1280))
    height = int(story.get("height", 720))
    ground_y = int(story.get("ground_y", 688))
    bgm_rel = story.get("bgm", "bgm-soft.wav")
    bgm_vol = float(story.get("bgm_volume", 0.16))

    out_root = work_dir or (root / ".cache" / "compiled_story" / story_name)
    out_root.mkdir(parents=True, exist_ok=True)
    tts_cache = out_root / "tts_cache"
    scenes_dir = out_root / "scenes"
    audio_dir = out_root / "audio"
    subs_dir = out_root / "subs"

    cast = story["cast"]
    hero_cast = cast["hero"]
    partner_cast = cast["partner"]
    comp_cast = cast["companion"]

    chirp_wav = audio_dir / "_chirp.wav"
    if not chirp_wav.is_file():
        write_parrot_chirp_wav(chirp_wav)

    style_colors: Dict[str, str] = {}
    for role_key, role_cfg in (("Hero", hero_cast), ("Partner", partner_cast)):
        style_colors[role_cfg.get("display_name", role_key)] = role_cfg.get("ass_color", "&H00FFFFFF")

    compiled_scenes: List[Path] = []
    for s_idx, shot in enumerate(story["shots"]):
        bg_rel = shot.get("background", story.get("default_background"))
        walk_enabled = bool(shot.get("walk_in", False))
        walk_dur = float(shot.get("walk_duration", 3.35 if walk_enabled else 0.0))
        walk_x_start = float(shot.get("walk_x_start", -55))
        walk_x_end = float(shot.get("walk_x_end", 315))
        talk_x = float(shot.get("talk_x", 335))

        t_cursor = walk_dur + (0.20 if walk_enabled else 0.30)
        mix_events: List[Tuple[Path, float, float]] = []
        ass_entries: List[Tuple[float, float, str, str]] = []
        hero_voice_events: List[Tuple[Path, float, float]] = []
        partner_voice_events: List[Tuple[Path, float, float]] = []
        hero_gestures: List[List[float]] = []

        for l_idx, line in enumerate(shot.get("lines", [])):
            sp_role = line["speaker"]  # "hero" or "partner"
            sp_cfg = hero_cast if sp_role == "hero" else partner_cast
            line_wav = audio_dir / f"s{s_idx:03d}_l{l_idx:02d}_{sp_role}.wav"
            dur = synthesize_tts_line(
                line["text"],
                line_wav,
                voice=sp_cfg.get("tts_voice", "hi-IN-MadhurNeural"),
                rate=line.get("rate", sp_cfg.get("tts_rate", "+10%")),
                pitch=line.get("pitch", sp_cfg.get("tts_pitch", "+0Hz")),
                cache_dir=tts_cache,
            )
            start_t = round(t_cursor, 3)
            end_t = round(start_t + dur + 0.06, 3)
            mix_events.append((line_wav, start_t, 1.0))

            if sp_role == "hero":
                hero_voice_events.append((line_wav, start_t, 1.0))
                if line.get("gesture", True):
                    hero_gestures.extend(_auto_gesture_windows(start_t, dur))
            else:
                partner_voice_events.append((line_wav, start_t, 1.0))

            speaker_prefix = f"{sp_cfg.get('display_name', '')}: " if sp_cfg.get("display_name") else ""
            style_name = sp_cfg.get("display_name", "Default")
            ass_entries.append((start_t, end_t, style_name, f"{speaker_prefix}{line['text']}"))
            t_cursor += dur + float(line.get("pause_after", 0.25))

        hop_windows: List[List[float]] = []
        for sfx_idx, sfx in enumerate(shot.get("sfx", [])):
            offset = float(sfx.get("offset", 0.0))
            sfx_t = max(0.0, t_cursor + offset) if offset < 0 else t_cursor + offset - 0.15
            if sfx.get("type") == "chirp":
                mix_events.append((chirp_wav, round(sfx_t, 3), float(sfx.get("volume", 0.85))))
                if sfx.get("hop", True):
                    hop_windows.append([round(sfx_t - 0.05, 3), round(sfx_t + 0.42, 3)])
                t_cursor = max(t_cursor, sfx_t + 0.45)

        total_dur = round(max(float(shot.get("min_duration", 2.0)), t_cursor + float(shot.get("pad_end", 0.25))), 2)

        shot_mix_wav = audio_dir / f"s{s_idx:03d}_mix.wav"
        mix_audio_events(mix_events, shot_mix_wav, total_dur)

        # Build per-speaker timeline WAVs so multi-line turns inside one shot lip-sync independently
        hero_lip_wav = audio_dir / f"s{s_idx:03d}_hero_lip.wav"
        mix_audio_events(hero_voice_events, hero_lip_wav, total_dur)
        partner_lip_wav = audio_dir / f"s{s_idx:03d}_partner_lip.wav"
        mix_audio_events(partner_voice_events, partner_lip_wav, total_dur)

        ass_path = subs_dir / f"s{s_idx:03d}.ass"
        write_ass_file(ass_entries, ass_path, style_colors=style_colors, width=width, height=height)

        cam_cfg = shot.get("camera", {})
        walk_cps = shot.get(
            "walk_cycles_per_sec",
            stride_matched_walk_cps(walk_x_start, walk_x_end, walk_dur) if walk_enabled else 0.8,
        )

        scene_cfg = {
            "name": f"{story_name}_s{s_idx:03d}",
            "fps": fps,
            "width": width,
            "height": height,
            "duration": total_dur,
            "ground_y": ground_y,
            "background": bg_rel,
            "audio": {
                "voice": _rel_or_abs(shot_mix_wav, root),
                "voice_start": 0.0,
                "subtitles_base_start": 0.0,
                "gain_ref": "auto",
                "bgm": bgm_rel,
                "bgm_volume": bgm_vol,
                "subtitles": _rel_or_abs(ass_path, root),
            },
            "camera": {
                "enabled": cam_cfg.get("enabled", True),
                "zoom_start": float(cam_cfg.get("zoom_start", 1.0)),
                "zoom_end": float(cam_cfg.get("zoom_end", 1.035)),
                "zoom_t_start": float(cam_cfg.get("zoom_t_start", walk_dur)),
                "zoom_t_end": float(cam_cfg.get("zoom_t_end", max(walk_dur + 0.5, total_dur - 0.15))),
                "focus_x": float(cam_cfg.get("focus_x", 0.54)),
                "focus_y": float(cam_cfg.get("focus_y", 0.54)),
            },
            "characters": {
                "tara": {
                    "puppet": partner_cast["puppet"],
                    "height": int(shot.get("partner_height", partner_cast.get("height", 355))),
                    "x": int(shot.get("partner_x", partner_cast.get("x", 885))),
                    "voice": _rel_or_abs(partner_lip_wav, root),
                    "voice_start": 0.0,
                    "blinks": procedural_blinks(total_dur, seed=101 + s_idx),
                },
                "gulli": {
                    "puppet": comp_cast["puppet"],
                    "height": int(shot.get("companion_height", comp_cast.get("height", 162))),
                    "x": int(shot.get("companion_x", comp_cast.get("x", 675))),
                    "hop_windows": hop_windows,
                },
                "gopal": {
                    "puppet": hero_cast["puppet"],
                    "leg_mode": shot.get("leg_mode", hero_cast.get("leg_mode", "sprite8")),
                    "skin_rgb": hero_cast.get("skin_rgb", [228, 170, 124]),
                    "side_height": int(hero_cast.get("side_height", 475)),
                    "front_height": int(hero_cast.get("front_height", 485)),
                    "walk_duration": walk_dur if walk_enabled else 0.0,
                    "turn_half_window": 0.14 if walk_enabled else 0.0,
                    "walk_action": "walk_cycle",
                    "walk_cycles_per_sec": walk_cps,
                    "walk_x_start": walk_x_start,
                    "walk_x_end": walk_x_end,
                    "talk_x": talk_x,
                    "voice": _rel_or_abs(hero_lip_wav, root),
                    "voice_start": 0.0,
                    "gesture_action": "speak_gesture",
                    "gesture_windows": hero_gestures,
                    "blinks": procedural_blinks(total_dur, seed=202 + s_idx),
                },
            },
        }
        scene_path = scenes_dir / f"shot_{s_idx:03d}.json"
        scene_path.parent.mkdir(parents=True, exist_ok=True)
        scene_path.write_text(json.dumps(scene_cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        compiled_scenes.append(scene_path)

    return story, compiled_scenes


def render_story(
    root: Path,
    config_dir: Path,
    story_path: Path,
    output_mp4: Path,
    workers: Optional[int] = None,
    compile_only: bool = False,
) -> Path:
    """Compile a Story Script JSON, incrementally render changed shots, and lossless-concat to MP4."""
    t0 = time.perf_counter()
    story, scene_paths = compile_story_to_scenes(root, story_path)
    print(f"Compiled {len(scene_paths)} shot(s) for '{story['name']}' in {time.perf_counter() - t0:.2f}s")
    if compile_only:
        return output_mp4

    # Pre-bake all puppets ONCE before rendering dozens/hundreds of shots (30-min speedup!)
    bake_all_puppets(root, config_dir, force=False)

    out_root = root / ".cache" / "compiled_story" / story["name"]
    renders_dir = out_root / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)
    shot_mp4s: List[Path] = []

    for s_idx, scene_path in enumerate(scene_paths):
        scene_bytes = scene_path.read_bytes()
        shot_hash = hashlib.sha1(scene_bytes).hexdigest()[:12]
        shot_mp4 = renders_dir / f"shot_{s_idx:03d}_{shot_hash}.mp4"
        if not shot_mp4.is_file():
            # Remove stale older versions of this shot index
            for stale in renders_dir.glob(f"shot_{s_idx:03d}_*.mp4"):
                stale.unlink()
            encode_video(root, config_dir, scene_path, output_mp4=shot_mp4, workers=workers)
        else:
            print(f"Shot {s_idx} cached ({shot_mp4.name}), skipping re-render.")
        shot_mp4s.append(shot_mp4)

    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    if len(shot_mp4s) == 1:
        output_mp4.write_bytes(shot_mp4s[0].read_bytes())
    else:
        concat_txt = out_root / "concat_list.txt"
        concat_txt.write_text(
            "\n".join(f"file '{p.resolve().as_posix()}'" for p in shot_mp4s) + "\n",
            encoding="utf-8",
        )
        ff = find_ffmpeg()
        subprocess.run(
            [ff, "-y", "-v", "warning", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c", "copy", str(output_mp4)],
            check=True,
        )

    print(f"Story ready: {output_mp4} (total {time.perf_counter() - t0:.2f}s)")
    return output_mp4
