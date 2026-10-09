"""A retained route cache cannot bypass rebinding after HAL initialization."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools/lib"))
import hcpaths  # noqa: F401,E402
import me711_trigger_test as T  # noqa: E402
import me711_image as I  # noqa: E402


def trial(control=False):
    r = T.Call()
    if control:
        # Far RETS disables only cache invalidation in simulator memory.
        address = T.sym("hc_route_init") - 0x800000
        r.m.flash[address:address + 2] = bytes([0xDB, 0x00])
    r.call("hc_hal_init")
    r.call("hc_cal_set_u8", 2579, 92)  # configured TPS1 cavity: AN1
    r.call("hc_cal_set_u8", 2580, 84)  # configured TPS2 cavity: AN3
    r.call("hc_route_service")
    before = bytes(r.m.xram[0x7404:0x7406])
    revision = r.m.r16(T.sym("hc_cfg_active_rev"))
    r.call("hc_hal_init")
    cleared = bytes(r.m.xram[0x7404:0x7406])
    r.call("hc_route_service")
    after = bytes(r.m.xram[0x7404:0x7406])
    return (before == after == bytes([1, 3]) and cleared == bytes([255, 255])
            and r.m.r16(T.sym("hc_cfg_active_rev")) == revision), (before, cleared, after)


def main():
    print("image", I.sha256())
    ok, state = trial()
    negative, control = trial(True)
    print("[%s] unchanged revision still rebinds TPS after HAL reset: %s" % ("PASS" if ok else "FAIL", state))
    print("[%s] removing invalidation reproduces missing bindings: %s" % ("PASS" if not negative else "FAIL", control))
    return 0 if ok and not negative else 1


if __name__ == "__main__":
    raise SystemExit(main())
