"""Ocarina v131072's build-checked real-time speed."""
from nso_asm import ADRP, B


# Real-time speed. The frame loop (main+0x6e6be0) computes each frame's step as a constant over its target frame rate and never reads the clock: s1 is 60, or 30 in one mode of the game
# (the fcsel at main+0x6e6cc0), s0 the target, so one frame is one step however long it took and everything runs slowly below the target. Found by gunvalk (zortos293/Lichii PR #216).
# The stub keeps that division and takes the larger of it and s1 x the measured frame time (state +0x38, float seconds, hle_nvn.c): 0 there leaves the game's own step, and the step is
# never below it. It marks state +0x3c so the host measures only for a main that reads the value. x16, x17 and s0 are not read again before they are written after the site
def real_speed(ctx):
    here, emit = ctx.here, ctx.emit
    ctx.site(0x6e6cc4, '2818201e')
    start = here()
    emit(0x1e201828)                       # fdiv s8,s1,s0        the game's own step
    emit(ADRP(16, here(), ctx.state))
    for w in (0x52800031,   # mov w17,#1
              0xb9003e11,   # str w17,[x16,#0x3c]  this main reads the frame time
              0xbd403a00,   # ldr s0,[x16,#0x38]   seconds; 0 = at the target
              0x1e210800,   # fmul s0,s0,s1
              0x1e204908):  # fmax s8,s8,s0
        emit(w)
    emit(B(here(), 0x6e6cc8))
    ctx.put(0x6e6cc4, [B(0x6e6cc4, start)], 'frame step from the measured frame time, never below the game\'s own (state +0x38)')


# v131072 main: the frame step (patch_nso.py "Frame step in whole vsyncs"). The game has its own frame-rate controller (main+0x3b4ef60, called once a frame with x20 = its
# config): from the measured frame time it picks a vsync interval between config +0x0 and +0x4 (with hysteresis, +0x50 / +0x54), stores it at +0x48 and fps = 60 / interval
# at +0x58, then at main+0x3b4f074 (where its paths meet) calls main+0x3b4f160, which hands +0x58 to setFrameRate (main+0x4dc0f0), and the framework's setInterval
# (main+0x346c5c0) with +0x48, which sets the window's present interval (main+0xf49970) and the framework's fps (+0xfc = 60 / interval). So 30 fps (interval 2) is the game's
# own mode, with its game time stepping by the interval. The stub at main+0x3b4f074 replaces the interval and fps with the host's step (state page +0x20, 1 = 60 fps, 2 = 30) while
# a target fps is set (state +0x0, the launcher's Frame rate / DM_FPS_TARGET; 0 = the game's own choice), and counts the vsyncs stepped (+0x30) for the host's speed check
def frame_step(ctx):
    here, emit, fs_site, fs_put, FS_STATE_OFF = ctx.here, ctx.emit, ctx.site, ctx.put, ctx.state
    site = 0x3b4f074
    fs_site(site, 'e00314aa')   # mov x0,x20
    start = here(); emit(ADRP(16, here(), FS_STATE_OFF))
    for w in (0xb9400211,   # ldr w17,[x16]           target fps (float bits; 0 = off)
              0x34000151,   # cbz w17,orig (+10)
              0xb9402211,   # ldr w17,[x16,#0x20]     step in vsyncs
              0x34000111,   # cbz w17,orig (+8)       not decided yet
              0xb9004a91,   # str w17,[x20,#0x48]     the controller's interval
              0x52800789,   # mov w9,#60
              0x1ad10929,   # udiv w9,w9,w17
              0xb9005a89,   # str w9,[x20,#0x58]      its fps, which setFrameRate takes
              0xf9401a09,   # ldr x9,[x16,#0x30]
              0x8b314129,   # add x9,x9,w17,uxtw
              0xf9001a09,   # str x9,[x16,#0x30]      vsyncs stepped
              0xaa1403e0):  # orig: mov x0,x20
        emit(w)
    emit(B(here(), site + 4))
    fs_put(site, [B(site, start)], "frame step: the frame-rate controller's interval and fps follow the host's vsyncs (state page target fps; 0 = the game's own choice)")


# Both stubs on one main (the frame step from the kid-with-sword fork, 2de238f3; the real-time step ours). With a target fps the host's step sets the controller's interval, and the
# frame loop's step is the larger of interval and measured frame time, which is the interval unless a frame stayed on screen longer than its hold; without one, real_speed alone
def frame_step_real_speed(ctx):
    real_speed(ctx)
    frame_step(ctx)


FRAME_STEP = {'e0f3ccfaf50065ae4ea01eb5aeb13b1a': frame_step_real_speed}   # 1.1.1 (v131072), the main of v0 too

BINDING = [
    {'what': 'frame step from the measured frame time', 'now': 'build', 'goal': 'game', 'purpose': 'frame rate',
     'why': "this game's own frame loop; the frame-step state page is general",
     'blocked': 'frame-step stubs have no function-matched form yet'},
    {'what': "frame step: the frame-rate controller's interval and fps from the host", 'now': 'build', 'goal': 'game', 'purpose': 'frame rate',
     'why': "the game's own 30 fps mode (interval 2), chosen by the host's step so presentation and game time agree",
     'blocked': 'frame-step stubs have no function-matched form yet'},
]
