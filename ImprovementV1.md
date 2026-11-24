# ImprovementV1.md — Flat Puppet Studio, Next-Iteration Plan

**Prepared:** 2026-11-24
**Scope:** The complete folder as it stands today (`flat_puppet_demo.py`, `make_video.sh`,
`README.md`, `requirements.txt`, `s4-demo2.ass`, 11 `.webp` art files, `S4.mp3`, `bgm-soft.wav`).
**Goal of V1:** turn a working one-file demo into a reliable, repeatable, configurable
mini-studio — without changing the visual style that already works.

---

## 1. Current state (what is already good)

| Area | Observation |
|------|-------------|
| Core idea | Building characters from *separate, clean, armless base art + cut parts* is correct. It avoids holes/blur when limbs move. Keep this. |
| Output | `FLAT-DEMO.mp4`, 1280×720 @ 25 fps, 10.7 s, with voice, BGM and burned-in Hindi subtitles. |
| Rig quality | Side Gopal has near/far legs with a real stance/swing cycle, arm swing, dhoti flap; front Gopal has 3 mouth states, blink, head nod, gesture arm; Tara blinks/breathes; Gulli's tail wags. |
| Lip sync | `mouth_level()` derives mouth openness from RMS loudness of `S4.mp3` — a genuinely useful feature. |
| Caching | `front_cache` already caches the (mouth, blink) head/arm combinations. Good instinct. |
| Docs | `README.md` explains the part-based art method clearly — the most valuable knowledge in the repo. |

This plan therefore focuses on **engineering reliability, workflow, and extensibility**, not on
throwing away the rig.

---

## 2. Findings (evidence from the current code)

Severity: **P0** = breaks correctness/reproducibility, **P1** = slows iteration or risks bugs,
**P2** = quality/maintainability.

| ID | Sev | Location | Finding | Impact |
|----|-----|----------|---------|--------|
| F-01 | P0 | `flat_puppet_demo.py:365-372` | No `if __name__ == "__main__":` guard; module body imports, decodes audio and renders on import. | Cannot import functions for tests, notebooks or reuse; a typo in a test triggers a full 267-frame render. |
| F-02 | P0 | `flat_puppet_demo.py:233-237` | `ffmpeg` is invoked at import time, writes `s4.wav` next to the sources, and `wave.open()` is never closed. | `test` mode fails without ffmpeg; stale/locked file on Windows; hidden side effect. |
| F-03 | P0 | `flat_puppet_demo.py:326-327`, `make_video.sh:6` | `frames/` is created with `exist_ok=True` but never cleaned. | If a later run has fewer frames, old `f0267.png…` are still encoded → ghost frames at the tail. |
| F-04 | P0 | `make_video.sh:11-12` vs `flat_puppet_demo.py:238`, `s4-demo2.ass:12` | Timing lives in three places: `AUDIO_START = 4.4`, `adelay=4400`, subtitle start `0:00:04.40`, plus `TOTAL=10.7` in both files. | Changing the voice timing requires editing 3 files; drift is inevitable. |
| F-05 | P0 | `make_video.sh` (bash), README line 31 | Windows users must manually split the script; `python3` vs `python` inconsistency. | Not one-command reproducible on the stated Windows environment. |
| F-06 | P1 | `flat_puppet_demo.py:239-250` | `envelope()` recomputes RMS slices per call, and is called 2–3× per frame (`mouth_level`, `o = envelope(t)`). | Wasted work every frame; also frame index uses `t*FPS` while sample window uses `sr/FPS` — fragile mixing of two clocks. |
| F-07 | P1 | `flat_puppet_demo.py:20-44`, `55-82` | Pure-Python BFS flood fill over ~2.5 MP images, twice, at startup. | Seconds of latency before the first frame; scales badly as characters are added. |
| F-08 | P1 | `flat_puppet_demo.py:114-115` | `rot()` rotates a full layer with default `expand=False`; pivots can sit near layer edges. | Rotated arms/legs can clip flat at the canvas edge instead of rotating freely. |
| F-09 | P1 | `flat_puppet_demo.py:342-350` | Swing applies vertical lift to the **whole leg including the hip**, not only the foot. | Hip detaches from the dhoti; visible on close inspection. Real knee bend is on the README wish list. |
| F-10 | P1 | `flat_puppet_demo.py:337-363` | Hard cut from side walk to front speak at `t = 4.2`; no transition. | Reads as a jump cut rather than a character turning to face the viewer. |
| F-11 | P1 | `flat_puppet_demo.py:251-253` | Fixed `gain_ref = 0.24` and hard thresholds with no hysteresis. | A quieter take produces a permanently closed mouth; noisy frames make the mouth flap between states. |
| F-12 | P1 | `flat_puppet_demo.py:370-371` | 267 PNG frames written to disk, then re-read by ffmpeg. | Large temp folder, slow I/O, and the stale-frame bug (F-03). |
| F-13 | P2 | Magic numbers throughout (`437,750`, `0.8`, `11.0`, `0.22`, `905`, …) | No config object; README tells users to "search for `0.8`". | Editing is error-prone and undocumented in code. |
| F-14 | P2 | Filenames like `media-generation-flat-gopal-mouth-half-0-a2dfbc…webp` | UUID-suffixed asset names, no manifest/provenance. | Hard to reason about; impossible to regenerate art deterministically. |
| F-15 | P2 | `s4-demo2.ass:8` → `Noto Sans Devanagari` | Font not guaranteed on Windows. | Hindi subtitles render as tofu boxes on machines without the font. |
| F-16 | P2 | README says "V6", docstring says "V4", test files named `test6-*`; no version, license, CHANGELOG or `.gitignore`. | Confusing version identity; no clean repo hygiene. |
| F-17 | P2 | `Image.BICUBIC`, `Image.LANCZOS` (lines 115, 124, 256) | Legacy resampling constants on Pillow ≥ 10. | Deprecation warnings; use `Image.Resampling.*`. |
| F-18 | P2 | `BASE_DIR == ROOT == FLAT`; no type hints; no tests; no error messages for missing assets. | Low readability, slow onboarding, silent failures. |

---

## 3. Prioritized backlog

| ID | Item | Area | Effort | Priority |
|----|------|------|--------|----------|
| A-01 | Add `main()` guard + `argparse` CLI (`test`, `frames`, `render`, `probe`) | Architecture | S | **P0** |
| A-02 | Single `scene.json` as source of truth (timing, fps, assets, pivots, layout) | Config | M | **P0** |
| A-03 | Cross-platform `render_video.py` replacing `make_video.sh` | Workflow | S | **P0** |
| A-04 | Decode audio once into a frame-indexed envelope; close handles; temp dir | Audio | S | **P0** |
| A-05 | Stream RGB frames straight to ffmpeg via `pipe:0`; delete `frames/` from the pipeline | Render | M | **P0** |
| A-06 | Wrap asset loading in validation + clear error messages | Robustness | S | **P1** |
| A-07 | Speed up white-removal with vectorised/optional-scipy connected components | Performance | M | **P1** |
| A-08 | Safe rotation: `expand=True` + re-centre on pivot; cache by quantised angle | Rig | M | **P1** |
| A-09 | Hip-pinned leg swing + thigh/calf knee joint | Animation | L | **P1** |
| A-10 | Side→front turn transition (short crossfade/turn frames) | Animation | M | **P1** |
| A-11 | Adaptive gain + hysteresis for lip sync | Audio | S | **P1** |
| A-12 | Rename assets to semantic names + `assets/manifest.json` | Assets | S | **P2** |
| A-13 | Bundle/pin subtitle font and validate ASS timing against config | Subtitles | S | **P2** |
| A-14 | Package with `pyproject.toml`, tests, `.gitignore`, license, CHANGELOG | Packaging | M | **P2** |
| A-15 | Secondary motion (dhoti/hair/settle) and walk ease-in/out | Animation | L | **P2** |

Legend: S ≈ ≤ 1 hour, M ≈ half a day, L ≈ 1–2 days.

---

## 4. Detailed proposals

### 4.1 A-01 — Entry point and CLI

Replace `TEST = sys.argv[1] == "test"` and the bottom block with:

```python
def main(argv=None):
    p = argparse.ArgumentParser(description="Flat Puppet Studio renderer")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("test", help="render 3 representative frames")
    f = sub.add_parser("frames", help="render all PNG frames")
    f.add_argument("--start", type=float)
    f.add_argument("--end", type=float)
    f.add_argument("--out", default="frames")
    r = sub.add_parser("render", help="render + encode mp4")
    r.add_argument("--scene", default="scene.json")
    r.add_argument("--no-audio", action="store_true")
    r.add_argument("--no-subs", action="store_true")
    args = p.parse_args(argv)
    ...

if __name__ == "__main__":
    raise SystemExit(main())
```

Also split the module into importable functions: `load_assets()`, `build_rigs()`,
`render_frame(t)`, `render_range()`, `encode()`. Keep one file for V1 if you prefer, but the
guard is non-negotiable.

### 4.2 A-02 — One config file

Create `scene.json` next to the script. Everything currently scattered becomes data:

```json
{
  "version": 1,
  "fps": 25,
  "width": 1280,
  "height": 720,
  "duration": 10.7,
  "coordinate_space": "source_1120x2240",
  "audio": {
    "voice": "S4.mp3",
    "voice_delay_ms": 4400,
    "music": "bgm-soft.wav",
    "music_volume": 0.22,
    "subtitles": "s4-demo2.ass",
    "gain_ref": 0.24,
    "mouth_thresholds": [0.15, 0.5],
    "hysteresis": 0.05
  },
  "assets": {
    "background": "media-generation-flat-courtyard-rich-....webp",
    "gopal_side_base": "media-generation-flat-gopal-side-noarm-legsapar-....webp",
    "gopal_side_orig": "media-generation-flat-gopal-side-0-....webp",
    "gopal_front_base": "media-generation-flat-gopal-front-noarm-....webp",
    "gopal_front_body": "media-generation-flat-gopal-body-....webp",
    "gopal_mouth_half": "media-generation-flat-gopal-mouth-half-....webp",
    "gopal_mouth_open": "media-generation-flat-gopal-mouth-open-....webp",
    "gopal_eyes": "media-generation-flat-gopal-eyes-closed-....webp",
    "tara": "media-generation-flat-tara-body-....webp",
    "tara_eyes": "media-generation-flat-tara-eyes-closed-....webp",
    "gulli": "media-generation-flat-gulli-side-....webp"
  },
  "layout": {
    "ground_y": 692,
    "tara": {"x": 905, "height": 360, "breathe_hz": 0.3, "breathe_px": 1.0},
    "gulli": {"x": 625, "height": 185, "tail_hz": 0.9, "tail_deg": 7},
    "gopal": {"walk_from_x": -60, "walk_to_x": 330, "front_x": 350,
              "side_height": 470, "front_height": 480}
  },
  "rigs": {
    "gopal_side": {
      "pivots": {"shoulder": [437, 750], "hip_near": [565, 1755], "hip_far": [405, 1755]},
      "parts": {
        "arm": [[362,700],[515,700],[530,990],[510,1440],[500,1560],[480,1690],[380,1690],[355,1560],[350,1440],[344,990]],
        "leg_near": [[460,1730],[665,1730],[660,1900],[630,2030],[700,2090],[782,2130],[782,2180],[470,2180],[450,2000],[448,1850]],
        "leg_far":  [[325,1730],[485,1730],[470,1850],[400,1960],[350,2030],[438,2090],[438,2180],[220,2180],[205,2090],[265,1950],[300,1830]]
      }
    },
    "gopal_front": {
      "pivots": {"head": [557, 700], "arm": [765, 875]},
      "boxes": {"mouth": [[570,545],[740,680]], "eyes": [[480,350],[760,500]]}
    }
  },
  "animation": {
    "walk": {"duration": 4.2, "steps_per_sec": 0.8, "swing_deg": 15.0,
             "stance_ratio": 0.55, "foot_lift_px": 11.0, "bob_px": 3.5},
    "blinks": {
      "tara":  [[1.2,1.32],[2.8,2.92],[5.2,5.32],[7.8,7.92],[10.3,10.42]],
      "gopal": [[7.15,7.27],[9.8,9.92]]
    },
    "gestures": [[5.5,6.7],[8.1,9.3]],
    "gesture_deg": 28
  }
}
```

Rules:
- `voice_delay_ms` is the **only** source for `AUDIO_START`, `adelay` and the first ASS line.
- `duration` is the only source for `TOTAL`, `NFRAMES`, `atrim` and `-t`.
- Validate at load: asset exists, `duration * fps` is an integer-ish frame count, ASS last
  `End` ≤ `duration`, all polygon points inside the declared source size.

### 4.3 A-03/A-05 — One cross-platform render+encode path

Delete `make_video.sh` (or keep it as a 2-line wrapper). Do the encode in Python and feed
frames over stdin, which removes both the bash dependency and the `frames/` folder entirely:

```python
cmd = [
    "ffmpeg", "-y", "-v", "error",
    "-f", "rawvideo", "-pixel_format", "rgb24",
    "-video_size", f"{cfg.width}x{cfg.height}",
    "-framerate", str(cfg.fps), "-i", "pipe:0",
    "-i", str(voice), "-stream_loop", "-1", "-i", str(music),
    "-filter_complex", (
        f"[0:v]ass={ass_arg}[v];"
        f"[1:a]aresample=44100,adelay={delay}|{delay}[a1];"
        f"[2:a]volume={vol},atrim=0:{dur}[a2];"
        f"[a1][a2]amix=inputs=2:normalize=0[a]"
    ),
    "-map", "[v]", "-map", "[a]",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(cfg.fps),
    "-c:a", "aac", "-ar", "44100", "-ac", "2", "-t", str(dur),
    str(out_mp4),
]
proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
for i in range(nframes):
    proc.stdin.write(render_frame(i / cfg.fps).convert("RGB").tobytes())
proc.stdin.close()
if proc.wait() != 0:
    raise RuntimeError("ffmpeg encode failed")
```

Notes:
- Escape `ass_arg` for Windows paths (`C\:/…`) or simply `cwd=BASE_DIR` and pass the relative
  ASS filename — the latter is simpler and matches how the filter is used today.
- Keep `--no-audio` / `--no-subs` switches for debugging; build the filter graph conditionally.
- If you still want PNG frames for inspection, `frames` mode writes to a **fresh** temp dir
  created with `tempfile.mkdtemp()`, so stale frames cannot leak into an encode.

### 4.4 A-04 — Audio envelope, computed once

Pre-decode with ffmpeg into a temp PCM file (or capture stdout), then build a numpy array
indexed by *frame number*, not by seconds:

```python
pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
hop = max(1, int(round(sr / cfg.fps)))
n = int(round(cfg.duration * cfg.fps))
lead = int(round(cfg.audio.voice_delay_ms / 1000 * cfg.fps))
buf = np.zeros((lead + n + 2) * hop, dtype=np.float32)
buf[lead * hop: lead * hop + pcm.size] = pcm[: max(0, (n + 2) * hop)]
win = buf[:(n + 2) * hop].reshape(n + 2, hop)
rms = np.sqrt(np.mean(win ** 2, axis=1))
env = np.minimum(rms[:n] / cfg.audio.gain_ref, 1.0)   # env[frame_index]
```

Then `mouth_level(i)` is a lookup plus hysteresis:

```python
level = 0 if e < t0 else (1 if e < t1 else 2)
if abs(level - prev) == 1 and t0 - h < e < t1 + h:   # in the grey zone
    level = prev
prev = level
```

Adaptive option: set `gain_ref` to the 90th percentile of `rms` instead of a constant so any
take drives the mouth correctly. Always close the wave/PCM handle with a context manager.

### 4.5 A-06/A-07 — Loading and speed

- Resolve every asset through `asset_path(name)`: raise `FileNotFoundError` with the config key
  and absolute path instead of letting `Image.open` fail deep in the pipeline.
- Check base/variant sizes match before `load_char()` crops them with a shared bbox; mismatched
  canvases currently produce silently misaligned parts.
- Replace the two flood fills with a vectorised connected-component label:
  `scipy.ndimage.label(white, structure=np.ones((3,3)))` → keep only components touching the
  border. Make `scipy` an optional extra; fall back to the existing BFS if unavailable.
  Cache the processed result per asset in memory for the whole run.
- Switch to `Image.Resampling.BICUBIC / LANCZOS` (F-17), and use `with Image.open(...)` everywhere.

### 4.6 A-08/A-09/A-10 — Rig and animation upgrades

**Safe rotation:** rotate with `expand=True`, then translate so the pivot stays put:

```python
def rot_at(layer, angle, pivot):
    box = (0, 0, layer.width, layer.height)
    r = layer.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    return r, (int(pivot[0] - angle_cos * pivot[0] + angle_sin * pivot[1]),
               int(pivot[1] - angle_sin * pivot[0] - angle_cos * pivot[1]))
```

Practical shortcut: pad every part with ~40 px transparent margin at load time, keep the current
`expand=False` call, and add the same margin to its pivot. Much smaller code change, same result.
Cache `rot(layer, round(angle, 1))` in an LRU dict — adjacent frames often share an angle.

**Hip-pinned leg + knee (F-09):** keep the hip point fixed; rotate only the polygon around the
hip and move the *foot* vertically by `lift`. To add a knee, split each leg into thigh and calf
pieces with a `KNEE_P` pivot and drive calf angle from `v` in `leg_pose()`:
`knee = -35 * math.sin(math.pi * v)` during swing, `≈0` during stance. The dhoti layer already
covers the top, so the joint stays hidden.

**Turn transition (F-10):** reserve 8–10 frames around `WALK_DUR` (`4.2 s`). Options, cheapest
first:
1. Crossfade last side-walk frame into first front frame (`Image.blend`) — 5 lines of code.
2. Add a 3-frame "turning" side pose with the arm closer to the body, then crossfade.
3. Full turn-around rig with a back view (out of scope for V1 — see §9).

Also ease the walk velocity: replace linear `x = -60 + 390*(t/WALK_DUR)` with
`ease(t/WALK_DUR)` so Gopal starts and stops naturally.

### 4.7 A-12/A-13/A-14 — Assets, subtitles, packaging

- Rename assets to semantic names (`gopal_side_noarm.webp`, `gopal_mouth_half.webp`, …) and add
  `assets/manifest.json` with `source`, `prompt`, `derived_from`, `license`. Keep the UUID in the
  manifest for traceability; no need to keep it in the filename.
- Ship `fonts/NotoSansDevanagari-Regular.ttf` (or detect `Nirmala UI` on Windows) and reference
  it explicitly in the ASS style; assert in config validation that subtitle end times and
  `duration` agree.
- Add `pyproject.toml`:

```toml
[project]
name = "flat-puppet-studio"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["Pillow>=10.0", "numpy>=1.24"]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.5"]
fast = ["scipy>=1.11"]

[project.scripts]
flat-puppet = "flat_puppet.cli:main"
```

- Add `.gitignore`: `frames/`, `*.wav` generated PCM, `test6-*.png`, `FLAT-DEMO.mp4`, `__pycache__/`.
- Add `LICENSE` (the artwork is AI-generated; state the terms explicitly) and `CHANGELOG.md`.
- Fix version identity: pick **V1** for this repo, update README title, docstring, test filenames.
- Add three small test files: `test_config.py` (validation), `test_audio.py` (envelope on a
  synthetic sine wave), `test_pose.py` (`leg_pose` continuity at `u=0.55` and `u=1.0`). Add a
  golden-frame smoke test comparing rendered frames against saved PNGs with a small pixel
  tolerance.

---

## 5. Proposed V1 folder structure

```
flat-puppet-studio/
├─ pyproject.toml
├─ README.md                 # rewritten for V1
├─ CHANGELOG.md
├─ LICENSE
├─ .gitignore
├─ scene.json                # the single source of truth
├─ flat_puppet/
│  ├─ __init__.py
│  ├─ cli.py                 # argparse entry point
│  ├─ config.py              # load + validate scene.json
│  ├─ assets.py              # white removal, cropping, caching
│  ├─ rigs.py                # part polygons, pivots, rotation helpers
│  ├─ audio.py               # ffmpeg decode + frame-indexed envelope
│  ├─ scene.py               # render_frame(t), blink/gesture/walk curves
│  └─ encode.py              # ffmpeg pipe:0 + filter graph builder
├─ assets/
│  ├─ manifest.json
│  ├─ art/*.webp              # semantic filenames
│  └─ fonts/NotoSansDevanagari-Regular.ttf
├─ media/
│  ├─ S4.mp3
│  ├─ bgm-soft.wav
│  └─ s4-demo2.ass
├─ tests/
│  ├─ test_config.py
│  ├─ test_audio.py
│  ├─ test_pose.py
│  └─ golden/*.png
└─ out/                      # generated mp4 only, git-ignored
```

If you want the smallest possible change, keep `flat_puppet_demo.py` but still add the
`main()` guard and `scene.json` — those two deliver most of the value.

---

## 6. Migration phases

- **Phase 1 — Safety (½ day):** A-01, A-04, A-06, plus `exist_ok` cleanup. End state: `python
  flat_puppet_demo.py test` works without side effects and no stale frames are possible.
- **Phase 2 — One source of truth (½ day):** A-02, A-03, A-05. End state: `python render_video.py`
  produces the same MP4 in one command on Windows and Linux; `frames/` no longer required.
- **Phase 3 — Quality (1–2 days):** A-08, A-09, A-10, A-11. End state: no hip gap, smooth
  turn, stable lip sync.
- **Phase 4 — Polish (½ day):** A-12, A-13, A-14. End state: installable package, tests,
  consistent docs.

---

## 7. Acceptance criteria for V1

1. `python -m flat_puppet render` (or `python render_video.py`) produces `FLAT-DEMO.mp4`
   **byte-for-byte comparable** to the current output at a glance: same 1280×720, 25 fps,
   10.7 s, same poses at t = 0.36 / 0.96 / 6.0 s.
2. No file in the source folder is modified by a render (no `s4.wav`, no `frames/`).
3. Changing `voice_delay_ms` in `scene.json` moves voice **and** subtitles together; no other
   file needs editing.
4. Running the renderer twice in a row with different durations produces the same-length MP4
   both times (no ghost frames).
5. `pytest` passes; a missing asset produces a clear error naming the config key.
6. The README explains one command for Windows and one for Linux/macOS, with no manual
   "run these two lines separately" step.

---

## 8. Non-goals for V1 (deliberately deferred)

- GUI/timeline editor.
- Script-driven multi-shot scenes (dialogue → shots) — the config is the stepping stone.
- Full character sets (Tara walk, Gauri, Seth), back view, left-side view.
- Re-generating the AI artwork or changing the flat visual style.
- Real phoneme-level viseme sync; RMS + hysteresis is sufficient for V1.

---

## Appendix A — One-day quick wins (do these first)

1. Add `if __name__ == "__main__": main()` and `argparse`.
2. Wrap `wave.open(...)` in `with`, write `s4.wav` to `tempfile.gettempdir()`.
3. Delete the `frames/` directory at the start of a full render (`shutil.rmtree(OUT, ignore_errors=True)`).
4. Precompute `envelope` into a numpy array indexed by frame; index once in `render_frame`.
5. Replace `Image.BICUBIC/LANCZOS` with `Image.Resampling.BICUBIC/LANCZOS`.
6. Pad arm/leg layers by 40 px transparent margin to stop rotation clipping.
7. Add `.gitignore` and align the version name everywhere to V1.

These seven changes are low-risk, take roughly a day total, and remove most of the P0/P1
failures above without touching the look of the animation.
