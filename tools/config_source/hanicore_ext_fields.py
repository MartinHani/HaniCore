#!/usr/bin/env python3
"""
hanicore_ext_fields.py - the page EXTENSION's fields (offsets 4096.., hcconfig.h
CFG_EXT_BASE), added 2026-11-03 for the functions the Ignitron study suggested
(.scratch/ignitron-study/STUDY.md, local; the runtime is
firmware/targets/me711/control/hcxfn711.c).

Ignitron is a REFERENCE only: no text, map or value is copied from it. Every
default here is HaniCore's own choice; the source of each is in its note or
in hanicore_presets.py. A value of 0 switches a function OFF wherever that is
possible, so a page that never set these bytes behaves as before.

add(M) is called at the end of hanicore_config_def.py with that module, so the
Meta / NewField / enum names are the model's own.
"""
from __future__ import annotations


def add(M) -> None:
    X = M.EXTENSION
    del X[:]
    L, Z, G, Meta, NF = M.L, M.Z, M.G, M.Meta, M.NewField
    CE = M.ConfigEnum

    def f(slot, ctype, count, ts, label, cat, units="", scale=1.0, tr=0.0,
          lo=0, hi=255, enum=None, note="", crit=False, digits=None,
          group=None, policy=None, pin=False, pin_needs=0):
        if digits is None:
            digits = (2 if scale in (0.01, 0.02, 0.005) else
                      1 if scale in (0.1, 0.5, 0.25) else 0)
        X.append(NF("CFG_U_" + slot, ctype, count, Meta(
            "CFG_U_" + slot, ts, label, policy or L, group or G.GENERAL,
            units=units, scale=scale, translate=tr, digits=digits, lo=lo,
            hi=hi, enum=enum, category=cat, note=note, safety_critical=crit,
            is_pin=pin, pin_needs=pin_needs),
            "%s%s extension field" % (ctype, "[%d]" % count if count > 1 else "")))

    def temp(slot, count, ts, label, cat, note=""):
        f(slot, "u16", count, ts, label, cat, units="C", scale=0.1,
          tr=-1000.0, lo=9600, hi=11500, note=note, digits=1)

    pair_action = CE("EtbPairAction", [
        (0, "ETB_PAIR_REVLIM", "Limit rpm (throttle fault rpm)"),
        (1, "ETB_PAIR_CUT", "Cut fuel and spark"),
    ], "What a throttle-sensor pair fault does to the engine")
    adapt_mode = CE("KnockAdaptMode", [
        (0, "KADAPT_OFF", "Off"), (1, "KADAPT_LEARN", "Learn only"),
        (2, "KADAPT_APPLY", "Learn and apply"),
    ], "Knock adaptation")
    M.ALL_ENUMS.extend([pair_action, adapt_mode])
    onoff = M.ENUM_OFF_ON

    # ======================= 1. throttle safety ===========================
    S = "Throttle safety"
    f("ETB_DEVCUT_PCT", "u8", 1, "etbDevCutPct",
      "Plate off target: cut above", S, units="%", hi=100, crit=True,
      note="When the throttle plate stays further than this from where it "
           "was sent (pedal target vs measured) for the time below, fuel "
           "AND spark are cut until the engine stops. Independent of the "
           "throttle fault monitor. 0 = off.")
    f("ETB_DEVCUT_T", "u8", 1, "etbDevCutTime", "Plate off target: for",
      S, units="s", scale=0.01, lo=1, hi=255, crit=True)
    f("ETB_PAIR_ACTION", "u8", 1, "etbPairAction",
      "Throttle sensor pair fault", S, hi=1, enum=pair_action, crit=True,
      note="Limit rpm: fuel is cut above the throttle-fault rpm (the plate "
           "rests on its spring). Cut fuel and spark: the engine stops - the "
           "measured opening can no longer be trusted while the motor holds "
           "the plate.")
    f("TPS_EXP", "u8", 4, "tpsExpected",
      "Expected throttle sensor voltage", S, units="V", scale=0.02, crit=True,
      note="What this throttle body's sensors read: track 1 closed, track 1 "
           "open, track 2 closed, track 2 open. AutoCal refuses endpoints "
           "further than the tolerance from these. 0 = not known (no check).")
    f("TPS_EXP_TOL", "u8", 1, "tpsExpTol",
      "AutoCal endpoint tolerance", S, units="V", scale=0.02, crit=True,
      note="0 = no plausibility check.")

    # ============================ 2. idle =================================
    I = "Idle"
    f("IDLE_IGN_KI", "u8", 1, "idleIgnKi", "Idle spark: integral", I,
      units="deg/s/100rpm", scale=0.1,
      note="Ignition-first idle: the spark correction also integrates the "
           "rpm error, so it settles inside its window and the throttle is "
           "only stepped when the spark runs out of room. 0 = P only.")
    f("IDLE_IGN_FADE", "u8", 1, "idleIgnFade",
      "Idle spark: fade out after the pedal", I, units="s", scale=0.01,
      note="The idle spark correction is faded out over this time when the "
           "idle loop releases (pedal pressed), instead of being dropped at "
           "once. 0 = drop at once.")
    f("IDLE_CORR_THR", "u8", 1, "idleCorrThr",
      "Throttle corrector: spark window used", I, units="%", hi=100,
      note="When the idle spark correction stays beyond this share of its "
           "window, the throttle is stepped toward the side that gives the "
           "spark its room back. 0 = off.")
    f("IDLE_CORR_PER", "u8", 1, "idleCorrPeriod",
      "Throttle corrector: every", I, units="s", scale=0.01, lo=1)
    f("IDLE_CORR_STEP", "u8", 1, "idleCorrStep",
      "Throttle corrector: step", I, units="%", scale=0.01)
    f("IDLE_CORR_MAX", "u8", 1, "idleCorrMax",
      "Throttle corrector: at most", I, units="%", scale=0.1)
    f("IDLE_KICK_DROP", "u8", 3, "idleKickDrop",
      "Throttle kick: rpm below target", I, units="rpm", scale=10,
      note="One-shot throttle steps when the rpm falls this far below the "
           "idle target (three levels, rising). They are taken back once "
           "the rpm is the reset amount above the target. 0 = level off.")
    f("IDLE_KICK_STEP", "u8", 3, "idleKickStep", "Throttle kick: step",
      I, units="%", scale=0.1)
    f("IDLE_KICK_RESET", "u8", 1, "idleKickReset",
      "Throttle kick: taken back above target +", I, units="rpm", scale=10)
    f("IDLE_ADAPT_RATE", "u8", 1, "idleAdaptRate",
      "Idle adaptation: rate", I, units="%/s", scale=0.01,
      note="Learns the throttle the warm idle really needs (a leak, a dirty "
           "throttle) from the settled idle trim, separately with the A/C "
           "off and on, kept while the battery is connected; AutoCal ETB "
           "clears it. 0 = off.")
    f("IDLE_ADAPT_MAX", "u8", 1, "idleAdaptMax",
      "Idle adaptation: at most +/-", I, units="%", scale=0.1)
    temp("IDLE_ADAPT_CLT", 1, "idleAdaptClt", "Idle adaptation: above", I)
    f("STALL_RPM", "u8", 1, "stallRpm", "Anti-stall: below target -",
      I, units="rpm", scale=10,
      note="Below the idle target minus this, extra throttle is added in "
           "proportion to the shortfall (also with the pedal pressed), "
           "before the engine stalls. 0 = off.")
    f("STALL_GAIN", "u8", 1, "stallGain", "Anti-stall: throttle per 100 rpm",
      I, units="%", scale=0.1)
    f("STALL_MAX", "u8", 1, "stallMax", "Anti-stall: at most", I,
      units="%", scale=0.1)
    f("MINADV_RPM_AX", "u8", 4, "minAdvRpmAx", "Minimum advance rpm", I,
      units="rpm", scale=50)
    f("MINADV_VAL", "u8", 4, "minAdvVal", "Minimum advance", I,
      units="deg", scale=0.5, tr=-20.0, hi=100,
      note="The final advance never goes below this curve while the idle "
           "loop or a deceleration retards it (backfire on the overrun). "
           "-20 deg everywhere = off. There is no vehicle-speed input on "
           "these ECUs yet, so the curve is over rpm.")

    # =========================== 3. starting ==============================
    T = "Starting"
    f("CRANK_HOLD", "u8", 1, "crankFuelHold",
      "Cranking fuel: full for", T, units="s", scale=0.1,
      note="The cranking fuel stays as the table says this long, then is "
           "reduced over the decay time to the floor below: a long crank "
           "stops adding fuel to a wet engine. 0 = no reduction.")
    f("CRANK_DECAY", "u8", 1, "crankFuelDecay",
      "Cranking fuel: then reduce over", T, units="s", scale=0.1)
    f("CRANK_FLOOR", "u8", 1, "crankFuelFloor",
      "Cranking fuel: down to", T, units="%", lo=10, hi=100)
    f("FIRST_REVS_ADD", "u8", 1, "firstRevsAdd",
      "First revolutions: extra fuel", T, units="%", hi=100,
      note="Added to the cranking fuel for the first revolutions after "
           "crank sync, while the manifold is still dry. 0 = off.")
    f("FIRST_REVS_N", "u8", 1, "firstRevsN", "First revolutions: count",
      T, hi=20)
    f("ASE_HOLD", "u8", 1, "aseHold", "After-start: hold for", T,
      units="s", scale=0.1,
      note="The after-start enrichment stays at its start value this long "
           "before it begins to decay.")
    f("WU_LAM_ON", "u8", 1, "wuLambdaEnable", "Warm-up lambda", T, hi=1,
      enum=onoff,
      note="On: while cold, the target lambda is the richer of the lambda "
           "table and this curve - a lambda instead of a percentage, so the "
           "closed loop holds it.")
    temp("WU_LAM_CLT", 6, "wuLambdaClt", "Warm-up lambda coolant", T)
    f("WU_LAM_VAL", "u8", 6, "wuLambdaVal", "Warm-up lambda", T,
      scale=0.005, tr=0.7, lo=0, hi=200, digits=3)
    f("OILSTART_KPA", "u8", 1, "oilStartKpa",
      "Start delay: oil pressure needed", T, units="kPa", scale=10,
      note="While cranking, no spark and no fuel until the oil pressure "
           "sensor reads this, or the time below has passed (skipped at "
           "once when the pressure is already there). Needs the oil "
           "pressure sensor. 0 = off.")
    f("OILSTART_MAX", "u8", 1, "oilStartMax", "Start delay: at most", T,
      units="s", scale=0.1)

    # ======================== 4. overrun and closed loop ==================
    D = "Overrun and closed loop"
    f("DFCO_CUT_T", "u8", 1, "dfcoCutTime", "Fuel cut: fade out over",
      D, units="s", scale=0.01,
      note="Fuel is reduced to zero over this time when the overrun cut "
           "begins (no jolt). 0 = at once.")
    f("DFCO_REST_T", "u8", 1, "dfcoRestoreTime",
      "Fuel cut end: fade in over", D, units="s", scale=0.01)
    f("DFCO_REST_ADD", "u8", 1, "dfcoRestoreAdd",
      "Fuel cut end: first fuel extra", D, units="%", hi=100,
      note="Extra fuel on the first injections after the cut ends (the "
           "port walls dried), decaying over the fade-in time.")
    f("O2SAT_LAM", "u8", 1, "o2SatLambda",
      "Sensor saturated after a cut above", D, scale=0.01, tr=1.0, hi=155,
      note="After an overrun fuel cut the sensor reads very lean for a "
           "while. Above this lambda (below the throttle below) it is "
           "saturated and the closed loop ignores it until it reads under "
           "the recovery lambda for the recovery time. 0 = off.")
    f("O2SAT_REC", "u8", 1, "o2SatRecLambda", "Recovered below", D,
      scale=0.01, tr=1.0, hi=155)
    f("O2SAT_T", "u8", 1, "o2SatRecTime", "Recovered for", D, units="s",
      scale=0.1)
    f("O2SAT_TPS", "u8", 1, "o2SatTps", "Only below throttle", D,
      units="%", hi=100)
    f("STFT_LEAN_LOCK", "u8", 1, "stftLeanLock",
      "Closed loop: no leaning for", D, units="s", scale=0.1,
      note="After the closed loop starts, it may add fuel but not remove "
           "it for this long - a sensor still settling never leans an "
           "engine. 0 = off.")
    f("STFT_KP", "u8", 4, "stftKp", "Closed loop P gain", D,
      units="%/%", scale=0.01,
      note="Idle / overrun / power / cruise: a proportional part on top of "
           "the integral (time constant) - percent of fuel per percent of "
           "lambda error. 0 = integral only.")

    # ============================= 5. knock ===============================
    K = "Knock"
    f("KAMP_ON", "u8", 1, "knockAmpEnable", "Retard by knock strength", K,
      hi=1, enum=onoff,
      note="On: the retard per knock comes from the map below (rpm x how "
           "far over the threshold the window was) instead of the fixed "
           "step.")
    f("KAMP_RPM_AX", "u8", 4, "knockAmpRpmAx", "Knock map rpm", K,
      units="rpm", scale=100)
    f("KAMP_AX", "u8", 4, "knockAmpAx", "Knock strength (x quiet reference)", K,
      scale=0.1, digits=1)
    f("KAMP_MAP", "u8", 16, "knockAmpMap", "Retard per knock", K,
      units="deg", scale=0.25, hi=40)
    f("KADAPT_MODE", "u8", 1, "knockAdaptMode", "Knock adaptation", K,
      hi=2, enum=adapt_mode,
      note="Learns a retard per rpm x load cell from knock that several "
           "cylinders share (fuel, heat - not one noisy cylinder) and "
           "applies it to all cylinders. Kept while the battery is "
           "connected; cleared with the trouble codes.")
    f("KADAPT_CYL", "u8", 1, "knockAdaptCyl",
      "Adaptation: cylinders retarding together", K, lo=1, hi=12)
    f("KADAPT_ATTACK", "u8", 1, "knockAdaptAttack",
      "Adaptation: learn share of the retard", K, units="%", hi=100)
    f("KADAPT_DECAY", "u8", 1, "knockAdaptDecay",
      "Adaptation: given back", K, units="deg/min", scale=0.1)
    f("KADAPT_MAX", "u8", 1, "knockAdaptMax", "Adaptation: at most", K,
      units="deg", scale=0.25)
    f("KADAPT_LOAD_AX", "u8", 4, "knockAdaptLoadAx",
      "Adaptation load (filling)", K, units="%", scale=2)

    # ============================= 6. boost ===============================
    B = "Boost"
    f("BI_RPM_AX", "u8", 6, "boostIRpmAx", "Boost integrator rpm", B,
      units="rpm", scale=100)
    f("BI_MIN", "u8", 6, "boostIMin", "Boost integrator minimum", B,
      units="%", hi=100,
      note="The closed-loop integrator's range, by rpm: the duty the "
           "integral may take away (minimum) and add (maximum). Both 0 at "
           "a point = the old fixed range there.")
    f("BI_MAX", "u8", 6, "boostIMax", "Boost integrator maximum", B,
      units="%", hi=100)
    temp("BLIM_IAT_AX", 4, "boostLimIatAx", "Boost limit intake air", B)
    f("BLIM_IAT", "u8", 4, "boostLimIat", "Boost limit by intake air", B,
      units="kPa", scale=2,
      note="Absolute boost target ceiling. 0 = no limit at that point.")
    temp("BLIM_CLT_AX", 4, "boostLimCltAx", "Boost limit coolant", B)
    f("BLIM_CLT", "u8", 4, "boostLimClt", "Boost limit by coolant", B,
      units="kPa", scale=2)

    # ========================= 7. limp mode ===============================
    P = "Limp mode"
    f("LIMP_ON", "u8", 1, "limpEnable", "Limp mode checks", P,
      note="Bits: 1 lean against target, 2 manifold pressure, 4 coolant, "
           "8 knock. Any check that trips puts the engine in limp mode "
           "until it stops: throttle limited, boost off, the reason kept "
           "in the trouble codes. 0 = off.", crit=True)
    f("LIMP_THR", "u8", 1, "limpThrottle", "Limp: throttle at most", P,
      units="%", hi=100, crit=True)
    f("LIMP_LEAN", "u8", 1, "limpLean", "Lean: richer target missed by",
      P, scale=0.01, crit=True)
    f("LIMP_LEAN_TPS", "u8", 1, "limpLeanTps", "Lean: above throttle", P,
      units="%", hi=100)
    f("LIMP_LEAN_T", "u8", 1, "limpLeanTime", "Lean: for", P, units="s",
      scale=0.1)
    f("LIMP_MAP", "u8", 1, "limpMap", "Manifold pressure above", P,
      units="kPa", scale=2, crit=True)
    f("LIMP_MAP_T", "u8", 1, "limpMapTime", "Pressure: for", P, units="s",
      scale=0.1)
    temp("LIMP_CLT", 1, "limpClt", "Coolant above", P)
    f("LIMP_KNOCK", "u8", 1, "limpKnock", "Knock retard above", P,
      units="deg", scale=0.25)
    f("LIMP_KNOCK_CYL", "u8", 1, "limpKnockCyl", "on cylinders", P,
      hi=12)
    f("DTC_LAMP", "u8", 4, "dtcNoLampMask", "No lamp for code", P,
      note="One bit per trouble code (the list order): set = that code is "
           "stored but does not light the lamp. 0 = every code as its "
           "class says.")
    f("DTC_OFF", "u8", 4, "dtcOffMask", "Code disabled", P,
      note="One bit per trouble code: set = the code is never stored.")

    # ===================== 8. throttle behaviour ==========================
    H = "Throttle"
    f("DBWG_AX", "u8", 4, "dbwGainAx", "Gain throttle position", H,
      units="%", hi=100)
    f("DBWG_PCT", "u8", 4, "dbwGainPct", "Gain at that position", H,
      units="%", hi=250,
      note="Scales the throttle PID's P and I by the plate position (a "
           "plate near the closed stop wants more). 0 everywhere = 100 %.")
    f("DBWS_AX", "u8", 4, "dbwSpeedAx", "Speed limit position", H,
      units="%", hi=100)
    f("DBWS_OPEN", "u8", 4, "dbwSpeedOpen", "Opening speed at most", H,
      units="%/10ms", scale=0.1,
      note="How far the throttle target may move in 10 ms at this "
           "position. Closing fast near the stop can break the plastic "
           "gears (spring + motor together). 0 = no limit.")
    f("DBWS_CLOSE", "u8", 4, "dbwSpeedClose", "Closing speed at most", H,
      units="%/10ms", scale=0.1)
    f("DBWO_RPM_AX", "u8", 4, "dbwOverrunRpmAx", "Overrun limit rpm", H,
      units="rpm", scale=100)
    f("DBWO_MAX", "u8", 4, "dbwOverrunMax",
      "Throttle at most with the pedal released", H, units="%", scale=0.1,
      note="Above idle, with the pedal released, the throttle (idle air, "
           "dashpot, kicks) is capped at this. 0 = no cap.")

    # ========================= 9. motorsport ==============================
    R = "Motorsport"
    f("TC_RATE", "u8", 1, "tcRpmRate", "Traction: rpm rise above", R,
      units="rpm/s", scale=100,
      note="There is no wheel-speed input on these ECUs, so wheelspin is "
           "judged by the engine speed rising faster than the car can "
           "accelerate it. Above this rate the cut / retard below act. "
           "Motorsport bit 4. 0 = off.")
    f("TC_RETARD", "u8", 1, "tcRetard", "Traction: retard", R,
      units="deg", hi=30)
    f("TC_CUT", "u8", 1, "tcCut", "Traction: spark cut", R, units="%",
      hi=90)
    # A shift light is a programmable output (I/O > Programmable outputs:
    # source rpm, threshold) - no second mechanism here.

    # ========================= 10. CAN bus (2026-11-03) ===================
    # .scratch/can-bus/spec.md (P1 + P2): the C167 CAN module, 500 kbit/s,
    # 11-bit, and the VAG drivetrain engine messages Motor_1/2/3/5 so a CAN
    # cluster shows rpm / coolant / MIL / EPC and the ABS / gearbox see an
    # engine ECU. Frames, bits, scales: .scratch/can-bus/VAG_PQ_MESSAGES.md
    # (FR CAN 51.570 + the OEM images). firmware/targets/me711/comms/hccan711.c.
    C = "CAN bus"
    can_mode = CE("CanVag", [
        (0, "CAN_VAG_OFF", "Off"),
        (1, "CAN_VAG_PQ34", "VAG PQ24-PQ34 (ME7)"),
    ], "Engine messages sent on the CAN bus")
    M.ALL_ENUMS.append(can_mode)
    f("CAN_ENABLE", "u8", 1, "canEnable", "CAN bus", C, enum=onoff,
      note="On: the CAN module runs at 500 kbit/s on pins 58 (L) / 60 (H) "
           "and acknowledges frames on the bus. Off: the module stays "
           "switched off and the ECU is silent on the bus. Takes effect "
           "after a key cycle.")
    f("CAN_VAG", "u8", 1, "canVag", "Engine messages", C, enum=can_mode,
      note="Send the VAG engine messages (Motor_1 rpm / torque / pedal, "
           "Motor_2 coolant / idle target / identity, Motor_3 intake air / "
           "throttle, Motor_5 MIL / EPC / fuel consumption) like the stock "
           "ME7. The cluster then shows rpm and coolant and the ABS / "
           "gearbox stop logging a missing engine ECU. Motor_6 carries the "
           "torque for an automatic gearbox. Takes effect after a key cycle.")
    f("CAN_VERS", "u8", 1, "canVers", "CAN version (CANVERS)", C, hi=31,
      note="The stock ECU's CAN version code, sent in Motor_2. 1.8T ME7.5: "
           "10 (= v4.0.2).")
    f("CAN_FMOTC", "u8", 1, "canEngineCode", "Engine code (FMOTC)", C,
      hi=63, note="Sent in Motor_2. 1.8T: 34 (4 cylinders transverse), 38 "
                  "longitudinal.")
    f("CAN_CWGC", "u8", 1, "canGearboxCode", "Gearbox code (CWGC)", C,
      hi=63, note="Sent in Motor_2. 15 = manual gearbox.")
    f("CAN_MOTTYP", "u8", 1, "canEngineType", "Engine type (MOTTYP)", C,
      note="Sent in Motor_5: bit 5 diesel, bit 4 naturally aspirated, bits "
           "0..3 cylinders. 1.8T turbo petrol: 4.")
    f("CAN_MDNORM", "u16", 1, "canTorqueNorm", "Torque normalisation "
      "(MDNORM)", C, units="Nm", hi=2000,
      note="100 % torque in the torque messages. 1.8T: 400 Nm. Above "
           "630 Nm the double-torque bit is set.")
    f("CAN_MDMAX", "u16", 1, "canTorqueMax", "Maximum torque", C,
      units="Nm", hi=2000,
      note="Sent in Motor_5 and the full-load torque in Motor_2. 1.8T "
           "(stock 24HGCM8g): 230 Nm.")
    f("CAN_NMDMAX", "u16", 1, "canTorqueMaxRpm", "Maximum torque at", C,
      units="rpm", hi=10000)
    f("CAN_KVNPZ", "u16", 1, "canConsumptionNorm", "Normalised "
      "consumption (KVNPZ)", C, hi=5000)
    f("CAN_FUEL_CORR", "u8", 1, "canFuelCorr", "Fuel consumption "
      "correction", C, units="%", hi=200,
      note="The consumption counter in Motor_5 (what the cluster shows) is "
           "the injected fuel times this. 0 = 100 %.")
    temp("CAN_HOT_CLT", 1, "canHotClt", "Coolant lamp above", C,
         note="Motor_5 overheat lamp bit above this coolant temperature. "
              "0 (shown as -100 C) = the lamp is never lit.")
    f("CAN_EPC_SRC", "u8", 1, "canEpcSource", "EPC lamp on", C,
      note="Bit 0: a throttle (DBW) fault. Bit 1: limp mode. 0 = never.")
    # ---- receiving (2026-11-03, VAG_PQ_MESSAGES.md section 3) ----
    vss_src = CE("CanVssSource", [
        (0, "CAN_VSS_NONE", "None"),
        (1, "CAN_VSS_ABS", "ABS vehicle speed (Bremse_1)"),
        (2, "CAN_VSS_FRONT", "Front wheels average (Bremse_3)"),
        (3, "CAN_VSS_REAR", "Rear wheels average (Bremse_3)"),
        (4, "CAN_VSS_CLUSTER", "Cluster speed (Kombi_1)"),
    ], "Where the vehicle speed comes from")
    M.ALL_ENUMS.append(vss_src)
    f("CAN_RX_MASK", "u8", 1, "canRxMask", "Receive", C,
      note="One bit per message: 1 Bremse_1 (ABS speed, brake, ESP off), 2 "
           "Bremse_3 (wheel speeds), 4 Getriebe_1 (gear, gearbox requests), "
           "8 Kombi_1 (cluster speed, fuel level), 16 Kombi_2 (oil and "
           "outside temperature), 32 Airbag_1 (crash), 64 Klima_1 (A/C). "
           "0 = receive nothing. Takes effect after a key cycle.")
    f("CAN_VSS_SRC", "u8", 1, "canVssSource", "Vehicle speed from", C,
      enum=vss_src,
      note="The vehicle speed HaniCore uses (and sends in Motor_2). Needs the "
           "message in Receive. A message older than the timeout reads as no "
           "speed.")
    f("CAN_RX_TMO", "u8", 1, "canRxTimeout", "Receive timeout", C,
      units="ms", scale=10, hi=255,
      note="A received value older than this is invalid (FR: 500 ms for "
           "most units). 0 = 500 ms.")
    # ---- custom frames for dashes / loggers (2026-11-03) ----
    f("CAN_CTX_ID", "u16", 2, "canCustomId", "Custom frame identifier", C,
      hi=2047,
      note="11-bit identifier of custom frame 1 / 2. 0 = frame off. Each "
           "frame carries four live values (any output channel, 16 bits "
           "each, as LibreTune shows them before scaling) - for an "
           "aftermarket dash or logger. Takes effect after a key cycle.")
    f("CAN_CTX_CH", "u16", 8, "canCustomCh", "Custom frame value (channel offset)", C,
      hi=65535,
      note="The live-data offset of each value: frame 1 values 1..4, then "
           "frame 2 values 1..4 (the offset is the channel's position in "
           "the output block, as the .ini lists the output channels). 65535 = 0.")
    f("CAN_CTX_RATE", "u8", 2, "canCustomRate", "Custom frame period", C,
      units="ms", scale=10, hi=255,
      note="How often frame 1 / 2 is sent. 0 = 100 ms.")
    f("CAN_CTX_LE", "u8", 1, "canCustomLittle", "Custom frames byte order", C,
      note="Bit 0 frame 1, bit 1 frame 2: 1 = little-endian (Intel), 0 = "
           "big-endian (Motorola).")
    f("CAN_CRASH_CUT", "u8", 1, "canCrashCut", "Airbag crash cuts the engine", C,
      enum=onoff, crit=True,
      note="On: an airbag crash message (Airbag_1, checksum checked, crash "
           "intensity 4 or more) cuts fuel and spark and switches the fuel "
           "pump off until the next key cycle - as the stock ME7. Needs "
           "Airbag_1 in Receive.")
    # ---- wideband over CAN, OBD-II over CAN (2026-11-04) ----
    wb_fmt = CE("CanWbFormat", [
        (0, "CAN_WB_OFF", "Off"),
        (1, "CAN_WB_RUSEFI", "rusEFI wideband (0x190)"),
        (2, "CAN_WB_AEM", "AEM X-series (0x180, 29-bit)"),
    ], "Wideband controller message format")
    M.ALL_ENUMS.append(wb_fmt)
    f("CAN_WB_FMT", "u8", 1, "canWbFormat", "Wideband controller on CAN", C,
      enum=wb_fmt,
      note="A wideband controller that sends lambda on the CAN bus. Lambda 1 "
           "and 2 read it when their source is 'External controller over "
           "CAN'. rusEFI format: 0x190 + 2 x index, lambda x 0.0001, valid "
           "byte. AEM X-series: 29-bit 0x180 + index. A value older than "
           "30 ms reads as no lambda. Takes effect after a key cycle.")
    f("CAN_WB_IDX", "u8", 1, "canWbIndex", "Wideband controller index", C,
      hi=14,
      note="The index of the controller that is lambda 1; lambda 2 is the "
           "next index.")
    f("CAN_OBD", "u8", 1, "canObd", "OBD-II over CAN", C, enum=onoff,
      note="Answer OBD-II requests (ISO 15765-4, 11-bit, 500 kbit/s: 0x7DF / "
           "0x7E0, replies on 0x7E8): mode 01 live data (rpm, speed, coolant, "
           "intake air, MAP, throttle, timing, load, lambda, battery), 03 / "
           "07 trouble codes, 04 clear (engine stopped), 09 calibration ID. "
           "For a scan tool or an OBD gauge. The car is NOT an emissions-"
           "certified OBD car with this. Takes effect after a key cycle.")
    # ---- ABS emulation + Haldex (race cars WITHOUT an ABS unit) ----
    f("CAN_ABS_EMU", "u8", 1, "canAbsEmu", "ABS emulation (no ABS fitted)", C,
      enum=onoff, crit=True,
      note="For a car with NO ABS / ESP unit: send Bremse_1 (vehicle speed) "
           "and Bremse_3 (four equal wheel speeds) every 10 ms from the "
           "vehicle speed input, so a CAN cluster shows speed and a Haldex "
           "or gearbox sees an ABS. Suspended (and reported) as soon as a "
           "real Bremse_1 is seen on the bus. Takes effect after a key cycle.")
    HX = "Haldex"
    hx_mode = CE("HaldexMode", [
        (0, "HX_OFF", "Off"),
        (1, "HX_EMU_CANCLUSTER", "Control by ABS emulation (CAN cluster)"),
        (2, "HX_EMU_NONCAN", "Control by ABS emulation (fixed rpm to the Haldex)"),
        (3, "HX_PASSIVE", "Passive: compute the lock only"),
    ], "Haldex clutch control")
    M.ALL_ENUMS.append(hx_mode)
    f("HX_MODE", "u8", 1, "haldexMode", "Haldex control", HX, enum=hx_mode,
      crit=True,
      note="Gen1 Haldex on a car WITHOUT an ABS unit. 1 / 2: the emulated "
           "rear wheel speeds are set below the front ones so the Haldex "
           "locks to the wanted %, closed loop on the lock it reports "
           "(Allrad_1). 2 also sends the Haldex a fixed rpm (more precise; "
           "a CAN cluster would show that rpm, so use 1 with a CAN cluster). "
           "3: only computes the wanted lock (for a logger / dash). Needs "
           "ABS emulation and the vehicle speed input; refused with a real "
           "ABS on the bus.")
    f("HX_TPS_AX", "u8", 4, "haldexTpsAx", "Lock: throttle", HX, units="%",
      hi=100)
    f("HX_TPS_LOCK", "u8", 4, "haldexTpsLock", "Lock: wanted at that throttle",
      HX, units="%", hi=100)
    f("HX_RPM_AX", "u8", 4, "haldexRpmAx", "Haldex rpm", HX, units="rpm",
      scale=100)
    f("HX_RPM_LIMIT", "u8", 4, "haldexRpmLimit", "Lock: at most at that rpm",
      HX, units="%", hi=100, note="0 = no limit at that rpm.")
    f("HX_NO_LOCK", "u8", 4, "haldexNoLock",
      "Rear slower by: 0 % lock at that rpm", HX, units="km/h", scale=0.1,
      note="The emulated rear-axle speed offset that leaves the clutch open "
           "(measure on the car).")
    f("HX_FULL_LOCK", "u8", 4, "haldexFullLock",
      "Rear slower by: 100 % lock at that rpm", HX, units="km/h", scale=0.1)
    f("HX_MAX", "u8", 1, "haldexMax", "Lock: at most", HX, units="%",
      hi=100, note="0 = 100 %.")
    f("HX_BRAKE", "u8", 1, "haldexBrakeOpen", "Open the clutch on the brake",
      HX, enum=onoff)
    f("HX_LAUNCH", "u8", 1, "haldexLaunch", "Lock during launch control", HX,
      units="%", hi=100, note="0 = the normal wanted lock.")
    f("HX_KP", "u8", 1, "haldexKp", "Closed loop P", HX,
      units="(km/h)/%", scale=0.01)
    f("HX_KI", "u8", 1, "haldexKi", "Closed loop I", HX,
      units="(km/h)/%s", scale=0.01)
    f("HX_DEADBAND", "u8", 1, "haldexDeadband", "Closed loop deadband", HX,
      units="%", hi=50)
    f("HX_RPM_FIX", "u8", 1, "haldexFixRpm", "Fixed rpm sent (mode 2)", HX,
      units="rpm", scale=100, note="0 = 2500 rpm.")

    # ========================= 11. vehicle speed + gears (2026-11-04) =====
    # the maintainer's design records (owner 2026-10-15: every
    # value a setting). firmware/sensors/hcvss.c + control/hcvss711.c.
    V = "Vehicle speed"
    vss_edge = CE("VssEdge", [
        (0, "VSS_FALLING", "Falling"),
        (1, "VSS_RISING", "Rising"),
    ], "Speed signal edge counted")
    M.ALL_ENUMS.append(vss_edge)
    f("VSS_PPK", "u16", 1, "vssPulsesPerKm", "Pulses per km", V, hi=65535,
      note="Pulses of the speed signal per km driven (the speed input, Road "
           "speed pin under Pins). VAG speed senders are often ~4300; check "
           "it against GPS: new = old x shown speed / true speed. Below 550 "
           "the input reads no speed.")
    f("VSS_EDGE", "u8", 1, "vssEdge", "Edge counted", V, enum=vss_edge,
      note="Takes effect after a key cycle.")
    f("VSS_FILTER", "u8", 1, "vssFilter", "Smoothing", V, hi=15,
      note="0 = none; each step moves (16 - this) / 16 of the way.")
    f("VSS_TMO", "u8", 1, "vssTimeout", "Standing after no pulse for", V,
      units="ms", scale=10, note="0 = 800 ms.")
    f("GEAR_N", "u8", 1, "gearCount", "Gears", V, hi=8,
      note="Number of forward gears. 0 = no gear detection.")
    f("GEAR_V", "u16", 8, "gearSpeed", "Speed per 1000 rpm", V,
      units="km/h", scale=0.01, hi=65000,
      note="Road speed at 1000 rpm in each gear, 1st first (it must rise "
           "gear by gear). Read it while driving steadily in that gear: the "
           "live value 'Speed per 1000 rpm'.")
    f("GEAR_BAND", "u8", 1, "gearBand", "Gear held within", V, units="%",
      hi=50, note="The detected gear is kept while the ratio stays within "
                  "this of its value. 0 = 10 %.")
    f("GEAR_MIN", "u8", 1, "gearMinSpeed", "No gear below", V, units="km/h",
      note="0 = 3 km/h.")
    # the first consumer: launch control only from (nearly) standing
    # (rusEFI launchSpeedThreshold, Speeduino lnchCtrlVss)
    f("LAUNCH_VMAX", "u8", 1, "launchMaxSpeed", "Launch: only below", V,
      units="km/h",
      note="Launch control acts only while the vehicle speed is at or below "
           "this (so a launch switch held while driving does nothing). 0 = no "
           "speed condition. Without a speed source the condition is met.")

    # LAYOUT: the 16-bit fields first (even offsets without pads), then the
    # bytes; the order inside each kind is the order above.
    wide = [x for x in X if x.ctype != "u8"]
    narrow = [x for x in X if x.ctype == "u8"]
    X[:] = wide + narrow
