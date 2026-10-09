"""C167 port reads and CJ220 polarity, independent of DBW software state.

C167CR UM 7.0: input bits read pins, output bits read latches. CJ220
truth table: disconnected IN1/IN2 read high; DI disconnected disables.
The stock simulator treats port registers as unconditional latch storage,
which hid input-bit corruption during whole-port read/modify/write.
"""
P2, DP2, P7, DP7 = 0xFFC0, 0xFFC2, 0xFFD0, 0xFFD2
PWMCON0, PWMCON1, PP2, PW2 = 0xFF30, 0xFF32, 0xF03C, 0xFE34
EN, IN1, IN2 = 0x0800, 0x0004, 0x0080

def attach(mem):
    original = mem.r8
    def read(a):
        address = a & 0xFFFFFF
        if address in (P2, P2+1, P7, P7+1):
            port = address & ~1
            direction, pulls = (DP2, EN) if port == P2 else (DP7, IN1 | IN2)
            latch = mem.sfr.get(port, 0)
            value = latch | (pulls & ~mem.sfr.get(direction, 0))
            return (value >> (8 * (address & 1))) & 255
        return original(a)
    mem.r8 = read

def state(mem):
    """Return signed motor duty (-1..1), DI state, and IN1/IN2 high fractions.

    Positive: OU1 high/OU2 low (117 positive relative to 118).
    Negative: the exact inverse. No torque when disabled or freewheeling.
    """
    regs = mem.sfr
    di = 'Z' if not regs.get(DP2, 0) & EN else ('H' if regs.get(P2, 0) & EN else 'L')
    dir_high = 1.0 if not regs.get(DP7, 0) & IN2 or regs.get(P7, 0) & IN2 else 0.0
    if not regs.get(DP7, 0) & IN1:
        pwm_high = 1.0
    else:
        pwm_high = float(bool(regs.get(P7, 0) & IN1))
        if regs.get(PWMCON1, 0) & IN1:
            if di == 'L':
                assert not regs.get(PWMCON1, 0) & 0x4040, 'PWM2 must use edge aligned independent mode'
                assert regs.get(PWMCON0, 0) & IN1, 'connected PWM2 must run'
            n = mem.r16(PP2) + 1
            high = max(0, min(n, n - mem.r16(PW2))) / n
            pwm_high = 1-high if pwm_high else high
    signed = pwm_high-dir_high if di == 'L' else 0.0
    return signed, di, pwm_high, dir_high
