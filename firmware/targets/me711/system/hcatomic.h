#ifndef HCATOMIC_H
#define HCATOMIC_H
/* THE ONE CRITICAL-SECTION CONVENTION.
 *
 * Everything shared across interrupt levels that is wider than one 16-bit
 * word - a 32-bit timestamp or period, a queue link and its payload, two words
 * that must agree - is read and written inside HC_ATOMIC_ENTER/EXIT, which
 * raises the CPU priority to TGT_ILVL_CFG_CRIT (13): above every capture, the
 * planner (9), CC25 (11) and the tick (8); below the SSC/PEC levels 14/15, so
 * the S5500 exchange is never stopped (IEN is NEVER cleared for this - see
 * the maintainer's design notes). The two NOPs let the new level take effect before the
 * protected access (C167CR UM: the PSW write's pipeline effect).
 *
 * A single word, or a byte, written by one context and read by another needs
 * no lock - the C167 moves it in one bus cycle. A read-modify-write of a word
 * from two contexts does (or two counters with one writer each, as the K-line
 * echo accounting does).
 *
 * The sections are kept to a few instructions: every one of them delays the
 * crank capture ISR, whose CC15 latch holds one tooth. tests/firmware/trigger/
 * me711_runtime_stress_proof.py bounds the longest one measured under load.
 * The ISR <-> task census is in the maintainer's design notes. */
#include <intrins.h>
#include "hctarget.h"

#define HC_ATOMIC_PSW  ((unsigned int)TGT_ILVL_CFG_CRIT << 12)
#define HC_ATOMIC_ENTER(s) do { (s) = (unsigned int)(PSW & 0xF000u);        \
        if ((s) < HC_ATOMIC_PSW) _bfld_(PSW, 0xF000u, HC_ATOMIC_PSW);      \
        _nop_(); _nop_(); } while (0)
#define HC_ATOMIC_EXIT(s) do {                                              \
        PSW = (unsigned int)((PSW & 0x0FFFu) | ((s) & 0xF000u)); } while (0)
/* A multi-word value copied as one snapshot. */
#define HC_ATOMIC_COPY(dst, src) do { unsigned int _hc_as;                  \
        HC_ATOMIC_ENTER(_hc_as); (dst) = (src); HC_ATOMIC_EXIT(_hc_as); } while (0)
#endif
