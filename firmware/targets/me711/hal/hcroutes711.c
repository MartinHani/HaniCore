/* Cold board mapping, unchanged cavity contract; no state or port writes -
   except the TACHO output stage at the end of this file (2026-10-11). */
#include "hcfarbridge.h"      /* FIRST: FAR module reaching near code */
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hctrigger.h"
#include "hcatomic.h"
#include "hcdeadline711.h"
#include "hcdeadline_state.h"
#include "hchal.h"
#include "hchal_me711.h"
#define OP_NONE 0u
#define OP_P2 2u
#define OP_P7 7u
#define OP_P8 8u

/* Ordinary task HAL calls may release an output, but cannot create an ON
   without a pulse token. Routing work is deliberately outside CC25. */
unsigned int HC_COLD hc_hal_deadline_out(unsigned char base, unsigned int which, unsigned char on)
{
    unsigned char i, bits, r, physical = 0u;
    unsigned int routed = 0u;
    if (on || (base != HC_OUT_IGN1 && base != HC_OUT_INJ1)) return 0u;
    for (i = 0, bits = (unsigned char)which; bits; i++, bits >>= 1) {
        if (!(bits & 1u)) continue;
        r = hc_hal_actuator_route[(base == HC_OUT_IGN1 ? 0u : 8u) + i];
        if (!r) continue;
        physical |= r;
        routed |= (unsigned int)(1u << i);
    }
    return hc_hal_deadline_ports_f(base, routed, physical, 0u);
}
void HC_COLD hc_hal_port_of(unsigned char cav, unsigned char *port,
                        unsigned char *bitno)
{
    *port = OP_NONE; *bitno = 0u;
    switch (cav) {
    /* injectors - EV1..EV8, all on P7/P8 CAPCOM pins */
    case 96u:  *port = OP_P7; *bitno = 6u;  break;   /* EV1 P7.6/CC30 */
    case 97u:  *port = OP_P7; *bitno = 5u;  break;   /* EV2 P7.5/CC29 */
    case 88u:  *port = OP_P7; *bitno = 4u;  break;   /* EV3 P7.4/CC28 */
    case 89u:  *port = OP_P8; *bitno = 7u;  break;   /* EV4 P8.7/CC23 */
    case 112u: *port = OP_P8; *bitno = 6u;  break;   /* EV5 P8.6/CC22 */
    case 113u: *port = OP_P8; *bitno = 5u;  break;   /* EV6 P8.5/CC21 */
    case 24u:  *port = OP_P8; *bitno = 4u;  break;   /* EV7 P8.4/CC20 */
    case 19u:  *port = OP_P8; *bitno = 3u;  break;   /* EV8 P8.3/CC19 */
    /* ignition - ZUE1..ZUE8, all on P2 CC0..CC7 */
    case 102u: *port = OP_P2; *bitno = 0u;  break;   /* ZUE1 P2.0/CC0 */
    case 103u: *port = OP_P2; *bitno = 1u;  break;   /* ZUE2 P2.1/CC1 */
    case 94u:  *port = OP_P2; *bitno = 2u;  break;   /* ZUE3 P2.2/CC2 */
    case 95u:  *port = OP_P2; *bitno = 3u;  break;   /* ZUE4 P2.3/CC3 */
    case 110u: *port = OP_P2; *bitno = 4u;  break;   /* ZUE5 P2.4/CC4 */
    case 111u: *port = OP_P2; *bitno = 5u;  break;   /* ZUE6 P2.5/CC5 */
    case 8u:   *port = OP_P2; *bitno = 6u;  break;   /* ZUE7 P2.6/CC6 */
    /* ZUE8 IS ROUTABLE. P2.7 is CC7's pin and CC7 IS the serial RX
       drain tick - but in COMPARE MODE 0 (hcts.c: CCM1[15:12] = 0x4), which
       is interrupt-only: "The corresponding port pin CCxIO is not affected by
       compare events in this mode and can be used as general purpose IO
       pin" and "the port latch and pin remain unaffected in compare mode 0"
       [C167CR UM V3.1 15.x, c167cr_um_v3.1.txt]. The drain
       needs the TIMER MATCH, not the pin, so the earlier "an eighth coil
       would fight the K-line" was never true of this configuration. Cavity 7
       A_T_ZUE8 <- ZDG8_P27 through S8621 (CK110), the same chip that already
       drives ZUE7 on cavity 8 (the ME7.1.1 schematic p1). DO NOT move CC7 to compare
       mode 1 or 3 - those drive the pin, and then this route WOULD conflict. */
    case 7u:   *port = OP_P2; *bitno = 7u;  break;   /* ZUE8 P2.7/CC7 */
    case 65u:  *port = OP_P2; *bitno = 12u; break;   /* EKP fuel pump P2.12 */
    default: break;
    }
}

/* ============================================================ THE TACHO ==
 * Cavity 37 A_T_TN, the engine-speed output to the instrument cluster: main
 * CPU P2.13 -> CJ920 low side -> 37, pulled up to UBR on the board
 * (hctarget.h TGT_TACHO_*). Routed by pinTacho (only 37 binds).
 *
 * SOFTWARE-TOGGLED, THE WAY THE STOCK FIRMWARE DRIVES IT (2026-10-11).
 * The overnight version made CC13 compare mode 1 toggle the latch in
 * hardware; on the car the needle never moved, and the only proof was a
 * c167sim model of compare mode 1 written from the same assumption as the
 * code. This ECU's own 022906032BT never programs CC13: it initialises
 * P2.13 as an output (DP2 = 0x38FF at key-on) and writes it with BSET/BCLR
 * P2.13 (seg88:EF14 / F152 / F156) - plain bit writes. FR "Audi R4-5V T
 * 132kW ME7.1" TN 3.20: symmetrical low/high pulses, 4 cylinders low = high
 * = 90 deg crank, i.e. rpm x cylinders / 120 Hz; nothing output while the
 * speed is not valid.
 *
 * The 1 ms tick toggles the pin when T1 has run a half-period past the last
 * toggle and advances by exactly one half-period: the average frequency is
 * exact, a single edge is at most one tick late. The bit is written with
 * single-instruction BSET/BCLR (sbit) - the tick runs at ILVL 8 and the
 * coil executor (ILVL 11) writes P2 too; a C read-modify-write of the whole
 * port could lose a coil edge.
 *
 * TEST ('!N', hc_tacho_test()): with the engine stopped the pin runs at a
 * fixed rpm for TACHO_TEST_MS so the needle can be checked at the car with
 * no instrument. Released - latch inactive, then input (stage off, line at
 * UBR) - when not routed, outputs not live, no crank sync or below 400 rpm
 * and no test running; "OFF releases the pin" like every engine output. */
typedef struct {
    unsigned int  half;       /* T1 ticks between toggles; 0 = released */
    unsigned char on;         /* pin driven                             */
    unsigned char lvl;        /* the level last written                 */
    unsigned int  last;       /* T1 of the last toggle                  */
    unsigned int  test_ms;    /* rev-counter test: ms left              */
    unsigned int  test_rpm;
} hc_tacho_t;
#define TA (*(hc_tacho_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_TACHO))
typedef char hc_tacho_fits[(sizeof(hc_tacho_t) <= TGT_RAM_TACHO_LIMIT) ? 1 : -1];
sbit TACHO_PIN = P2 ^ TGT_TACHO_BIT;
sbit TACHO_DIR = DP2 ^ TGT_TACHO_BIT;
#define TACHO_TEST_MS   6000u
#define TACHO_MIN_RPM    400u

static void tacho_release(void)
{
#if TGT_TACHO_ACTIVE_HIGH
    TACHO_PIN = 0;                              /* inactive first */
#else
    TACHO_PIN = 1;
#endif
    TACHO_DIR = 0;                              /* then input     */
    TA.on = 0u;
    TA.half = 0u;
}

void HC_COLD hc_tacho_init(void)
{
    TA.test_ms = 0u;
    TA.test_rpm = 0u;
    tacho_release();
}

/* '!N': rpm / 100 in `rpm100` (0 = 3000 rpm); refused while the engine
   turns (the real signal owns the pin then). */
void HC_COLD hc_tacho_test(unsigned char rpm100)
{
    if (trg_rpm != 0u || trg_state != TRG_NO_SIGNAL) {
        return;
    }
    TA.test_rpm = (rpm100 == 0u) ? 3000u : (unsigned int)rpm100 * 100u;
    TA.test_ms = TACHO_TEST_MS;
}

void HC_COLD hc_tacho_service(void)
{
    unsigned int rpm = trg_rpm, cyl, half, q;
    unsigned char test = (unsigned char)(TA.test_ms != 0u && rpm == 0u);

    cyl = hc_cal_u8(CFG_CYLINDERS);
    if (test) {
        rpm = TA.test_rpm;
    }
    if (hc_cal_u8(CFG_U_PIN_TACHO) != TGT_TACHO_CAV || !hc_hal_outputs_live()
        || (!test && trg_state < TRG_SYNC_CRANK) || rpm < TACHO_MIN_RPM
        || cyl < 1u || cyl > 12u) {
        if (TA.on) tacho_release();
        return;
    }
    /* half-period in T1 ticks (1.25 MHz) = 37 500 000 / rpm x 2 / cylinders.
       37 500 000 / rpm fits 16 bits from 573 rpm; below that it saturates
       (a needle under 600 rpm is the cluster's business). */
    q = (rpm < 573u) ? 65000u
                     : (unsigned int)((unsigned long)37500000uL / (unsigned int)rpm);
    if (cyl < 2u) {
        half = (q > 32500u) ? 65000u : (unsigned int)(q << 1);
    } else {
        half = (unsigned int)(((unsigned long)q << 1) / (unsigned int)cyl);
    }
    if (!TA.on) {
        TA.last = T1;
        TA.lvl = 1u;
#if TGT_TACHO_ACTIVE_HIGH
        TACHO_PIN = 0;
#else
        TACHO_PIN = 1;
#endif
        TACHO_DIR = 1;                          /* then output    */
        TA.half = half;
        TA.on = 1u;
        return;
    }
    TA.half = half;                             /* one word store */
}

/* The 1 ms tick: toggle when a half-period has elapsed (ILVL 8). */
void HC_COLD hc_tacho_tick(void)
{
    unsigned int h;

    if (TA.test_ms != 0u) {
        TA.test_ms--;
    }
    if (!TA.on) {
        return;
    }
    h = TA.half;
    if (h == 0u || (unsigned int)((unsigned int)T1 - TA.last) < h) {
        return;
    }
    TA.last = (unsigned int)(TA.last + h);
    if ((unsigned int)((unsigned int)T1 - TA.last) >= h) {
        TA.last = (unsigned int)T1;             /* fell behind: resync */
    }
    if (TA.lvl) {
        TACHO_PIN = 0;
        TA.lvl = 0u;
    } else {
        TACHO_PIN = 1;
        TA.lvl = 1u;
    }
}

unsigned char HC_COLD hc_tacho_running(void)
{
    return TA.on;
}
