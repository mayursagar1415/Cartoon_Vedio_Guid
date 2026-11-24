"""Multi-core parallel frame renderer and zero-disk-I/O FFmpeg pipe encoder."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import os
from pathlib import Path
import subprocess
import time
from typing import Optional, Sequence, Tuple

from flat_puppet.core.compositor import SceneCompositor, load_scene_config
from flat_puppet.core.puppet import bake_all_puppets
from flat_puppet.utils.ffmpeg import build_encode_command

_WORKER_COMPOSITOR: Optional[SceneCompositor] = None


def _init_worker(root_str: str, config_str: str, scene_str: str, leg_mode: Optional[str]) -> None:
    global _WORKER_COMPOSITOR
    _WORKER_COMPOSITOR = SceneCompositor(
        Path(root_str), Path(config_str), Path(scene_str), leg_mode_override=leg_mode
    )


def _worker_save_frame(args: Tuple[int, str]) -> int:
    idx, out_dir = args
    assert _WORKER_COMPOSITOR is not None
    frame = _WORKER_COMPOSITOR.render_frame(idx)
    frame.save(Path(out_dir) / f"f{idx:04d}.png", format="PNG")
    return idx


def _worker_render_bytes(idx: int) -> bytes:
    assert _WORKER_COMPOSITOR is not None
    frame = _WORKER_COMPOSITOR.render_frame(idx)
    return frame.convert("RGB").tobytes()


def render_test_frames(
    root: Path,
    config_dir: Path,
    scene_path: Path,
    samples: Sequence[Tuple[int, str]] = ((9, "test6-swingF"), (24, "test6-swingN"), (150, "test6-speak")),
    leg_mode: Optional[str] = None,
) -> list[Path]:
    t0 = time.perf_counter()
    bake_all_puppets(root, config_dir, force=False)
    comp = SceneCompositor(root, config_dir, scene_path, leg_mode_override=leg_mode)
    saved: list[Path] = []
    for idx, name in samples:
        out_path = root / f"{name}.png"
        comp.render_frame(idx).save(out_path, format="PNG")
        saved.append(out_path)
    elapsed = time.perf_counter() - t0
    print(f"test frames saved ({len(saved)}) in {elapsed:.2f}s")
    return saved


def render_to_frames(
    root: Path,
    config_dir: Path,
    scene_path: Path,
    out_dir: Optional[Path] = None,
    workers: Optional[int] = None,
    leg_mode: Optional[str] = None,
) -> Path:
    t0 = time.perf_counter()
    target_dir = out_dir or (root / "frames")
    target_dir.mkdir(parents=True, exist_ok=True)
    # Remove stale PNG frames from any prior render of different length (prevents ghost frames)
    for old_frame in target_dir.glob("f*.png"):
        old_frame.unlink()

    bake_all_puppets(root, config_dir, force=False)
    comp_main = SceneCompositor(root, config_dir, scene_path, leg_mode_override=leg_mode)
    nframes = comp_main.nframes
    max_workers = max(1, workers or min(os.cpu_count() or 4, 8))

    if max_workers == 1:
        for i in range(nframes):
            comp_main.render_frame(i).save(target_dir / f"f{i:04d}.png", format="PNG")
    else:
        tasks = [(i, str(target_dir)) for i in range(nframes)]
        chunksize = max(1, nframes // (max_workers * 4))
        with ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=_init_worker,
            initargs=(str(root), str(config_dir), str(scene_path), leg_mode),
        ) as executor:
            list(executor.map(_worker_save_frame, tasks, chunksize=chunksize))

    elapsed = time.perf_counter() - t0
    print(f"frames={nframes} rendered in {elapsed:.2f}s (workers={max_workers})")
    return target_dir


def encode_video(
    root: Path,
    config_dir: Path,
    scene_path: Path,
    output_mp4: Optional[Path] = None,
    workers: Optional[int] = None,
    save_frames: bool = False,
    no_audio: bool = False,
    no_subs: bool = False,
    leg_mode: Optional[str] = None,
    max_duration: Optional[float] = None,
) -> Path:
    t0 = time.perf_counter()
    scene_cfg = load_scene_config(scene_path, root=root)
    out_file = output_mp4 or (root / "FLAT-DEMO.mp4")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    bake_all_puppets(root, config_dir, force=False)
    comp_main = SceneCompositor(root, config_dir, scene_path, leg_mode_override=leg_mode)
    duration = min(comp_main.duration, max_duration) if max_duration else comp_main.duration
    nframes = int(round(duration * comp_main.fps))

    audio_cfg = scene_cfg.get("audio", {})
    voice_start = float(audio_cfg.get("voice_start", 0.0))
    sub_base_start = float(audio_cfg.get("subtitles_base_start", voice_start))
    ass_shift_sec = voice_start - sub_base_start

    voice_path = None if no_audio else ((root / audio_cfg["voice"]) if audio_cfg.get("voice") else None)
    bgm_path = None if no_audio else ((root / audio_cfg["bgm"]) if audio_cfg.get("bgm") else None)
    ass_path = None if no_subs else ((root / audio_cfg["subtitles"]) if audio_cfg.get("subtitles") else None)

    max_workers = max(1, workers or min(os.cpu_count() or 4, 8))

    if save_frames:
        frames_dir = render_to_frames(root, config_dir, scene_path, workers=max_workers, leg_mode=leg_mode)
        cmd = build_encode_command(
            width=comp_main.width,
            height=comp_main.height,
            fps=comp_main.fps,
            duration=duration,
            output_mp4=out_file,
            voice_path=voice_path,
            voice_delay_sec=voice_start,
            bgm_path=bgm_path,
            bgm_volume=float(audio_cfg.get("bgm_volume", 0.22)),
            ass_path=ass_path,
            ass_shift_sec=ass_shift_sec,
            frames_pattern=str(frames_dir / "f%04d.png"),
            use_pipe=False,
            work_dir=root / ".cache",
        )
        subprocess.run(cmd, check=True)
    else:
        cmd = build_encode_command(
            width=comp_main.width,
            height=comp_main.height,
            fps=comp_main.fps,
            duration=duration,
            output_mp4=out_file,
            voice_path=voice_path,
            voice_delay_sec=voice_start,
            bgm_path=bgm_path,
            bgm_volume=float(audio_cfg.get("bgm_volume", 0.22)),
            ass_path=ass_path,
            ass_shift_sec=ass_shift_sec,
            use_pipe=True,
            work_dir=root / ".cache",
        )
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        assert proc.stdin is not None
        try:
            if max_workers == 1:
                for i in range(nframes):
                    proc.stdin.write(comp_main.render_frame(i).convert("RGB").tobytes())
            else:
                chunksize = max(1, nframes // (max_workers * 6))
                with ProcessPoolExecutor(
                    max_workers=max_workers,
                    initializer=_init_worker,
                    initargs=(str(root), str(config_dir), str(scene_path), leg_mode),
                ) as executor:
                    for raw_bytes in executor.map(_worker_render_bytes, range(nframes), chunksize=chunksize):
                        proc.stdin.write(raw_bytes)
            proc.stdin.close()
            ret = proc.wait()
            if ret != 0:
                raise subprocess.CalledProcessError(ret, cmd)
        except Exception:
            proc.kill()
            proc.wait()
            raise

    elapsed = time.perf_counter() - t0
    print(f"Encoded {out_file.name} ({nframes} frames) in {elapsed:.2f}s (workers={max_workers})")
    return out_file
