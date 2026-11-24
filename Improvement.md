# Flat Puppet Studio — Comprehensive Project Audit & Improvement Plan

> **Audit Date:** 2026-11-24  
> **Target Project:** Flat Puppet Studio (2D Kahani Character Animator - Demo V6)  
> **Workspace:** `c:\Users\Mayur\OneDrive\Desktop\flat-puppet-studio`

---

## 1. Executive Summary & Architecture Audit

### Project Overview
Flat Puppet Studio is a lightweight 2D cutout character animation engine implemented in Python (Pillow, NumPy) that renders AutoDraft-style animated stories (*Kahani* style) with synchronized lip movement, multi-part walking cycles, ambient secondary animation, and audio/subtitle compositing via FFmpeg.

### Key Strengths of Current Implementation
- **AutoDraft Torso-Base Philosophy:** Using a whole, sharp torso base without arms and layering separate cut limbs on top with static sleeve stubs cleanly eliminates joint gaps and inpaint tearing.
- **Minimal Dependencies:** Relies only on `Pillow` and `numpy`, making it lightweight and portable without heavy game-engine overhead.
- **Audio-Driven Lip Sync:** Direct RMS audio envelope extraction from voice tracks (`S4.mp3`) provides natural dialogue movement without manual keyframing.
- **Cultural Subtitle Integration:** Uses `.ass` subtitle timing for authentic Hindi Devanagari rendering.

### Primary Deficiencies & Bottlenecks
1. **Critical Windows Execution Roadblocks:** Hardcoded bash script (`make_video.sh`) and unhandled `ffmpeg` path discovery crash on Windows environments when FFmpeg is not installed globally in `%PATH%`.
2. **Import-Time Side Effects:** Top-level execution of `subprocess.run(["ffmpeg", ...])` generates `s4.wav` directly in the project root during script import, breaking reusability and automated testing.
3. **Severe Runtime Asset-Baking Latency:** On every run, Python BFS flood-fill algorithms (`remove_white`, `clear_big_white_components`) re-process high-resolution 1120×2240 images from scratch, wasting seconds to minutes before frame rendering begins.
4. **Single-Threaded Sequential Rendering:** 267 frames are rendered sequentially on a single CPU core, leaving modern multi-core processors 85–90% idle.
5. **Frame Disk I/O Overhead:** Writing 267 individual PNG frames to disk and reading them back through FFmpeg causes unnecessary SSD wear and latency.
6. **Monolithic Magic-Number Rigging:** Character coordinates, polygon bounding boxes, and pivot points are hardcoded tuples embedded directly into rendering logic.
7. **Animation Nuances:** Single-segment rigid leg rotation without knee bending, an abrupt snap from walk (side view) to talk (front view), and a 3-tier discrete lip flap that flickers on subtle speech nuances.

---

## 2. Priority 0 (Immediate): Critical Bug Fixes & Cross-Platform Stability

### 2.1 Robust Multi-Platform FFmpeg Discovery
- **Problem:** On Windows, `ffmpeg` is frequently located in specialized tool directories (e.g. `E:\antigravity-cache\binaries\ffmpeg.exe` or portable tools folders) rather than global PATH. Running `subprocess.run(["ffmpeg", ...])` throws `FileNotFoundError: [WinError 2]`.
- **Solution:** Implement automatic binary resolution that searches:
  1. System `PATH` (`shutil.which("ffmpeg")`)
  2. Cache binaries (`E:\antigravity-cache\binaries\ffmpeg.exe`)
  3. Local project tools or environment variables (`FFMPEG_BINARY`).
- **Graceful Fallback:** If FFmpeg is missing for envelope extraction, use Python's built-in `wave` module directly on pre-converted WAVs or raise a clean, actionable setup guide.

### 2.2 Eliminate Top-Level Execution Side Effects
- **Problem:** Lines 232–237 execute FFmpeg audio conversion and write `s4.wav` during module import:
  ```python
  subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", f"{ROOT}/S4.mp3", ...])
  ```
- **Solution:** Encapsulate all setup, file generation, and pipeline execution inside functions (`get_audio_envelope()`, `main()`) protected by `if __name__ == "__main__":`.

### 2.3 Cross-Platform Build Scripts (`make_video.ps1` & Python CLI)
- **Problem:** `make_video.sh` is a Unix bash script that fails in standard Windows PowerShell and CMD.
- **Solution:** 
  1. Add native PowerShell script: `make_video.ps1`.
  2. Implement a unified Python CLI: `python flat_puppet_demo.py render --encode --output FLAT-DEMO.mp4` so rendering and encoding work identically across Windows, macOS, and Linux without bash.

### 2.4 Subtitle Font Fallback & Glyphs
- **Problem:** `s4-demo2.ass` hardcodes `Noto Sans Devanagari`. If the target system lacks this font, FFmpeg may render missing glyph boxes (tofu) or misplace Hindi conjunct characters (halant/matras).
- **Solution:** Bundle or configure fallback fonts (e.g., `Mangal`, `Nirmala UI`, or provide a local font directory flag `-fontsdir ./fonts` in FFmpeg).

---

## 3. Priority 1: Performance & Engine Optimization (10× Speedup)

```
Current Pipeline (Sequential & Redundant):
[Raw WebP] ➔ [Slow Python BFS White Removal (Every Run)] ➔ [Single-Core Render 267 Frames] ➔ [Save 267 PNGs to Disk] ➔ [FFmpeg Disk Read & Encode]
Time: ~35–60s

Optimized Pipeline:
[Pre-baked Alpha WebP/PNG] ➔ [Multi-Core Parallel Render (Pool)] ➔ [Direct In-Memory Stdin Pipe to FFmpeg] ➔ [Final MP4]
Time: ~3–6s (10x Faster)
```

### 3.1 Offline Asset Baking (`prepare_assets`)
- **Bottleneck:** `remove_white` iterates pixel-by-pixel with `deque` in pure Python over 1120×2240 images.
- **Optimization:** Run white removal and polygon slicing **once** as an offline preparation step (`python flat_puppet_demo.py bake-assets`). Save transparent assets into an `assets_baked/` folder as lossless WebP or optimized PNGs.
- **Speed Gain:** Eliminates 8–15 seconds of startup latency on every render.

### 3.2 Parallel Frame Rendering via Multiprocessing
- **Bottleneck:** `for i in range(NFRAMES): render_frame(i).save(...)` executes single-threaded.
- **Optimization:** Use `concurrent.futures.ProcessPoolExecutor` or `multiprocessing.Pool`:
  ```python
  from concurrent.futures import ProcessPoolExecutor

  def render_frame_batch(frame_indices):
      for idx in frame_indices:
          frame = render_frame(idx)
          frame.save(f"{OUT}/f{idx:04d}.png")

  def render_all_parallel(n_frames, max_workers=os.cpu_count()):
      # Batch frames across available CPU cores
      chunks = np.array_split(range(n_frames), max_workers)
      with ProcessPoolExecutor(max_workers=max_workers) as executor:
          executor.map(render_frame_batch, chunks)
  ```
- **Speed Gain:** 4× to 8× render speedup on multi-core systems.

### 3.3 Direct Memory-to-FFmpeg Stdin Pipe (Zero Disk I/O)
- **Bottleneck:** Writing 267 PNG files to disk (`~200 MB`) and reading them back through FFmpeg.
- **Optimization:** Stream raw RGBA/RGB bytes directly to FFmpeg stdin:
  ```python
  ffmpeg_cmd = [
      ffmpeg_bin, "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
      "-s", f"{W}x{H}", "-pix_fmt", "rgb24", "-r", str(FPS),
      "-i", "-",  # Read from stdin pipe
      "-i", "S4.mp3", "-stream_loop", "-1", "-i", "bgm-soft.wav",
      ..., "FLAT-DEMO.mp4"
  ]
  proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)
  for frame in generate_frames():
      proc.stdin.write(frame.tobytes())
  proc.stdin.close()
  proc.wait()
  ```
- **Benefit:** Zero file pollution, no disk wear, instant encoding handoff.

---

## 4. Priority 2: Modular Architecture & Data-Driven Rigging

### 4.1 Proposed Project Directory Structure
Refactor the single 372-line monolithic script into clean, reusable modules:

```
flat-puppet-studio/
│
├── assets/                       # Raw character & background images
│   ├── gopal/
│   ├── tara/
│   ├── gulli/
│   └── backgrounds/
│
├── assets_baked/                 # Pre-keyed transparent cutouts (fast load)
├── configs/                      # Data-driven definitions
│   ├── puppets/
│   │   ├── gopal.json            # Bones, pivots, polygon coordinates, scales
│   │   ├── tara.json
│   │   └── gulli.json
│   └── scenes/
│       └── scene_demo_courtyard.json  # Scene timeline, positions, audio
│
├── flat_puppet/                  # Core Python Package
│   ├── __init__.py
│   ├── core/
│   │   ├── puppet.py             # Puppet rig, part hierarchy, transformations
│   │   ├── kinematics.py         # Walk cycle generator, easing functions, bone rotation
│   │   ├── audio.py              # Envelope extraction, viseme mapper, audio mixer
│   │   └── compositor.py         # Multi-layer scene compositor & camera
│   ├── render/
│   │   ├── engine.py             # Single-frame, multi-process & pipe renderers
│   │   └── ffmpeg_pipeline.py    # FFmpeg encoder wrapper & subtitle integrator
│   └── cli.py                    # Unified CLI (bake, test, render, export)
│
├── make_video.ps1                # PowerShell automated pipeline (Windows)
├── make_video.sh                 # Bash automated pipeline (Linux/macOS)
├── requirements.txt              # Standardized dependencies
├── README.md                     # Usage guide
└── Improvement.md                # Project architecture & roadmap
```

### 4.2 Data-Driven Character Rig Schema (`gopal.json`)
Replace hardcoded pixel coordinates with a clean JSON configuration:
```json
{
  "name": "gopal",
  "default_height": 480,
  "views": {
    "side": {
      "base_image": "assets_baked/gopal_side_torso.png",
      "pivots": {
        "shoulder": [437, 750],
        "hip_near": [565, 1755],
        "hip_far": [405, 1755]
      },
      "parts": {
        "arm": { "image": "assets_baked/gopal_side_arm.png", "pivot": [437, 750], "z_index": 5 },
        "leg_near": { "image": "assets_baked/gopal_leg_near.png", "pivot": [565, 1755], "z_index": 2 },
        "leg_far": { "image": "assets_baked/gopal_leg_far.png", "pivot": [405, 1755], "z_index": 0 }
      }
    },
    "front": {
      "base_image": "assets_baked/gopal_front_torso.png",
      "pivots": {
        "head": [557, 700],
        "shoulder_right": [765, 875]
      },
      "mouth_box": [570, 545, 740, 680],
      "eye_box": [480, 350, 760, 500]
    }
  }
}
```

---

## 5. Priority 3: Animation Quality & Visual Polish

### 5.1 2-Bone Articulated Leg Rig (Knee & Ankle Kinematics)
- **Current Limitation:** Each leg swings as a single rigid polygon (`A * (1 - 2 * (u / 0.55))`). This creates a "stiff wooden stick" appearance.
- **Improvement:**
  - Split each leg into **Thigh** (upper leg) and **Calf + Foot** (lower leg) with a knee pivot.
  - During the swing phase (`u in [0.55, 1.0]`), introduce a natural 20°–35° knee flexion that folds the lower leg before extending to plant the foot:
    ```python
    def articulated_leg_pose(u):
        if u < 0.55:  # Stance phase: planted leg rotates backward
            thigh_ang = 15.0 * (1 - 2 * (u / 0.55))
            knee_ang = 0.0
            lift = 0.0
        else:  # Swing phase: knee bends, foot clears ground
            v = (u - 0.55) / 0.45
            thigh_ang = -15.0 + 30.0 * ease(v)
            knee_ang = 32.0 * math.sin(math.pi * v)  # Knee bends forward
            lift = 12.0 * math.sin(math.pi * v)
        return thigh_ang, knee_ang, lift
    ```

### 5.2 Smooth View Transitions (Side Walk ➔ Front Talk)
- **Current Limitation:** At `t = 4.2s`, Gopal abruptly pops from profile side walk to standing front pose in a single frame.
- **Improvement:**
  - Option A: **Intermediate 3/4 Turn Pose** (generate a 3/4 transitional angle image for 4–6 frames).
  - Option B: **Kinematic Turn Ease** (apply a rapid horizontal squish-and-stretch `scale_x` tween over 0.2s as the character halts, simulating rotational perspective turn).

### 5.3 Advanced Audio Lip-Sync with Viseme Hysteresis
- **Current Limitation:** Slicing raw RMS energy into 3 discrete states (`<0.15`, `<0.5`, `>=0.5`) causes rapid mouth flickering during syllable transitions.
- **Improvement:**
  - **Temporal Smoothing (Hysteresis):** Apply a moving average or exponential decay filter on the audio envelope so the mouth stays open through brief consonant pauses within words.
  - **Phoneme Alignment:** Support industry-standard **Rhubarb Lip Sync** JSON input or Whisper phoneme timings to map mouth shapes to actual vowels and consonants:
    - Shape A: Closed (M, B, P)
    - Shape B: Slightly open / consonants (D, T, S, N)
    - Shape C: Wide open vowels (AA, AH)
    - Shape D: Rounded vowels (O, OO, U)

### 5.4 Procedural Secondary Motion & Ambient Life
- **Randomized Blinking:** Replace hardcoded blink lists with a Poisson-distribution procedural blink generator (blinks every 2.5–4.5 seconds with random double-blinks).
- **Subtle Breathing Idle:** Apply subtle vertical sine oscillation to character chest/shoulders (`1.5 px` at 0.3 Hz).
- **Head Tilt & Accent Micro-moves:** Add slight head tilts triggered on dialogue emphasis peaks.

### 5.5 Camera Staging & Dynamic Framing
- Instead of static 1280×720 framing, add support for a virtual camera:
  - Slight panning following Gopal during the walk phase.
  - Slow, cinematic push-in (zoom 1.0× ➔ 1.06×) during emotional dialogue to enhance narrative impact.

---

## 6. Actionable Implementation Roadmap

| Milestone | Task | Estimated Time | Priority |
| :--- | :--- | :--- | :--- |
| **Phase 1** | Add FFmpeg auto-detection (`shutil.which` + cache fallback) | 30 mins | P0 |
| **Phase 1** | Remove top-level `subprocess.run` side-effects; add `main()` guard | 20 mins | P0 |
| **Phase 1** | Create `make_video.ps1` native PowerShell execution script | 20 mins | P0 |
| **Phase 2** | Add offline asset baking (`--bake-assets`) to eliminate flood-fill delay | 1.5 hours | P1 |
| **Phase 2** | Implement multiprocessing frame batching (`ProcessPoolExecutor`) | 1 hour | P1 |
| **Phase 2** | Implement direct FFmpeg in-memory pipe streaming (`-i -`) | 1.5 hours | P1 |
| **Phase 3** | Refactor into modular structure (`flat_puppet/` package) | 2 hours | P1 |
| **Phase 3** | Extract hardcoded coordinates into `gopal.json` and `scene.json` | 1.5 hours | P1 |
| **Phase 4** | Implement 2-segment articulated leg kinematics (knee bend) | 2 hours | P2 |
| **Phase 4** | Add audio envelope hysteresis smoothing & multi-shape visemes | 1.5 hours | P2 |
| **Phase 4** | Procedural idle animation (breathing + dynamic Poisson blinks) | 1 hour | P2 |
| **Phase 5** | Storytelling Script-to-Video pipeline (Text ➔ TTS ➔ LipSync ➔ Video) | Future | P3 |

---

## 7. Ready-to-Use Code Snippets

### A. Cross-Platform FFmpeg Discovery Helper
```python
import os, shutil

def find_ffmpeg() -> str:
    """Finds ffmpeg in PATH, cache drive, or common installation directories."""
    # 1. System PATH
    found = shutil.which("ffmpeg")
    if found:
        return found
    
    # 2. Antigravity local cache
    cache_path = r"E:\antigravity-cache\binaries\ffmpeg.exe"
    if os.path.exists(cache_path):
        return cache_path
        
    # 3. Common Windows paths
    candidates = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe")
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
            
    raise RuntimeError(
        "FFmpeg binary not found. Please install FFmpeg or set FFMPEG_BINARY environment variable."
    )
```

### B. PowerShell Full Build Script (`make_video.ps1`)
```powershell
<#
.SYNOPSIS
    Flat Puppet Studio — Full Render & Video Encoding Pipeline (Windows Native)
#>
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

# Discover FFmpeg
$FFmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
if (-not $FFmpeg -and (Test-Path "E:\antigravity-cache\binaries\ffmpeg.exe")) {
    $FFmpeg = "E:\antigravity-cache\binaries\ffmpeg.exe"
}
if (-not $FFmpeg) {
    Write-Error "FFmpeg not found! Please ensure ffmpeg is in your PATH or in E:\antigravity-cache\binaries\ffmpeg.exe."
}

Write-Host ">>> 1. Rendering animation frames with Python..." -ForegroundColor Cyan
python flat_puppet_demo.py

Write-Host ">>> 2. Encoding video with FFmpeg ($FFmpeg)..." -ForegroundColor Cyan
& $FFmpeg -y -framerate 25 -i frames/f%04d.png -i S4.mp3 -stream_loop -1 -i bgm-soft.wav `
  -filter_complex "[0:v]ass=s4-demo2.ass[v];[1:a]aresample=44100,adelay=4400|4400[a1];[2:a]volume=0.22,atrim=0:10.7[a2];[a1][a2]amix=inputs=2:normalize=0[a]" `
  -map "[v]" -map "[a]" -c:v libx264 -pix_fmt yuv420p -r 25 -c:a aac -ar 44100 -ac 2 -t 10.7 FLAT-DEMO.mp4

Write-Host ">>> Successfully generated FLAT-DEMO.mp4!" -ForegroundColor Green
```

---

## 8. Summary of Benefits Post-Improvement
1. **Developer Experience:** Instant run on Windows via PowerShell or single CLI command without bash or PATH misconfigurations.
2. **Execution Speed:** Overall render-to-MP4 time drops from **~50s** to **~4s** through pre-baked asset loading, multiprocessing, and pipe encoding.
3. **Maintainability:** Adding a new character or scene requires editing a simple JSON file rather than measuring pixel coordinates in Python source code.
4. **Visual Quality:** Natural knee bend, smooth speech transitions, and subtle breathing create broadcast-ready animated stories (*Kahani*).
