# Handoff: Apple M1-class performance work

This document is the complete handoff for a performance pass on one Switch 2 title running through
nxnative on an Apple M1 Pro. It covers the goal, the branches in this fork, every change made, the
measurements, the open GPU fault, how to build and run, and what to do next. The title is referred
to as "the target game"; its profile lives in `dm/games/<title-id>/`.

## 1. Goal and constraints

- **Goal:** the best frame rate and the fewest glitches for the target game on an Apple M1 Pro
  (32 GB, macOS 26), with a stable 60 FPS in two reference scenes:
  - **outdoor hub:** the large forest area right after the opening;
  - **starting house:** the small interior the save starts in.
- **Hardware used for every number here:** MacBook Pro, Apple M1 Pro (16-core GPU), 32 GB, macOS 26.
- **Working rules followed:**
  - one emulator process at a time (check `pgrep -x dmhost` before launching);
  - builds run under `nice -n 10`;
  - at least 6 GB of free disk at all times (the build's watchdog stops it below 4 GB);
  - official upstream fixes take priority over local workarounds and over other forks.

## 2. Branches in this fork

| Branch | Base | What it is | State |
|---|---|---|---|
| `main` | upstream `seedds/nxnative` | untouched upstream | reference |
| `m1-perf` | kid-with-sword fork (`cheemu21/kid-with-sword-remake`, d1d672ac) + SDK guard | the fork's GPU work plus our M1 additions (14 commits) | **recommended**; built, see §7 for its route result |
| `m2-upstream` | upstream `main` (with 44 newer fixes) + all local work + the fork's GPU gains (4 commits) | the "everything" branch | built; **GPU fault in the starting house / its exit**, see §6 |

Why two branches: the kid-with-sword fork is based on an older upstream `main` and carries its own
versions of several fixes that upstream later merged differently. Merging current upstream `main`
into the fork produced 46 conflicts (including the shader translator DLLs and the chain lock), so the
work was done in both directions:

- `m1-perf`: our additions ported onto the fork (small, clean, no shader chain change);
- `m2-upstream`: the fork's gains ported onto upstream + our work (4 commits; see §5).

`m2-upstream` reproduces a GPU page fault / GPU hang that the fork never showed (§6). Until that is
found, `m1-perf` is the branch to play and measure on.

## 3. Measurements (outdoor hub, same spot, median of 500 frames)

| Metric | Our branch (upstream-based, before the fork port) | kid-with-sword fork | Reading |
|---|---|---|---|
| Frame time | 39.7 ms | **31.4 ms** | −21% |
| GPU time | 46.8 ms | **34.0 ms** | −27%: the fork's win is on the GPU |
| Render passes per frame | 101 | 110 | similar |
| Draw calls | 1,090 | 1,737 | the fork draws more (no reflection-probe throttle) and is still faster |
| Attachment load / store | 77.7 / 117.1 MB | 113.6 / 127.9 MB | the fork moves more tile memory |
| Submit CPU per frame | **5.4 ms** | 7.0 ms | ours is better (incremental pool tables, upstream PR #1489) |
| Startup pipeline prepare | **5.9 s** | 215–270 s | ours: 7 GB warmed archive, 1,050 bases; fork: 1.8 GB, 1,123 specializations compiled at start |
| Game time vs real time | 1.00 | 0.95 | the fork's frame step slows game time when frames run long |

## 4. What the kid-with-sword fork does better

In order of estimated impact:

1. **Compute dispatches side by side** (`21b7b681`, `DM_NVN_DISPATCH_OVERLAP`, profile key
   `dispatch_overlap on`). Game dispatches with no game barrier and nothing else between them run
   concurrently in the copy encoder instead of each waiting for the previous one. The fork's author
   measured 27.1 → 24.9 ms per frame on an M4 Pro; the start-of-frame burst (117 dispatches) goes
   from 5.7 to 2.6–3.7 ms. On an M1 Pro, with fewer GPU cores, the serialised burst costs more, so
   the gain should be larger.
2. **Indirect draw conversions survive unrelated writes** (`aa49ae03`). Conversions of indirect draws
   are kept across uniform updates and storage writes that do not touch their records; grass splits
   2 render passes a frame instead of 6. Upstream solved the same problem with its own `mdx_run`
   path (multi-draw indirect copies with a look-ahead that stops only at uniform updates hitting a
   record) plus our `DM_NVN_MDX_SAFE`, so this commit does not apply on `m2-upstream`.
3. **A depth-writing pool draw is not a depth reader** (`479526c7`). A draw through a texture pool
   that writes depth itself cannot sample the depth attachment (that would be a feedback loop), so
   it no longer ends the render pass; about 70 passes a frame stay open. On Apple GPUs every ended
   pass stores and reloads tile memory, so this matters more on M1.
4. **Retired pool tables reused** (`a3844dc6`): fewer residency-set changes per frame. Upstream has
   an equivalent (`pool_table_take` / `pool_table_give`).
5. **Frame step through the game's frame-rate controller** (`2de238f3`, `fps_target 60`): the host
   picks the vsync interval and the game runs its own 60 or 30 fps mode accordingly, so frames are
   held in whole vsyncs instead of drifting. Side effect on its own: game time at 0.95 of real time.
6. **Stability and memory:**
   - `mem_map_limit on` (`c774d51b`): map requests past the application pool fail as on hardware;
     without it, crashes are reported when entering some larger areas (upstream has it on too);
   - MetalFX black-world fix at the game's native resolution (`c2218343`);
   - console-mode resolution (720p handheld / 1080p docked) through a RomFS overlay
     (`26a2646e`, a resolution overlay script in `scripts/`; not generated by the standard build);
   - lossy compression on attachment-only colour targets (`rt_lossy`, about 100 MB less);
   - a larger alias region (`DM_ALIAS_SIZE=0x200000000`; upstream now defaults to 64 GB on Mac).
7. **No GPU faults observed:** 0 faults in 2 passes through the route, where every upstream-based
   build faulted (§6). The fork has no GPU watchdog, but it logs command-buffer errors the same way
   (`segment command buffer execution error`), so the 0 is real.

## 5. Our additions

### 5.1 On `m1-perf` (ported onto the fork)

| Commit | Change | Switch | Effect |
|---|---|---|---|
| 81c9e3f2 | Decoded NDVE movie frames scaled directly on Metal | — | movie frames without a CPU copy |
| c8a2fe89 | `DM_NVN_NDVE_MOVIE_DIRECT=2` also skips the NDVE network | `DM_NVN_NDVE_MOVIE_DIRECT` | title screen / movies 52 → 16.7 ms a frame (60 FPS) |
| 0aa740f3 | NDVE direct mode and `DM_UPSCALER` switchable mid-run through `DM_CTL` | `DM_CTL` `env` lines | live A/B without restarting |
| 5c93fca6 | MetalFX upscaler: the game's NDSR variants are gamma 2, squared after the scaler (includes `up_mfx_has_pow`) | `DM_UPSCALER=metalfx` | correct colours with MetalFX (no washed-out picture) |
| 8a02afd0 | Reflection-probe face drawn only every k-th visit per layer | `DM_NVN_PROBE_EVERY=<k>[:<size>]` | −5–6 ms GPU at k=4; also avoids the page fault after Continue on upstream-based builds |
| 8076baea | Compute dispatches ordered by the ranges they touch | `DM_NVN_CS_DEPS=1` | −4 ms on our base; combined with the fork's `dispatch_overlap` (`dispatch_enc(game, deps)`), CS_DEPS=1 overrides it |
| aff5d465 | GPU times the game measures are scaled | `DM_NVN_GPU_TS_SCALE=<f>` | dynamic-resolution quality knob: at 0.6 the starting house renders up to 1536x864 instead of the 683x384 floor for +5 ms |
| 359416cf | Screenshots of a cropped present capture the cropped picture | — | no black border in screenshots |
| fb85c62b | Task / mesh pipelines (M rows) prepared before the first frame and stored in the pipeline archive | `DM_PSO_MESH_PREWARM=0` turns it off | no mesh compile stalls in play (the starting house had them) |
| 75cb80f1 | Prewarm seed list `pso_manifest.tsv` (9,784 rows; the fork's 11 C rows already included) | — | first start prepares pipelines before the first frame |
| 5a1128bd, 24f63535, d8982eb8, 556cc799 | `DM_PRESET`: an M1-class preset in `dm/host/front_mac.m` | `DM_PRESET=auto\|m1\|off` | see §5.3 |

### 5.2 On `m2-upstream` (fork gains ported onto upstream + our work)

| Commit | Change | Notes |
|---|---|---|
| b3aa3230 | `dispatch_overlap` (from `21b7b681`) | combined with `DM_NVN_CS_DEPS` in one `dispatch_enc(game, deps)`; profile key `dispatch_overlap on` |
| 26c79d47 | depth-writing pool draw not a reader (from `479526c7`) | on top of upstream's `pool_ds_read` (182 → 101 passes): a pool draw counts as a depth reader only once read tracking saw the attachment read through a pool, and not while it writes depth itself; `t_feedback`'s `depth_self_case` uses dynamic tables |
| fb84230c | the fork's frame step and our real-time step in one `FRAME_STEP` entry | `frame_step` sets the controller's interval from the host's step; `real_speed` keeps the frame loop's step at max(interval, measured frame time), so game time stays at real time; `fps_target 60` |
| 93f81272 | preset: `DM_NVN_CS_DEPS` off | otherwise it replaces `dispatch_overlap` |

Fork commits deliberately **not** ported to `m2-upstream`, and why:

| Fork commit | Reason |
|---|---|
| aa49ae03 indirect conversions survive | upstream's `mdx_run` path + `DM_NVN_MDX_SAFE` already cover it |
| a3844dc6 retired pool tables reused | upstream has `pool_table_take` / `pool_table_give` |
| c774d51b `mem_map_limit` | already on upstream |
| c2218343 MetalFX black world | our `a974f2d4` (fallback when the NDSR chain goes past the replaced stage) fixes the same picture |
| 46975a20 wide GPU writes as intervals | its gain came from collisions in a 4,096-slot table; upstream moved to a 65,536-slot hash |
| 26a2646e console-mode resolution, `rt_lossy`, `upscaler_chain` | profile keys or RomFS overlay our build does not have; candidates for later |

`m2-upstream` also carries everything from the local upstream-based branch, including:

- indirect clamps and the GPU watchdog;
- loop caps for two library task shaders;
- the MetalFX path for the NDSR networks;
- the render-target placement heap (3 GB of render targets in 0.7 GB);
- texture-upgrade hardening;
- shader-code pools no longer resident (−334 MB);
- `DM_NVN_TS_BOUNDARY=interp`.

### 5.3 The M1 preset (`DM_PRESET`)

`dm/host/front_mac.m`, table `k_preset_m1`. With `DM_PRESET=auto` (default) it applies to the target
game on an Apple7-family GPU (M1). With `m1` it applies on any GPU; with `off` it does nothing.
Variables already set in the environment are kept. The log line `GPU preset m1 (...)` lists what was
set.

| Variable | Value | On | Why |
|---|---|---|---|
| `DM_NVN_NDVE_MOVIE_DIRECT` | 2 | yes | skips the NDVE network: title and movies at 60 FPS |
| `DM_NVN_PROBE_EVERY` | 4 | yes | −5–6 ms GPU |
| `DM_NVN_CS_DEPS` | 1 | **no** | would replace the fork's `dispatch_overlap`; A/B pending |
| `DM_UPSCALER` | metalfx | yes | MetalFX spatial instead of the NDSR network (whose HMMA chains streak on M1), gamma-2 fix |
| `DM_NVN_GPU_TS_SCALE` | 0.6 | yes | higher dynamic resolution indoors for +5 ms; no cost outdoors |
| `DM_NVN_TS_BOUNDARY` | interp | no (`m2-upstream` only) | hang candidate, A/B pending |

## 6. Open issue: GPU fault on upstream-based builds

**Symptom:** a GPU address fault (`kIOGPUCommandBufferCallbackErrorPageFault`) or a GPU hang
(`kIOGPUCommandBufferCallbackErrorHang`) in the starting house or while leaving it. The watchdog
(`DM_NVN_GPU_WATCHDOG`, on by default upstream) then stops the process with exit code 70. With the
watchdog off the game keeps running, with light flashes / overexposure afterwards.

**Runs** (route: starting house → door + cutscene → ladder → outdoor walk → outdoor still):

| Build / config | Result |
|---|---|
| `m2-upstream`, default | page fault, frame 1,209 (door) |
| `m2-upstream`, `DM_NVN_DISPATCH_OVERLAP=0` | GPU hang, frame ~1,815 (door cutscene) |
| `m2-upstream`, `DM_PRESET=off DM_UPSCALER=metalfx` | page fault, frame 954 (inside the house) |
| `m2-upstream`, `DM_NVN_POOL_HEAP=0 DM_NVN_UPGRADE_SAFE=0 DM_NVN_IND_CLAMP=0 DM_NVN_MDX_SAFE=0` | GPU hang, frame 3,441 (door cutscene) |
| previous local upstream-based branch, 5 runs (watchdog off) | 1–503 faults in every run |
| untouched older local mix branch | page fault ~1 min after Continue |
| kid-with-sword fork, 2 runs | **0 faults** |

**What is ruled out:**

- the four fork commits ported to `m2-upstream`;
- the M1 preset, including the reflection-probe throttle;
- the render-target placement heap;
- the texture-upgrade hardening;
- the indirect clamps;
- the indirect record lifetime (`MDX_SAFE`).

**What the logs show right before a fault:**

- texture upgrades ("texture upgraded to allow image writes", the NDSR upscaler's textures), but the
  fork does the same upgrades (60 in a clean run);
- "pool for handles traced to no slot: texture pool ... 44 have no storage (memory pool finalized or
  gone)";
- raw pool table activity: "raw pool table words at commit: 17670, of them 712 held an older table
  than the current one". The table itself does not overflow (4,118 of 8,191 entries).

**Prime suspects:** the code upstream has and the fork does not, in the bindless and raw-memory pool
table paths:

- the fork uses lunks' raw global memory pool table (`ef72f7c5`, from `574a38f0`);
- the fork patches bindless pool tables and keeps finalized descriptors out of the ghost ring
  (`ee9b7765`);
- upstream has its own incremental pool tables (PR #1489), raw-table words following the pools at
  commit (PR #1427), raw lookups starting from the last entry (PR #1464), and the PR #1360 host part.

**Next step:** a code bisect between the fork base and upstream. Each step is a build of about
10 minutes plus about 2 minutes of route.

1. Build upstream `main` + the target profile only, with no local work. If it faults, the cause is
   upstream.
2. If it faults, bisect upstream's 44 commits after the fork's base (`865cc35f..origin/main`). Start
   with:
   - `0c7e88b9` (incremental pool tables);
   - `339d9f23` (raw-table words at commit);
   - `0f510fd5` (raw lookup hint);
   - `c229bd7d` (texture IDs marked gone before the CPU-written classification);
   - `d4239a6e` (storage takeover lookup).
3. Alternatively, port `ef72f7c5` + `ee9b7765` from the fork onto `m2-upstream` and check whether
   the fault disappears.

`DM_NVN_HANGLOG=1` names the shaders of a hung segment; `DM_NVN_GMEM_MISSLOG=1` logs bound-buffer
addresses the raw table misses.

## 7. `m1-perf` result

Built at commit `556cc799` (+ the seen-shader list) into its own work folder: shader chain identical
to the fork's, 7,278 additional shaders compiled from the seen list. The route result is recorded
here when available; see the commit that adds it.

## 8. Building

Requirements:

- macOS 26 SDK. The MTL4FX temporal-scaler offset properties need the macOS 27 SDK and are guarded
  in `dm/gfx/nvn/nvn_mtl.m`.
- The project's Python venv and .NET (`DOTNET_ROOT=/opt/homebrew/opt/dotnet/libexec`).
- ~25 GB for the extracted game plus the work folder.

```bash
python scripts/build_ipa_from_nsp.py <game.nup> --platform mac --work-dir <work-dir> \
  --allow-other-metal --seen-shaders --progress lines -l en-US
```

The build's steps:

1. unpack;
2. NSO rewrite;
3. shader split;
4. Mac shaders: with `--seen-shaders`, a partial library from `dm/games/<title-id>/shader_seen.tsv`;
5. Mac host (`tools/dmhost`);
6. pipeline prebuild into the Metal 4 pipeline archive.

The work folder is kept between builds, and shaders come from its cache when the shader chain (the
`b-<chain>` folder) is unchanged.

Pitfalls met:

- **`--seen-shaders` needs `dm/games/<title-id>/shader_seen.tsv`.** It is tracked upstream; on the
  fork base it is committed on `m1-perf`.
- **RomFS image reuse is stamped.** The stamp is `.inputs.json`, holding the source digest
  (`romfs_image.py` + `pack_nup.py` + TOC SHA + version) and the file identity. A clone of the image
  gets a new identity, and a branch with an older packer has a different digest; either one makes the
  build repack 20+ GB. Restamp the existing image instead: check the digest the image was made with,
  then rewrite only `.inputs.json`.
- **The build watchdog** stops the build when `RomFS.img.part` appears (an unwanted repack) or when
  free disk falls below 4 GB.
- **A new pipeline archive is slow to start:** the first start on a fresh archive prepares for about
  4 minutes. Route scripts must wait for the prepare before sending input.

## 9. Running and measuring

```bash
cd <work-dir>/run && DM_ROOT=<work-dir> DM_ROMFS=<work-dir>/extract/<version>/RomFS.img \
  DM_SAVE=<work-dir>/run/save DM_WINDOW=1 DM_AUDIO=1 ../tools/dmhost
```

Useful variables:

- `DM_WINDOW=1`: a window; `DM_METAL_HUD=1`: the Metal HUD; `DM_AUDIO=1`: sound.
- `DM_NVN_TSV=<file>`: per-frame metrics. Lines are `frame<TAB>@name<TAB>value`, with names such as:
  - `@t_s`, `@gpu_ms`, `@work_ms`, `@sub_cpu_ms`;
  - `@passes`, `@rt_load_mb`, `@rt_store_mb`, `@pso_new`.
- `DM_CTL=<file>`: a control file the running host reads. Each appended line is one command:
  - a button (`A`, `B`);
  - a stick with a duration (`LDown~1.9`, `LUp~8`);
  - `shot <png>` for a screenshot;
  - `env VAR=value` for a live A/B.
- `DM_KEYS_ROUTE`: scripted buttons by frame number, for example `f510:A,f630:A,f750:A*12/20`.
- `DM_HITCH_DUMP`, `DM_PSO_WAITLOG=1`: hitch and pipeline-wait diagnostics.
- `DM_NVN_GPU_WATCHDOG=0`: keep running after a GPU fault (upstream-based branches only).

Measurement route used for every number:

1. load a save in the starting house and wait until submit CPU settles (pipeline prepare done);
2. stay 25 s in the house;
3. leave by the door and skip the cutscene with A every 3 s;
4. climb down the ladder;
5. walk outdoors for ~25 s;
6. stand still outdoors for 60 s.

Medians come from `frames.tsv` per phase. Check for faults with:

```bash
grep -c 'command buffer execution error' host.log
```

Process tips:

- Match the emulator with `pgrep -x dmhost`. A pattern with `-f` also matches the monitoring
  script's own command line.
- Only one emulator at a time: they share the GPU, and timings mix.

## 10. Environment switch reference (this work)

| Switch | Default | Meaning |
|---|---|---|
| `DM_PRESET` | auto | M1 preset (§5.3) |
| `DM_NVN_DISPATCH_OVERLAP` | profile (`on`) | game dispatches side by side |
| `DM_NVN_CS_DEPS` | 0 | range-tracked compute barriers; overrides overlap when 1 |
| `DM_NVN_PROBE_EVERY` | 1 | reflection-probe face every k-th visit |
| `DM_NVN_GPU_TS_SCALE` | 1.0 | scales the GPU times the game reads (dynamic resolution) |
| `DM_NVN_NDVE_MOVIE_DIRECT` | 0 | 1: direct Metal scaling of movie frames; 2: also skip the NDVE network |
| `DM_UPSCALER` | game | `metalfx`: MetalFX spatial instead of the game's NDSR upscaler |
| `DM_PSO_MESH_PREWARM` | 1 | prepare mesh pipelines before the first frame |
| `DM_NVN_TS_BOUNDARY` | off | `interp`: segment boundaries without GPU timestamp writes (`m2-upstream`) |
| `DM_NVN_FB_DSELF` | 1 | depth-writing pool draw is not a reader (`m2-upstream`) |
| `DM_FRAME_DELTA` | 1 | real-time step from the measured frame time (`m2-upstream`) |
| `DM_NVN_GPU_WATCHDOG` | 1 | stop at the first faulting command buffer (upstream-based) |
| `DM_NVN_POOL_HEAP`, `DM_NVN_UPGRADE_SAFE`, `DM_NVN_IND_CLAMP`, `DM_NVN_MDX_SAFE` | 1 | upstream-based safety / memory switches (ruled out for the fault) |
| `DM_FPS_HOLD`, `DM_ALIAS_SIZE` | — | fork runs used `DM_FPS_HOLD=off DM_ALIAS_SIZE=0x200000000` |

## 11. Next steps, in order

1. Run `m1-perf` through the route 3 times (fault rate, frame time per phase), then compare with the
   plain fork.
2. A/B `DM_NVN_CS_DEPS=1` against `dispatch_overlap` on `m1-perf`.
3. Warm `m1-perf`'s pipeline archive (the startup prepare). The fork's archive compiles 1,123
   specializations at start; the prebuild with the seen list and the M rows should bring the start
   down toward 6 s.
4. Find the upstream fault (§6) so that `m2-upstream`, which has the lower submit CPU and the newer
   fixes, can become the main branch.
5. Consider porting from the fork into `m2-upstream`:
   - console-mode resolution (`26a2646e`): 720p is a large GPU saving on M1;
   - `rt_lossy`.
