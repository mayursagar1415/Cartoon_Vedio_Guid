#!/usr/bin/env python3
"""Flat Puppet Studio — 2D Kahani Character Animator entrypoint.

Backwards-compatible CLI wrapper around the modular `flat_puppet` package.
Supports:
    python flat_puppet_demo.py test          # Fast 3-frame diagnostic check
    python flat_puppet_demo.py bake          # Pre-bake RGBA assets into assets_baked/
    python flat_puppet_demo.py render        # Multi-core parallel frame render to frames/
    python flat_puppet_demo.py encode        # Direct parallel render + FFmpeg pipe to MP4
"""

from pathlib import Path

from flat_puppet.cli import main

if __name__ == "__main__":
    raise SystemExit(main(root=Path(__file__).resolve().parent))
