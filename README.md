# Flat Puppet Studio — 2D Kahani Character Animator

A modular Python animation engine for flat 2D cutout characters (*AutoDraft-style* kahani videos):
characters are assembled from clean, armless torso bases and separately articulated parts (head, arm, 2-bone thigh + calf legs), animated with procedural kinematics, smoothed audio lip-sync, subtle camera framing, and direct FFmpeg pipe encoding.

## Quick Start

Install the two Python packages (`Pillow` and `numpy`) and ensure `ffmpeg` is available (on `PATH`, `FFMPEG_BINARY`, or `E:\antigravity-cache\binaries\ffmpeg.exe`):

```bash
pip install -r requirements.txt
```

1. **Render 3 diagnostic test frames (fast check):**
   ```bash
   python flat_puppet_demo.py test
   ```
   Writes `test6-swingF.png`, `test6-swingN.png`, and `test6-speak.png`.

2. **Render & encode the full video in one step (parallel + direct FFmpeg pipe):**
   ```bash
   python flat_puppet_demo.py encode --output FLAT-DEMO.mp4
   ```
   Or via platform wrappers:
   - **Windows PowerShell:** `.\make_video.ps1`
   - **Linux / macOS / Git Bash:** `bash make_video.sh`

3. **Optional CLI Commands:**
   ```bash
   python flat_puppet_demo.py bake [--force]          # Pre-bake transparent cutouts into assets_baked/
   python flat_puppet_demo.py render [--workers 8]     # Save PNG frames to frames/ in parallel
   python flat_puppet_demo.py encode --save-frames     # Keep PNG frames while encoding MP4
   ```

## Architecture

- **`flat_puppet/core/image_ops.py`** — White-keying, polygon extraction, knee joint splitting, and hash-validated `AssetBaker` caching in `assets_baked/`.
- **`flat_puppet/core/kinematics.py`** — 2-segment articulated leg walk cycle (hip + knee bend), smooth turn squash transitions, procedural blink generator, and breathing idle motion.
- **`flat_puppet/core/audio.py`** — Asymmetric attack/release RMS envelope smoothing with hysteresis (prevents mouth chatter) + optional Rhubarb Lip Sync JSON support.
- **`flat_puppet/core/puppet.py` & `configs/puppets/*.json`** — Data-driven puppet rig definitions (`gopal.json`, `tara.json`, `gulli.json`).
- **`flat_puppet/core/compositor.py` & `configs/scenes/*.json`** — Data-driven scene staging with virtual camera push-in (`demo_courtyard.json`).
- **`flat_puppet/render/engine.py`** — Multi-core `ProcessPoolExecutor` frame renderer + zero-disk-I/O FFmpeg stdin pipe streamer.
- **`flat_puppet/utils/ffmpeg.py`** — Cross-platform FFmpeg discovery and automatic Devanagari font fallback (`Nirmala UI` on Windows when `Noto Sans Devanagari` is absent).

Made with Muse for the *'Garib Kumhar aur Bolne Wala Ghada'* project.
