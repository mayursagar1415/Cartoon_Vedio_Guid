# Flat Puppet Studio — Master Production Rulebook & 30-Minute Automation Chain

> **Complete Engineering & Art-Direction Playbook** covering everything used to build pixel-clean **2D Kahani Animations** (including [STORY-DEMO.mp4](STORY-DEMO.mp4)) and how to scale seamlessly from 10 seconds to **30-minute episodes** with minimal tokens.

---

## 1. The Golden Architecture Rule (Why Cutout-Torso Beats Robotic Rigging)

Never assemble humans out of loose "numbered parts sheets" (isolated cylinder thighs/calves/forearms stacked end-to-end with circular dots) or floating geometric capsules — segmented floating shapes always read as **robotic**.

Instead, follow the **AutoDraft Studio Cutout Architecture**:

| Role | Required Views | Why It Looks Hand-Drawn (Zero Seams) |
| :--- | :--- | :--- |
| **Hero / Main Walker + Speaker** | `front` (arm separated) + `front_noarm` + `side` + `side_noarm` + face variants | Complete, unbroken hand-drawn torso base (`front_noarm` & `side_noarm`) sits *underneath* moving limbs. Moving arms only cover shoulder/elbow seams using `sleeve_stub` + joint caps (`gol tukda`). |
| **Partner / Standing Speaker** | `front` (closed smile) + `eyes_closed` + optional `mouth_half` + `mouth_open` | Full body moves naturally with breathing & subtle conversational head tilt while eyes blink & mouth shape swaps cleanly in place. |
| **Companion Creature / Prop** | `side` sprite with isolated tail/wing polygon | Animated with secondary spring/oscillation (`tail_pivot_rel`) and celebratory `hop_windows` synced to SFX. |

---

## 2. Character Selection, Framing & Art Style Rules

When generating or selecting characters and backgrounds (`image-generator` or bespoke artwork):

1. **Consistent 2D Vector Ink Line & Cel Shading:**
   - Thick continuous dark ink outlines (`#14100C`, ~4–6 px on portrait sprites).
   - Flat cel fills with subtle 1-step shadow tones. Zero photorealism, zero 3D gradients, zero floor shadows baked onto character PNGs.
2. **Mandatory Aspect Ratios & Margins:**
   - **Backgrounds (`16:9`):** Wide landscape (`1376×768` / `1920×1080` -> rendered at `1280×720`). Must keep an **uncluttered horizontal dirt/floor strip** across bottom `y ≈ 92%–96%` (`ground_y = 688–692`) so characters can walk across without stepping on props.
   - **Human Characters (`9:16` portrait):** Full body from top of turban/hair to bare feet on **pure solid white (`#FFFFFF`)** with clean margins (`50–80 px` top & bottom). Never cut off toes or turban top.
   - **Companions/Animals (`3:2` landscape):** Side profile sitting cleanly on `#FFFFFF` with tail/wings sticking out cleanly from the main silhouette (`mitthu_parrot.jpg`).
3. **White-Keying Protection Rules (`image_ops.py`):**
   - `remove_white()` flood-fills from borders (`RGB > (232, 230, 222)`) and applies `MinFilter(5)` + `GaussianBlur(0.8)` for clean anti-aliased cutout edges.
   - **Rule:** White dhotis, shirts, eyes, and teeth MUST be enclosed inside a continuous dark `#14100C` ink outline so border flood-fill never eats inside clothes or sclera.
   - Always set `"protect_box": [x0, y0, x1, y1]` around faces in standing puppets so `clear_big_white_components()` removes interior background gaps (between arm & waist) without ever deleting eye whites or teeth.
   - Always check clothes palette contrast against the background sky (`#5FC6FC`) and hills (`#6DB844`): warm maroon, golden amber, magenta-rose, teal, and cream pop cleanly.

---

## 3. Body-Organ, Face & Clothing Prep Rules (`flat_puppet/tools/puppet_prep.py`)

Never guess pixel coordinates by eye. Always inspect first, isolate by ink boundaries, and synthesize at 4× supersampling.

### Rule 3A — Probe Grids Before Writing Any Config
Always generate a pixel coordinate overlay before defining pivots, mouth boxes, eye boxes, or polygons:
```bash
python flat_puppet_demo.py probe assets_story/bansi_front.jpg --step 100 -o .cache/probe.png
python flat_puppet_demo.py probe assets_story/mitthu_parrot.jpg --norm -o .cache/probe_norm.png
```
- **What to record for a Hero `front` puppet (`configs/puppets/*.json`):**
  - `neck_cut_y`: horizontal Y on the cropped `front_noarm` image right below the chin inside the collar.
  - `pivots.head`: `[cx, y]` base of neck/collar where head rotates naturally.
  - `pivots.arm`, `elbow`, `wrist`: exact joint centers along the active gesturing arm (`elbow` becomes 2-bone IK middle joint).
  - `polygons.arm` & `polygons.sleeve_stub`: tight cutout containing arm + upper sleeve cuff.
  - `boxes.eyes` & `boxes.mouth`: tight rectangles enclosing eyes / smile line without hitting mustache ends or eyebrows.
  - `offsets`: `[fb[0] - base_bbox[0], fb[1] - base_bbox[1]]` (`[0, 0]` when left/top margins match; non-zero when `front_orig` extends further left than `front_noarm`).

### Rule 3B — Arm Removal (`reconstruct_front_noarm`)
When deriving `front_noarm` from an existing front drawing:
1. Keep the **artist's original chest side-wall contour** completely untouched up to the armpit.
2. Erase to pure `#FFFFFF` strictly outside that curve + the protruding sleeve/arm.
3. Fill only the short upper shoulder corner in the sampled kurta RGB and splice a **4× supersampled curved ink stroke** connecting the neck collar cleanly onto the existing chest wall (`ink_width = 5.2`).
4. Layer `front_stub` (sleeve cuff) *on top* of the rotating 2-bone arm (`_paste_2bone_limb`) so raising the hand up `-55 px` never exposes a hollow armpit.

### Rule 3C — Garment Recoloring Without Skin Leaks (`flood_enclosed`)
Never use flat horizontal `y0..y1` rectangles to recolor clothes — that creates visible cutoff bands at collars, sleeves, and dhoti hems.
1. Flood-fill (`flood_enclosed`) from interior cloth seed points stopping strictly at dark ink lines (`luma <= 90.0`).
2. Add tight chroma guards (`R - B >= 16` distinguishes warm cream kurta from white dhoti; `R - G > 74 & B < 95` isolates bright trim ribbons from bare arm skin).
3. Use `recolor_region()` which scales target RGB by normalized luminance while fading linearly near `luma <= 55` — **100% preserving anti-aliased ink lines**.

### Rule 3D — 4× Supersampled Blink & Mouth Synthesis
- **Closed Eyes (`synthesize_eyes_closed`):** Sample cheek/inner-bridge skin RGB **inside** the face (never near white outside margins!), clear the white eye ellipses cleanly avoiding nose-bridge ink & eyebrows, and draw 4× supersampled downward-curved closed eyelid arcs (`width = 5.0`), downsampled via `LANCZOS`.
- **Mouth Half / Open (`synthesize_mouths`):**
  - First erase the **entire** closed smile line + corner smile ticks + lower dimple using a `rounded_rectangle` clear box in chin/cheek skin RGB.
  - Draw 4× supersampled D-shaped open cavities (`#200B0C` fill, crisp dark `#120E0C` outline, `#F9F7F3` upper teeth strip, `#C45250` warm tongue).
  - For moustached characters, pass `mustache_preserve_y` to restore all original dark pixels (`RGB < 48`) above the upper lip line so whiskers never clip.

### Rule 3E — Clean Side Walk Cutting (`puppet.py`)
- **Dhoti Hem Clean Cut (`hem_cut_y: 1732`):** Trim `side_torso` right below the skirt hem with `rect_part(..., feather=2.5)` so zero stray ankle/toe outline pixels float under the dhoti.
- **Finger Dhoti-Leak Guard:** Clear bright white dhoti pixels (`RGB > (202, 200, 192)`) inside `side_arm_lower` below the `wrist` pivot so fingers stay crisp against background props.

---

## 4. Walk Cycle, Kinematics & Option 4 Rules (`leg_modes.py`, `kinematics.py`)

- **Always default to `leg_mode = "sprite8"` (Option 4):**
  Uses 8 studio keyframes (`_SPRITE8_KEYFRAMES`: Contact -> Down squash -> Passing -> High-Point -> Toe-off -> Swing fold -> Swing reach -> Pre-contact) driving **unified-outline procedural vector legs (`render_leg_vector` @ 2× supersampling)** matched to the character's exact `skin_rgb` (with `0.85×` darkened far leg for depth separation). Zero cut seams, natural knee flexion (`-30°`), heel-to-toe foot roll, aligned `far_ankle_y == near_ankle_y`, and rhythmic vertical body bounce (`-4.0 px` to `+1.5 px`).
- **Zero Foot-Slide Stride Formula (`stride_matched_walk_cps`):**
  One full `sprite8` cycle (`step_amp = 18.0°`) at `~475 px` height covers **`~142 px`** on ground. Always set:
  ```python
  walk_cycles_per_sec = clamp(|walk_x_end - walk_x_start| / (142.0 * walk_duration), 0.55, 1.05)
  ```
- **2-Bone Analytical Arm IK (`solve_2bone_ik`):**
  Arm gestures move hand targets (`hand_ik_dx`, `hand_ik_dy`) from `configs/actions/speak_gesture.json` via Law of Cosines (`bend_sign=1`) so shoulder + elbow bend organically in one smooth `ease_in_out_cubic` arc. Joint seams are hidden under `cap` (`split_limb_at_joint`) and rotated safely with `rot_safe()` (`expand=True` + exact float pivot compensation quantized to `0.1°` for caching).
- **Smooth View Turn (`turn_transition_scale`):**
  Only apply the `0.14s` horizontal turn squeeze (`scale_x = 0.38 -> 1.0`) when `walk_duration > 0.05`. Never trigger it on stationary (`walk_duration = 0`) dialogue shots or frame 0 will flatten briefly.

---

## 5. Voice, Lip-Sync, Audio Mix & Subtitle Rules (`voice_and_subs.py`, `audio.py`)

1. **Free Natural Hindi Neural Voices (`edge-tts`):**
   - Male voice: `hi-IN-MadhurNeural` (e.g. `rate="+12%", pitch="-3Hz"`).
   - Female / child voice: `hi-IN-SwaraNeural` (e.g. `rate="+12%", pitch="+4Hz"`).
   - Run via a UTF-8 Python call inside `E:\antigravity-cache\packages\venvs\automation\Scripts\python.exe` — never inline Hindi strings directly in PowerShell `-c` double quotes.
2. **Always Strip Silence Before Timing:**
   Trim leading/trailing silence on every TTS output using FFmpeg `silenceremove` (`-45dB` forward & reversed), convert to `22050 Hz mono PCM WAV`, and read exact duration via `wave` header before computing subtitle start/end times.
3. **Chatter-Free Lip-Sync (`AudioAnalyzer`):**
   - Master mix (`story_voice_mix.wav`) drives FFmpeg audio, while **each speaking character gets an isolated WAV track** (`hero_lip.wav` / `partner_lip.wav`) so silent listeners keep closed smiling mouths while the other character speaks.
   - Use asymmetric envelope smoothing (`alpha = 0.72` attack, `0.42` release), `gain_ref="auto"` (90th percentile normalization), and hysteresis thresholds (`0.11 / 0.17 / 0.43 / 0.52`) to prevent rapid mouth fluttering.
4. **Devanagari Subtitles (`ffmpeg.py` + `write_ass_file`):**
   - Give speakers distinct `.ass` colors (`&H0066E0FF` warm amber for hero, `&H00FFFFFF` white for partner) with `Outline=3`.
   - `prepare_ass_subtitles()` automatically maps `"Noto Sans Devanagari"` -> `"Nirmala UI"` on Windows so matras/conjuncts render cleanly.

---

## 6. Mandatory Visual QA Checklist Before Delivering Any Video

Inspect generated strips & decoded frames before declaring success:
1. Run `python -m unittest discover -s tests -v` — all tests must pass.
2. Extract a multi-frame contact sheet **from the final encoded MP4** (testing start walk, turn transition, each speaker talking, and end SFX):
   ```bash
   E:\antigravity-cache\binaries\ffmpeg.exe -y -i OUTPUT.mp4 -vf "select='eq(n,30)+eq(n,84)+eq(n,115)+eq(n,190)+eq(n,230)+eq(n,260)',scale=640:360,tile=3x2" -frames:v 1 .cache\qa_sheet.jpg
   ```
3. Inspect full-res frames for:
   - Feet touch `ground_y` smoothly with no hovering/clipping.
   - Armpit/chest ink contour stays continuous under maximum IK hand lift.
   - Closed eyes show matching skin color (no white sclera leaks) and mustaches remain intact above open mouths.
   - Subtitles sit inside bottom margin cleanly without overlapping feet or missing Devanagari conjuncts.

---

## 7. Low-Token Automation Chain for 30-Minute Videos

To produce a **5-minute, 15-minute, or 30-minute animated Kahani** without rewriting Python or hand-timing hundreds of dialogue timestamps:

### How the Single-Command Chain Works
You author ONLY one compact **Story Script JSON** (like [configs/stories/mitthu_ka_hissa.json](configs/stories/mitthu_ka_hissa.json)) and run **one command**:

```bash
python flat_puppet_demo.py story configs/stories/my_episode.json -o EPISODE-01.mp4 --workers 8
```

Inside `flat_puppet/tools/story_compiler.py`, the compiler automatically runs the entire studio pipeline end-to-end:
1. **Hash-Cached Batch TTS:** Synthesizes only new/changed Hindi lines (`tts_cache/<sha1>.wav`) and trims silence automatically.
2. **Exact Timeline Auto-Solver:** Uses measured WAV durations to compute exact dialogue start/end timestamps, stride-matched `walk_cycles_per_sec`, `gesture_windows`, `camera` zoom timings, `procedural_blinks`, `.ass` subtitles, and per-speaker lip-sync WAV mixes.
3. **One-Time Asset Bake:** Bakes character cutouts **once** (`assets_baked/`) and reuses them across all 150–250 shots.
4. **Incremental Shot Hash Caching:** Hashes every compiled `shot_NNN.json` -> renders only changed/new shots across 8 parallel CPU workers via zero-disk-I/O FFmpeg stdin pipe (`ProcessPoolExecutor`). Editing dialogue in Shot 84 of a 30-minute video re-renders **only Shot 84 (~10s)**!
5. **Lossless Stream-Copy Concat (`ffmpeg -f concat -c copy`):** Merges all rendered shot MP4s in under 1 second with identical `H.264 / yuv420p / 25fps / AAC 44.1kHz` encoding parameters and zero re-encoding loss.

### Stored Code Reference in This Repository

| Module | Purpose |
| :--- | :--- |
| [flat_puppet_demo.py](flat_puppet_demo.py) / [cli.py](flat_puppet/cli.py) | Unified CLI: `story`, `probe`, `bake`, `test`, `render`, `encode` |
| [flat_puppet/tools/puppet_prep.py](flat_puppet/tools/puppet_prep.py) | Coordinate grid prober, flood-fill recoloring, no-arm torso repair, 4× eye/mouth synthesis |
| [flat_puppet/tools/voice_and_subs.py](flat_puppet/tools/voice_and_subs.py) | Hash-cached `edge-tts`, silence trimming, procedural parrot chirp, FFmpeg mixer, `.ass` builder |
| [flat_puppet/tools/story_compiler.py](flat_puppet/tools/story_compiler.py) | Story Script JSON compiler, stride-lock math, incremental shot renderer & lossless concat stitcher |
| [flat_puppet/core/puppet.py](flat_puppet/core/puppet.py) | Generalized multi-character baking & scaled asset loader |
| [flat_puppet/core/compositor.py](flat_puppet/core/compositor.py) | Multi-speaker compositor, 2-bone IK arm, Option 4 walk dispatch, camera push-in |
| [flat_puppet/core/leg_modes.py](flat_puppet/core/leg_modes.py) | Option 4 (`sprite8`) 8-pose studio walk & `render_leg_vector()` |
| [flat_puppet/core/kinematics.py](flat_puppet/core/kinematics.py) | Analytical 2-bone IK (`solve_2bone_ik`), `turn_transition_scale`, `procedural_blinks`, breathing |
| [flat_puppet/core/actions.py](flat_puppet/core/actions.py) | Keyframed Action Library (`walk_cycle.json`, `speak_gesture.json`) with smooth easing curves |
| [flat_puppet/core/config.py](flat_puppet/core/config.py) | Strict scene JSON & ASS subtitle timing validation |
| [flat_puppet/core/audio.py](flat_puppet/core/audio.py) | Per-speaker smoothed RMS lip-sync envelope & hysteresis |
| [flat_puppet/core/image_ops.py](flat_puppet/core/image_ops.py) | Border flood-fill keying, `split_limb_at_joint`, `rot_safe`, `AssetBaker` |
| [flat_puppet/render/engine.py](flat_puppet/render/engine.py) | Multi-core `ProcessPoolExecutor` frame renderer & FFmpeg pipe encoder |
| [flat_puppet/utils/ffmpeg.py](flat_puppet/utils/ffmpeg.py) | Cross-platform FFmpeg lookup & Windows Devanagari font fallback (`Nirmala UI`) |

### Speed & Budget Estimate for a 30-Minute Video
- **30 minutes @ 25 fps** = `45,000` frames (~`160–180` shots of `10–12s` each).
- At current 8-worker pipe encode speed (`~10s` per `270` frames = `~27 fps` sustained), full cold render takes **~25–28 minutes** once; subsequent dialogue/shot tweaks re-render **only touched shots (~10s per shot)** thanks to `tts_cache` + `renders/shot_*_<hash>.mp4`!
- Because shots encode independently and stitch with `-c copy`, RAM stays flat across the entire 30-minute run with zero memory leaks or massive intermediate PNG folders.

---

### Minimal Multi-Shot Template for Future Episodes

```json
{
  "name": "episode_02",
  "fps": 25,
  "width": 1280,
  "height": 720,
  "ground_y": 688,
  "default_background": "assets_story/story_orchard_bg.jpg",
  "bgm": "bgm-soft.wav",
  "bgm_volume": 0.16,
  "cast": {
    "hero": { "puppet": "bansi", "display_name": "बंसी चाचा", "leg_mode": "sprite8", "skin_rgb": [215, 141, 91], "tts_voice": "hi-IN-MadhurNeural", "ass_color": "&H0066E0FF" },
    "partner": { "puppet": "kavya", "display_name": "काव्या", "height": 355, "x": 885, "tts_voice": "hi-IN-SwaraNeural", "ass_color": "&H00FFFFFF" },
    "companion": { "puppet": "mitthu", "height": 162, "x": 675 }
  },
  "shots": [
    {
      "walk_in": true,
      "walk_duration": 3.2,
      "walk_x_start": -55,
      "walk_x_end": 315,
      "talk_x": 335,
      "lines": [
        { "speaker": "hero", "text": "अरे काव्या, आज क्या नया सीख रही हो?", "gesture": true }
      ]
    },
    {
      "walk_in": false,
      "talk_x": 335,
      "lines": [
        { "speaker": "partner", "text": "चाचा, आज हम पेड़ लगाने की कहानी लिख रहे हैं!" }
      ],
      "sfx": [{ "type": "chirp", "hop": true }]
    }
  ]
}
```
