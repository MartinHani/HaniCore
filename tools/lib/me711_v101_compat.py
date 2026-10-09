"""Exact V101 identity + append-only V102 migration; no calibration retuning.

Offsets and default scalar values are read from the firmware contract. A
linked migration proof compares every output byte against this restoration
path. Generic older layouts continue through field-by-field migration.
"""
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SHARED=ROOT/'firmware'
GEN=(SHARED / 'generated/hc_config_generated.h').read_text()
MANAGER=(SHARED / 'config/hc_config_manager.c').read_text()
def value(name):
    return int(re.search(r'#define\s+'+name+r'\s+(0x[0-9A-Fa-f]+|\d+)',GEN).group(1),0)
OLD_SCHEMA=0x30d2
OLD_LAYOUT=0x332f8d11
SCHEMA=value('HC_UNIVERSAL_SCHEMA');LAYOUT=value('HC_CFG_LAYOUT_ID')
SCHEMA_OFF=value('CFG_U_SCHEMA');MAGIC_OFF=value('CFG_U_MAGIC')
def known_identity(layout,page):
    if len(page)!=4096 or int.from_bytes(page[MAGIC_OFF:MAGIC_OFF+2],'big')!=value('HC_UNIVERSAL_MAGIC'):return False
    schema=int.from_bytes(page[SCHEMA_OFF:SCHEMA_OFF+2],'big')
    return (layout,schema) in ((OLD_LAYOUT,OLD_SCHEMA),(LAYOUT,SCHEMA))
def migrate_v101(page):
    if not known_identity(OLD_LAYOUT,page):raise ValueError('not exact V101 schema/layout')
    p=bytearray(page);start=value('CFG_U_FUEL_MODEL');reference=value('CFG_U_PRESSURE_REF')
    p[start:reference]=bytes(reference-start)
    # V101 did not encode physical role. Legacy remains exact; commission
    # the new role explicitly (AWT cavity 101 is pre-throttle charge).
    p[value('CFG_U_PRESSURE_ROLE')]=0
    match=re.search(r'defaults\[13\]\s*=\s*\{([^}]+)\}',MANAGER)
    defaults=[int(n) for n in re.findall(r'(\d+)u',match.group(1))]
    assert len(defaults)==13
    for i,n in enumerate(defaults):p[reference+2*i:reference+2*i+2]=n.to_bytes(2,'big')
    # the throttle words appended after that block (hc_cfg_v102_defaults)
    p[value('CFG_U_DBW_PWM_HZ'):value('CFG_U_DBW_PWM_HZ')+2]=(2000).to_bytes(2,'big')
    p[value('CFG_U_DBW_FRICTION_X10'):value('CFG_U_DBW_FRICTION_X10')+2]=b'\0\0'
    p[SCHEMA_OFF:SCHEMA_OFF+2]=SCHEMA.to_bytes(2,'big')
    off=value('CFG_U_CRC');p[off:off+2]=b'\0\0'
    return bytes(p)
