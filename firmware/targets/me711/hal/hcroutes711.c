/* Cold board mapping, unchanged cavity contract; no state or port writes. */
#include <reg167.h>
#include "hctarget.h"
#include "hcdeadline711.h"
#include "hcdeadline_state.h"
#include "hchal.h"
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
