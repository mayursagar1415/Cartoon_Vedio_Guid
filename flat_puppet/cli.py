"""Command-line interface for Flat Puppet Studio."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time
from typing import Optional, Sequence

from flat_puppet.core.puppet import bake_all_puppets
from flat_puppet.render.engine import encode_video, render_test_frames, render_to_frames


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flat_puppet_demo.py",
        description="Flat Puppet Studio — 2D Kahani Character Animator",
    )
    sub = parser.add_subparsers(dest="command")

    # 'test' command (backwards-compatible)
    p_test = sub.add_parser("test", help="Render 3 diagnostic test pose frames")
    p_test.add_argument("--scene", default="configs/scenes/demo_courtyard.json", help="Scene JSON path")

    # 'bake' command
    p_bake = sub.add_parser("bake", help="Pre-bake transparent character cutouts into assets_baked/")
    p_bake.add_argument("--force", action="store_true", help="Force rebake even if cache is fresh")

    # 'render' command
    p_render = sub.add_parser("render", help="Render all frames to PNG files in parallel")
    p_render.add_argument("--scene", default="configs/scenes/demo_courtyard.json", help="Scene JSON path")
    p_render.add_argument("--out", default="frames", help="Output frames directory")
    p_render.add_argument("--workers", type=int, default=None, help="Parallel worker processes")

    # 'encode' command
    p_encode = sub.add_parser("encode", help="Render and stream straight into FFmpeg to produce MP4")
    p_encode.add_argument("--scene", default="configs/scenes/demo_courtyard.json", help="Scene JSON path")
    p_encode.add_argument("--output", "-o", default="FLAT-DEMO.mp4", help="Output MP4 file")
    p_encode.add_argument("--workers", type=int, default=None, help="Parallel worker processes")
    p_encode.add_argument("--save-frames", action="store_true", help="Also write PNG frames to frames/")
    p_encode.add_argument("--no-audio", action="store_true", help="Skip voice and BGM tracks")
    p_encode.add_argument("--no-subs", action="store_true", help="Skip subtitle burn-in")

    return parser


def main(argv: Optional[Sequence[str]] = None, root: Optional[Path] = None) -> int:
    base_dir = root or Path(__file__).resolve().parent.parent
    config_dir = base_dir / "configs"

    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    # Default to 'render' when run with no subcommand for 100% backwards compatibility
    if not args_list:
        args_list = ["render"]
    args = parser.parse_args(args_list)

    if args.command == "bake":
        t0 = time.perf_counter()
        bake_all_puppets(base_dir, config_dir, force=args.force)
        print(f"Assets baked into {base_dir / 'assets_baked'} in {time.perf_counter() - t0:.2f}s")
        return 0

    scene_path = Path(args.scene)
    if not scene_path.is_absolute():
        scene_path = base_dir / scene_path

    if args.command == "test":
        render_test_frames(base_dir, config_dir, scene_path)
        return 0

    if args.command == "render":
        out_dir = Path(args.out)
        if not out_dir.is_absolute():
            out_dir = base_dir / out_dir
        render_to_frames(base_dir, config_dir, scene_path, out_dir=out_dir, workers=args.workers)
        return 0

    if args.command == "encode":
        out_mp4 = Path(args.output)
        if not out_mp4.is_absolute():
            out_mp4 = base_dir / out_mp4
        encode_video(
            base_dir,
            config_dir,
            scene_path,
            output_mp4=out_mp4,
            workers=args.workers,
            save_frames=args.save_frames,
            no_audio=args.no_audio,
            no_subs=args.no_subs,
        )
        return 0

    parser.print_help()
    return 1
