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
   python flat_puppet_demo.py bake [--force]                              # Pre-bake cutouts into assets_baked/
   python flat_puppet_demo.py story configs/stories/mitthu_ka_hissa.json -o STORY-DEMO.mp4
   python flat_puppet_demo.py probe assets_story/bansi_front.jpg --step 100 -o .cache/probe.png
   python flat_puppet_demo.py render [--workers 8]                        # Save PNG frames to frames/
   python flat_puppet_demo.py encode --scene configs/scenes/bansi_mango.json --leg-mode sprite8 -o STORY-DEMO.mp4
   ```

## Studio Rulebook & 30-Minute Automation Chain

See **[Rule.md](Rule.md)** for the complete production rulebook covering character selection, organ extraction, Option 4 walk mechanics, 4x face synthesis, TTS/lip-sync, visual QA, and the low-token `story` compiler for scaling cleanly up to 30-minute episodes.

## Architecture

- **`flat_puppet/core/image_ops.py`** — White-keying, polygon extraction, joint splitting, and hash-validated `AssetBaker` caching in `assets_baked/`.
- **`flat_puppet/core/leg_modes.py`** — Option 4 (`sprite8`) 8-pose heel-to-toe studio walk strip & `render_leg_vector()` unified-outline leg renderer.
- **`flat_puppet/core/kinematics.py`** — Analytical 2-bone IK solver (`solve_2bone_ik`), turn squash transitions, procedural blinks, and breathing idle motion.
- **`flat_puppet/core/audio.py`** — Asymmetric attack/release RMS envelope smoothing with hysteresis (prevents mouth chatter) + Rhubarb JSON support.
- **`flat_puppet/core/puppet.py` & `configs/puppets/*.json`** — Data-driven puppet definitions (`gopal`, `tara`, `gulli`, `bansi`, `kavya`, `mitthu`).
- **`flat_puppet/core/compositor.py` & `configs/scenes/*.json`** — Multi-speaker scene staging with camera push-in (`demo_courtyard`, `bansi_mango`).
- **`flat_puppet/tools/puppet_prep.py`** — Coordinate probe grids, closed-ink flood recoloring, arm removal, and 4x supersampled eyes/mouth synthesis.
- **`flat_puppet/tools/voice_and_subs.py`** — Hash-cached Hindi neural TTS (`edge-tts`), silence trimming, procedural SFX, WAV mixing, and ASS subtitle writer.
- **`flat_puppet/tools/story_compiler.py`** — Multi-shot Story Script compiler, stride-matched walk solver, incremental shot cache, and lossless concat stitcher.
- **`flat_puppet/render/engine.py`** — Multi-core `ProcessPoolExecutor` frame renderer + zero-disk-I/O FFmpeg stdin pipe streamer.
- **`flat_puppet/utils/ffmpeg.py`** — Cross-platform FFmpeg discovery and automatic Devanagari font fallback (`Nirmala UI` on Windows).

Made with Muse for the *'Garib Kumhar aur Bolne Wala Ghada'* project.
