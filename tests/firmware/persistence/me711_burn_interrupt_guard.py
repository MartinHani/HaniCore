"""Execute linked V102 flash-window masks, including a missing-CC25 control.

This checks interrupt admission at the RAM writer boundary, not flash timing.
Supply the exact frozen bench binary that will be flashed.
"""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import c167sim as S

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('image',type=Path,nargs='?');ap.add_argument('-v',action='store_true');a=ap.parse_args()
    import me711_image as PI
    image=(a.image or PI.image()).read_bytes()
    call=image.index(bytes.fromhex('DA380060'))
    pattern=bytes.fromhex('D1A066BEBFFF66B0BFFF66B9BFFF')
    start=image.rfind(pattern, max(0,call-1024),call)
    assert start>=0,'linked T8/CC16/CC25 interrupt masks absent'
    assert image.find(bytes.fromhex('BF88'),start,call)>=0,'writer IEN boundary missing'
    for ic in (0xF160,0xF172):
        # Linked OR must restore only the saved enable bit after the writer.
        operand=ic.to_bytes(2,'little')
        assert bytes.fromhex('66F4400074F4')+operand in image[call:call+800]
    for initial in (0xF4,0xB4,0x74,0x34):
        m=S.Mem(image);c=S.CPU(m,0,0)
        m.w16(0xFE10,0xFC00);m.w16(0xFE12,0xF700);m.w16(0xFF10,0)
        for ic in (0xF160,0xF172,0xF17C):m.w16(ic,initial)
        c.csp,c.ip=(start+0x800000)>>16,start&0xFFFF
        for _ in range(4):c.step()
        for ic in (0xF160,0xF172):
            assert m.r16(ic)==(initial&~0x40),'mask damaged request/priority'
        m.w16(0xF172,m.r16(0xF172)|0x80);m.w16(0xFF10,0x0800)
        c.check_irq();assert not c.irq_taken,'CC25 fetched flash during writer window'
    # Execute the same generated sequence with CC25 masking removed.
    bad=bytearray(image);bad[start+10:start+14]=bytes.fromhex('CC00CC00')
    m=S.Mem(bad);c=S.CPU(m,0,0)
    m.w16(0xFE10,0xFC00);m.w16(0xFE12,0xF700);m.w16(0xFF10,0)
    m.w16(0xF172,0xF4);c.csp,c.ip=(start+0x800000)>>16,start&0xFFFF
    for _ in range(5):c.step()
    m.w16(0xFF10,0x0800);c.check_irq()
    assert c.irq_count.get(0x39)==1,'negative control did not expose unsafe vector fetch'
    print('PASS linked CC16/CC25 masks preserve IR/priority; pending CC25 blocked')
    print('PASS negative control: missing mask admits flash-backed vector 0x39')
    # 2026-10-07: every flash-backed handler the firmware enables, including
    # the planner level (CC26IC 0xF174) and the reply job (S0TBIC 0xF19C),
    # must be masked by the time the writer is called. Run the linked
    # sequence from the masks to the CALLS and look.
    # (CC7/8/9/15 are masked before `start`, the anchor above, and are
    # checked by the persistence forensics gates.)
    flash_backed = {0xF160: 'CC16', 0xF172: 'CC25', 0xF174: 'CC26 planner',
                    0xF19C: 'S0TB reply'}
    m=S.Mem(image);c=S.CPU(m,0,0)
    m.w16(0xFE10,0xFC00);m.w16(0xFE12,0xF700);m.w16(0xFF10,0)
    for ic in flash_backed: m.w16(ic,0xF4)
    c.csp,c.ip=(start+0x800000)>>16,start&0xFFFF
    for _ in range(400):
        if (c.csp<<16|c.ip)==call+0x800000: break
        c.step()
    open_=[n for ic,n in flash_backed.items() if m.r16(ic)&0x40]
    if '-v' in sys.argv: print({n: hex(m.r16(ic)) for ic, n in flash_backed.items()})
    damaged=[n for ic,n in flash_backed.items() if (m.r16(ic)&0xBF)!=0xB4]
    assert (c.csp<<16|c.ip)==call+0x800000,'did not reach the writer CALLS'
    assert not open_,'flash-backed handler(s) still enabled at the writer call: %s'%open_
    assert not damaged,'mask damaged request/priority: %s'%damaged
    print('PASS every flash-backed handler masked at the writer call: %s'
          % ', '.join(flash_backed.values()))
    return 0
if __name__=='__main__':raise SystemExit(main())
