#!/usr/bin/env python3
"""Append-only persistence contract proof over the actual ME7.1.1 image.

Replaces the retired A/B erase simulator.  The legal trace contains only NOR
PROGRAM writes; DONE's two words are necessarily the final trace targets.
"""
from __future__ import annotations
import binascii, importlib.util, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_image as PI          # one place names the image under test
IMG = PI.IMG
SRC = (ROOT / "firmware/targets/me711/nvm/hcnvm.c").read_text()
# GEOMETRY IS DERIVED, NEVER RESTATED - see tools/lib/me711_nvm_geometry.py for the
# incident that made this a rule.
from me711_nvm_geometry import GEO
CELL0, PAGE, CELLS = GEO.file_base, GEO.page, GEO.cells
OFF, BODY, PAYLOAD, REC_LEN = GEO.off, GEO.body, 4096, 4120
DONE = b"DONE"; CHECKS = FAILS = 0
spec=importlib.util.spec_from_file_location("build",ROOT/"tools/build/build_hanicore_me711.py")
build=importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(build)
def check(s, ok):
 global CHECKS,FAILS; CHECKS+=1; FAILS+=not ok; print(("PASS" if ok else "FAIL"),s)
def addr(i): return GEO.addr(i)
def crc(x): return binascii.crc_hqx(x,0xffff)
def record(payload,gen):
 r=bytearray(b"HCN1"+(0x12345678).to_bytes(4,"big")+(1).to_bytes(2,"big")+PAYLOAD.to_bytes(2,"big")+gen.to_bytes(4,"big")); r+=crc(r).to_bytes(2,"big")+payload+crc(payload).to_bytes(2,"big")+DONE; assert len(r)==REC_LEN; return bytes(r)
def blank(f,i): return all(x==0xff for x in f[addr(i):addr(i)+BODY])
def valid(f,i):
 r=f[addr(i):addr(i)+REC_LEN]
 return r[:4]==b"HCN1" and r[-4:]==DONE and int.from_bytes(r[16:18],"big")==crc(r[:16]) and int.from_bytes(r[-6:-4],"big")==crc(r[18:-6])
def active(f):
 a=[i for i in range(CELLS) if valid(f,i)]
 # signed 32-bit generation difference: later generation wins across wrap.
 return next((i for i in a if all(((int.from_bytes(f[addr(i)+12:addr(i)+16],"big")-int.from_bytes(f[addr(j)+12:addr(j)+16],"big"))&0xffffffff)<0x80000000 for j in a)),None)
def burn(f,payload,gen,cut=None):
 cur=active(f)
 if cur is not None and f[addr(cur)+18:addr(cur)+18+PAYLOAD]==payload:return "noop",[]
 target=next((i for i in range(CELLS) if blank(f,i)),None)
 if target is None:return "full",[]
 r,trace=record(payload,gen),[]
 for n in range(0,REC_LEN,2):
  trace.append(("PROGRAM",addr(target)+n))
  if cut is not None and len(trace)>cut:break
  f[addr(target)+n:addr(target)+n+2]=r[n:n+2]
 return "commit",trace
def safe(t): return all(op=="PROGRAM" and (a&0x1fff) not in (0,0x1ffe) for op,a in t)
def main():
 base=bytearray(IMG.read_bytes())
 # V53 SCOPED THIS. It used to assert no erase command appeared ANYWHERE in
 # hcnvm.c, which was right while the store was never erased and is wrong now
 # that it is reclaimed. The property that still matters is that the WRITER -
 # the routine that programs a record - contains none, and that is asked of the
 # writer's own body. me711_flash_busy_proof asks the complementary question of
 # the eraser, and does it against the linked image rather than the text.
 WBODY = SRC[SRC.index("void far hc_nvm_payload(void)"):SRC.index("void far hc_nvm_payload_end(void)")]
 check("no AMD erase command remains in the runtime WRITER",all(x not in WBODY for x in ("FL_ERASE","FL_SECTOR","CB_DOERASE")))
 check("and the eraser is a separate routine, not grown into the writer","void far hc_nvm_eraser(void)" in SRC and "FL_ERASE_SECTOR" in SRC)
 check("runtime selects cells and checks whole body blank",all(x in SRC for x in ("CELL_ADDR","cell_blank","HCNV_ERR_FULL")))
 f=bytearray(base); st,t=burn(f,b"A"*PAYLOAD,1)
 check("virgin first Burn is cell 0, valid only after DONE",st=="commit" and active(f)==0 and valid(f,0))
 check("virgin cells 1..15 remain byte-identical FF",all(blank(f,i) for i in range(1,CELLS)))
 check("first trace is program-only and leaves boot sum unchanged",safe(t) and build.program_page_sum(f)==build.program_page_sum(base))
 snaps=[bytes(f[addr(0):addr(0)+REC_LEN])]
 for i in range(1,CELLS):
  st,t=burn(f,bytes([0x41+i])*PAYLOAD,i+1)
  check("sequential Burn %02d selects cell %02d"%(i,i),st=="commit" and active(f)==i and safe(t))
  check("older records immutable after cell %02d"%i,all(bytes(f[addr(j):addr(j)+REC_LEN])==snaps[j] for j in range(i)))
  snaps.append(bytes(f[addr(i):addr(i)+REC_LEN]))
 before=bytes(f); st,t=burn(f,b"Z"*PAYLOAD,CELLS+1)
 check("full store returns clean refusal without trace",st=="full" and not t and bytes(f)==before and active(f)==CELLS-1)
 for cut in (0,1,8,500,2050,2058,2059,2060):
  x=bytearray(base);burn(x,b"O"*PAYLOAD,1); old=bytes(x[addr(0):addr(0)+REC_LEN]);st,t=burn(x,b"N"*PAYLOAD,2,cut)
  if cut == 0:
   check("cut before first word leaves target genuinely blank",active(x)==0 and blank(x,1) and bytes(x[addr(0):addr(0)+REC_LEN])==old)
   st,t=burn(x,b"N"*PAYLOAD,2);check("blank target may be selected after pre-program cut",st=="commit" and active(x)==1 and safe(t))
  elif cut == REC_LEN//2:
   check("complete DONE makes new record active",active(x)==1 and valid(x,1) and bytes(x[addr(0):addr(0)+REC_LEN])==old)
  else:
   check("cut %d rejects incomplete cell and preserves previous"%cut,active(x)==0 and not valid(x,1) and bytes(x[addr(0):addr(0)+REC_LEN])==old and not blank(x,1))
   st,t=burn(x,b"N"*PAYLOAD,2);check("cut %d never reuses partial cell"%cut,st=="commit" and active(x)==2 and safe(t))
 x=bytearray(base);burn(x,b"Q"*PAYLOAD,1);before=bytes(x);st,t=burn(x,b"Q"*PAYLOAD,2)
 check("no-op Burn has no program/reset trace and consumes no cell",st=="noop" and not t and bytes(x)==before and active(x)==0)
 for field in (0,4,16,100,REC_LEN-1):
  x=bytearray(base);burn(x,b"A"*PAYLOAD,1);burn(x,b"B"*PAYLOAD,2);x[addr(1)+field]^=1
  check("corruption at record offset %d rejects only newer cell"%field,active(x)==0)
 x=bytearray(base);burn(x,b"A"*PAYLOAD,0xffffffff);burn(x,b"B"*PAYLOAD,1)
 check("generation wrap makes 1 newer than FFFFFFFF",active(x)==1)
 bad=bytearray(base);bad[0x40000:0x40000+REC_LEN]=record(b"V"*PAYLOAD,1)
 check("negative V37 page+0 record changes boot sum",build.program_page_sum(bad)!=build.program_page_sum(base))
 bad=bytearray(base);bad[0x55ffe]=0xfb;bad[0x57ffe]=0xf7
 check("negative interrupted erase samples change boot sum",build.program_page_sum(bad)!=build.program_page_sum(base))
 check("negative erase bus trace is rejected",not safe([("ERASE",0x50000)]))
 print("%d/%d checks pass"%(CHECKS-FAILS,CHECKS));return int(bool(FAILS))
if __name__=="__main__":raise SystemExit(main())
