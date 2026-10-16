"""Guided force-feedback tuner for the Thrustmaster T500RS (Windows).

Setup:   pip install pysdl2 pysdl2-dll numpy
Run:     python t500rs_ffb_tuner.py
Needs:   wheel on PC mode, Thrustmaster driver installed, no game running.
Safety:  all forces are short and capped; keep a light grip on the wheel
         unless a step says "hands off". Ctrl+C stops everything.
"""
import json
import statistics
import sys
import time
from ctypes import byref

import numpy as np
import sdl2

MAX_LEVEL = 32767
SAFE_CAP = 0.6  # never command more than 60% in automatic tests


def die(msg):
    print(msg)
    sys.exit(1)


def open_wheel():
    if sdl2.SDL_Init(sdl2.SDL_INIT_JOYSTICK | sdl2.SDL_INIT_HAPTIC) != 0:
        die("SDL init failed: %s" % sdl2.SDL_GetError().decode())
    pick = None
    for i in range(sdl2.SDL_NumJoysticks()):
        name = sdl2.SDL_JoystickNameForIndex(i).decode()
        print("  device %d: %s" % (i, name))
        if "T500" in name.upper() or "THRUSTMASTER" in name.upper():
            pick = i
            break
    if pick is None:
        die("No Thrustmaster device found. Check power, USB, PC-mode switch, driver.")
    joy = sdl2.SDL_JoystickOpen(pick)
    hap = sdl2.SDL_HapticOpenFromJoystick(joy)
    if not hap:
        die("Wheel has no force feedback via SDL: %s" % sdl2.SDL_GetError().decode())
    return joy, hap


def axis(joy):
    sdl2.SDL_JoystickUpdate()
    return sdl2.SDL_JoystickGetAxis(joy, 0) / 32768.0  # -1..1


def play(hap, effect, ms):
    eid = sdl2.SDL_HapticNewEffect(hap, byref(effect))
    if eid < 0:
        print("  (effect not supported: %s)" % sdl2.SDL_GetError().decode())
        return None
    sdl2.SDL_HapticRunEffect(hap, eid, 1)
    return eid


def stop(hap, eid=None):
    sdl2.SDL_HapticStopAll(hap)
    if eid is not None:
        sdl2.SDL_HapticDestroyEffect(hap, eid)


def constant(level, ms, sign=1):
    e = sdl2.SDL_HapticEffect()
    e.type = sdl2.SDL_HAPTIC_CONSTANT
    e.constant.type = sdl2.SDL_HAPTIC_CONSTANT
    e.constant.direction.type = sdl2.SDL_HAPTIC_CARTESIAN
    e.constant.direction.dir[0] = sign
    e.constant.length = ms
    e.constant.level = int(max(-MAX_LEVEL, min(MAX_LEVEL, level * sign)))
    return e


def condition(kind, strength, ms):
    e = sdl2.SDL_HapticEffect()
    e.type = kind
    e.condition.type = kind
    e.condition.direction.type = sdl2.SDL_HAPTIC_CARTESIAN
    e.condition.direction.dir[0] = 1
    e.condition.length = ms
    c = int(strength * MAX_LEVEL)
    e.condition.right_sat[0] = e.condition.left_sat[0] = 0xFFFF
    e.condition.right_coeff[0] = e.condition.left_coeff[0] = c
    return e


def sine(strength, hz, ms):
    e = sdl2.SDL_HapticEffect()
    e.type = sdl2.SDL_HAPTIC_SINE
    e.periodic.type = sdl2.SDL_HAPTIC_SINE
    e.periodic.direction.type = sdl2.SDL_HAPTIC_CARTESIAN
    e.periodic.direction.dir[0] = 1
    e.periodic.length = ms
    e.periodic.period = int(1000 / hz)
    e.periodic.magnitude = int(strength * MAX_LEVEL)
    return e


def ask_rating(question, labels="1=far too weak  3=right  5=far too strong"):
    while True:
        a = input("  %s\n  [%s] > " % (question, labels)).strip()
        if a in {"1", "2", "3", "4", "5"}:
            return int(a)


def ask_yn(question):
    return input("  %s [y/n] > " % question).strip().lower().startswith("y")


def sample(joy, secs, hz=200):
    out = []
    t0 = time.time()
    while time.time() - t0 < secs:
        out.append(axis(joy))
        time.sleep(1 / hz)
    return out


# ---------------------------------------------------------------- tests
def test_range(joy):
    print("\n[1/8] Range & center. Turn the wheel fully left, fully right, then let go.")
    input("  Press Enter, then do it over the next 6 seconds...")
    s = sample(joy, 6)
    time.sleep(1)
    rest = statistics.mean(sample(joy, 1))
    r = {"min": min(s), "max": max(s), "rest_center_offset": rest}
    print("  axis min %.3f  max %.3f  rest %.3f" % (r["min"], r["max"], rest))
    if abs(rest) > 0.02:
        print("  Note: center offset > 2%. Re-power the base so it re-centers.")
    return r


def test_deadzone(joy, hap):
    print("\n[2/8] Minimum force (dead spot). HANDS OFF the wheel.")
    input("  Press Enter...")
    base = axis(joy)
    found = None
    for pct in range(1, 41):
        eid = play(hap, constant(pct / 100 * MAX_LEVEL, 250), 250)
        if eid is None:
            break
        time.sleep(0.3)
        moved = abs(axis(joy) - base)
        stop(hap, eid)
        time.sleep(0.4)
        base = axis(joy)
        if moved > 0.01:
            found = pct
            break
    print("  wheel first moved at ~%s%% constant force" % found)
    return {"min_force_pct": found}


def test_latency(joy, hap):
    print("\n[3/8] Response latency. HANDS OFF.")
    input("  Press Enter...")
    lat = []
    for _ in range(5):
        start = axis(joy)
        eid = play(hap, constant(0.3 * MAX_LEVEL, 400), 400)
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 0.4:
            if abs(axis(joy) - start) > 0.005:
                lat.append((time.perf_counter() - t0) * 1000)
                break
        stop(hap, eid)
        time.sleep(0.8)
    res = statistics.mean(lat) if lat else None
    print("  mean latency %s ms over %d pulses" % (round(res, 1) if res else "n/a", len(lat)))
    return {"latency_ms": res}


def test_ladder(joy, hap, name, make, levels):
    ratings = {}
    for lv in levels:
        input("  Hold the wheel lightly. Enter to feel %s at %d%%..." % (name, int(lv * 100)))
        eid = play(hap, make(lv), 1800)
        time.sleep(1.9)
        stop(hap, eid)
        ratings[lv] = ask_rating("How did that feel?")
    best = min(ratings, key=lambda k: abs(ratings[k] - 3))
    return {"ratings": {str(k): v for k, v in ratings.items()}, "best_pct": int(best * 100)}


def test_spring(joy, hap):
    print("\n[4/8] Centering spring. Turn the wheel off-center by hand each time.")
    return test_ladder(joy, hap, "spring", lambda s: condition(sdl2.SDL_HAPTIC_SPRING, s, 1800),
                       [0.2, 0.4, 0.6])


def test_damper(joy, hap):
    print("\n[5/8] Damper (resistance to fast movement). Swing the wheel back and forth.")
    return test_ladder(joy, hap, "damper", lambda s: condition(sdl2.SDL_HAPTIC_DAMPER, s, 1800),
                       [0.1, 0.3, 0.5])


def test_clipping(joy, hap):
    print("\n[6/8] Strength steps & clipping. Hold the wheel lightly; it will pull left then right.")
    levels = [0.2, 0.35, 0.5, SAFE_CAP]
    felt = {}
    for lv in levels:
        for sign, side in ((1, "right"), (-1, "left")):
            input("  Enter to feel %d%% pulling %s..." % (int(lv * 100), side))
            eid = play(hap, constant(lv * MAX_LEVEL, 700, sign), 700)
            time.sleep(0.8)
            stop(hap, eid)
        felt[lv] = ask_rating("Strength at %d%%?" % int(lv * 100))
    same = ask_yn("Did the top two steps feel almost the same (strength plateau)?")
    return {"ratings": {str(k): v for k, v in felt.items()}, "plateau_at_top": same}


def test_vibration(joy, hap):
    print("\n[7/8] Detail / vibration (kerbs, road texture).")
    out = {}
    for hz in (15, 40):
        input("  Hold lightly. Enter for %d Hz vibration..." % hz)
        eid = play(hap, sine(0.3, hz, 1500), 1500)
        time.sleep(1.6)
        stop(hap, eid)
        out[str(hz)] = ask_rating("Crisp & clear?", "1=absent/muddy  3=ok  5=sharp & strong")
    # self-oscillation check under high spring, hands off
    input("  HANDS OFF. Enter to check for self-oscillation...")
    eid = play(hap, condition(sdl2.SDL_HAPTIC_SPRING, 0.8, 2500), 2500)
    time.sleep(0.5)
    s = sample(joy, 1.5)
    stop(hap, eid)
    out["oscillation_stdev"] = statistics.pstdev(s)
    print("  axis stdev under spring: %.4f (>0.01 means it is shaking)" % out["oscillation_stdev"])
    return out


def recenter(hap):
    eid = play(hap, condition(sdl2.SDL_HAPTIC_SPRING, 0.5, 1500), 1500)
    time.sleep(1.5)
    stop(hap, eid)
    time.sleep(0.3)


def run_pulse(joy, hap, level, sign, push_s=0.2, coast_s=1.5):
    """Constant-force push, then zero force; returns samples and when the push ended."""
    ts, xs = [], []
    push_end = push_s
    eid = play(hap, constant(level * MAX_LEVEL, int(push_s * 1000), sign), 0)
    t0 = time.perf_counter()
    nxt = 0.0
    while True:
        now = time.perf_counter() - t0
        if now > push_s + coast_s:
            break
        if now >= nxt:
            x = axis(joy)
            ts.append(now)
            xs.append(x)
            nxt = now + 0.001
            if abs(x) > 0.6 and now < push_end:  # nearing lock: cut force early
                sdl2.SDL_HapticStopAll(hap)
                push_end = now
    stop(hap, eid)
    return np.array(ts), np.array(xs), push_end


def fit_accel(t, x, push_end):
    m = t < push_end
    t, x = t[m], x[m]
    moved = np.nonzero(np.abs(x - x[0]) > 0.003)[0]
    if len(moved) == 0:
        return None
    i0 = max(moved[0] - 1, 0)
    if len(t) - i0 < 10:
        return None
    accel = abs(2 * np.polyfit(t[i0:], x[i0:], 2)[0])
    mean_speed = abs(x[-1] - x[i0]) / (t[-1] - t[i0])
    return accel, mean_speed


def coast_points(t, x, push_end):
    """(|velocity|, deceleration along motion) pairs while the wheel coasts freely."""
    m = t > push_end + 0.03
    t, x = t[m], x[m]
    if len(t) < 20:
        return []
    dt = 0.005
    g = np.arange(t[0], t[-1], dt)
    k = np.ones(5) / 5
    v = np.convolve(np.gradient(np.interp(g, t, x), dt), k, "same")
    a = np.convolve(np.gradient(v, dt), k, "same")
    keep = np.abs(v) > 0.05
    keep[:5] = keep[-5:] = False  # smoothing edge artifacts
    return list(zip(np.abs(v[keep]), (a * np.sign(v))[keep]))


def test_friction_model(joy, hap):
    """Identify belt friction, viscous drag and inertia from the wheel's rotation.

    Model: J * accel = F - Fc*sign(v) - b*v, all forces in % of max.
    Push phase gives accel vs F (slope 1/J, intercept -> Fc).
    Coast phase (F=0) gives decel vs speed (intercept -> Fc, slope -> b).
    Position is in axis units (-1..1 across the full rotation range).
    """
    print("\n[8/8] Friction & inertia from wheel rotation. HANDS OFF; the wheel swings briefly.")
    input("  Press Enter...")
    levels = [0.15, 0.25, 0.35]
    F, A, V, C = [], [], [], []
    for i, lv in enumerate(levels + levels):
        recenter(hap)
        t, x, push_end = run_pulse(joy, hap, lv, 1 if i % 2 == 0 else -1)
        p = fit_accel(t, x, push_end)
        if p:
            F.append(lv * 100)
            A.append(p[0])
            V.append(p[1])
        C += coast_points(t, x, push_end)
    recenter(hap)
    if len(set(F)) < 2:
        print("  Not enough clean pushes to fit a model.")
        return {"ok": False}
    A = np.array(A)
    b_over_J = None
    if len(C) >= 20:
        cv = np.array(C)
        m_, k_ = np.polyfit(cv[:, 0], cv[:, 1], 1)
        b_over_J = -m_
        A = A + b_over_J * np.array(V)  # add back drag lost during the push
    s, c = np.polyfit(F, A, 1)
    if s <= 0:
        print("  Fit failed (acceleration did not rise with force).")
        return {"ok": False}
    J = 1 / s
    res = {"ok": True, "inertia_pct_per_unit_s2": float(J), "friction_pct_push": float(-c / s)}
    if b_over_J is not None:
        res["friction_pct_coast"] = float(-k_ * J)
        res["viscous_pct_per_unit_s"] = float(b_over_J * J)
    for k, v in res.items():
        if k != "ok":
            print("  %-26s %.4f" % (k, v))
    return res


# ---------------------------------------------------------------- advice
def advise(r):
    tips = []
    d = r["deadzone"]["min_force_pct"]
    if d and d > 8:
        tips.append("Dead spot ~%d%%: set in-game minimum force / deadzone compensation to ~%d%%." % (d, d))
    elif d is None:
        tips.append("Wheel never moved under test forces: check PC mode, power, firmware.")
    sp = r["spring"]["best_pct"]
    tips.append("Centering spring in Control Panel: ~%d%% (turn to 0%% for sims that self-center)." % sp)
    tips.append("Damper in Control Panel: ~%d%%." % r["damper"]["best_pct"])
    cl = r["clipping"]
    tips.append("Overall strength: %s." % (
        "70-80% in panel; plateau at top steps suggests you are clipping, lower in-game gain"
        if cl["plateau_at_top"] else "100% in panel, raise in-game gain until clipping appears"))
    if r["vibration"]["oscillation_stdev"] > 0.01:
        tips.append("Self-oscillation detected: lower damper/spring and in-game gain, check firmware.")
    if min(r["vibration"]["15"], r["vibration"]["40"]) <= 2:
        tips.append("Weak detail: raise Periodic effect strength and disable in-game smoothing.")
    lat = r["latency"]["latency_ms"]
    if lat and lat > 40:
        tips.append("Latency %.0f ms is high: use a direct USB port, close background apps." % lat)
    f = r["friction"]
    if f["ok"]:
        fc = f.get("friction_pct_coast", f["friction_pct_push"])
        tips.append("Belt friction ~%.1f%% force: start friction compensation at ~%.1f%% "
                    "(75%%, leaves stability margin)." % (fc, 0.75 * fc))
        if d:
            tips.append("Stiction (breakaway minus sliding friction): ~%.1f%%." % (d - fc))
        if "viscous_pct_per_unit_s" in f:
            tips.append("Viscous drag: %.3f %%/(axis unit/s); inertia: %.4f %%/(axis unit/s^2). "
                        "These feed the proxy's damping/inertia compensation." %
                        (f["viscous_pct_per_unit_s"], f["inertia_pct_per_unit_s2"]))
    return tips


def main():
    print("T500RS FFB tuner. Devices:")
    joy, hap = open_wheel()
    sdl2.SDL_HapticSetGain(hap, 100)
    results = {}
    try:
        results["range"] = test_range(joy)
        results["deadzone"] = test_deadzone(joy, hap)
        results["latency"] = test_latency(joy, hap)
        results["spring"] = test_spring(joy, hap)
        results["damper"] = test_damper(joy, hap)
        results["clipping"] = test_clipping(joy, hap)
        results["vibration"] = test_vibration(joy, hap)
        results["friction"] = test_friction_model(joy, hap)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sdl2.SDL_HapticStopAll(hap)
    if len(results) == 8:
        tips = advise(results)
        results["recommendations"] = tips
        print("\n=== Recommended settings ===")
        for t in tips:
            print(" -", t)
    with open("t500rs_ffb_report.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nSaved t500rs_ffb_report.json")


if __name__ == "__main__":
    main()
