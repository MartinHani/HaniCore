/*
 * hc_route.h - the physical pin router.
 *
 *      logical function  ->  configured physical ECU pin (1..121)
 *                        ->  target hardware descriptor
 *                        ->  HAL resource
 *
 * This is the layer the universal configuration was built for. The
 * configuration says "throttle track 1 is on connector pin 92". The descriptor
 * says what connector pin 92 is on THIS board and which of this CPU's ADC
 * channels, if any, can read it. The HAL says which channel it actually reads
 * for HC_AIN_TPS1. Those three have to agree, and until this file existed
 * nothing checked that they did.
 *
 * WHAT IT DOES NOT DO YET, DELIBERATELY.
 *
 * It does NOT rebind the HAL. hc_hal_ain() still reads the channel its own
 * PHYS[] table names, exactly as it did in V26 - the image whose battery,
 * ambient-pressure and throttle readings are the only analog behaviour this
 * ECU has actually demonstrated on hardware. Making the configuration
 * authoritative over that binding is a change that can silently move a live
 * sensor reading, and it is not one to make in the same image that introduces
 * the mechanism.
 *
 * So this router RESOLVES and REPORTS. hc_route_check() returns a bitmask of
 * every semantic channel whose configured pin disagrees with what the HAL
 * reads, which is
 *
 *   - a bench diagnostic: "you configured TPS1 on pin 84, the firmware reads
 *     AN1 which is pin 92" is a sentence nobody could get out of this ECU
 *     before;
 *   - the gate that has to be green before the binding is ever inverted.
 *
 * WHY THE DISAGREEMENT MASK IS NOT A FAULT. A fresh universal block routes
 * nothing - every pin field is HC_PIN_NONE - and that is the correct starting
 * state, not an error. Only a pin that IS configured and DOES disagree counts.
 */
#ifndef HC_ROUTE_H
#define HC_ROUTE_H

#include "hctarget.h"   /* HC_COLD: far on ME7.1.1 (FCODE), empty elsewhere */
#ifndef HC_COLD
#define HC_COLD
#endif

#include "hc_config_generated.h"
#include "hc_pin_descriptor.h"
#include "hchal.h"

/* The configured physical connector pin for a semantic analog channel, or
 * HC_PIN_NONE. Reads the ACTIVE configuration, because that is what the
 * runtime is using; the host's pending edits are not routing yet. */
unsigned char HC_COLD hc_route_ain_pin(unsigned char sem);

/* The ADC channel that the CONFIGURED pin implies on this board, or
 * HC_ADC_NONE when the pin is unrouted, does not exist, or is not readable by
 * this CPU's converter. */
unsigned char HC_COLD hc_route_ain_adc(unsigned char sem);

/* Bit `sem` set = that channel is configured to a pin, and the ADC channel
 * that pin implies is NOT the one hc_hal_ain() reads. Zero means every
 * configured analog route agrees with the firmware. */
unsigned int HC_COLD hc_route_check(void);

/* Bit `sem` set = that channel is routed to a real, readable pin. */
unsigned int HC_COLD hc_route_ain_routed_mask(void);

/* 1 when the pin can carry the capability the function needs, on this board,
 * per the linked descriptor. The router never invents a capability: a pin the
 * descriptor does not describe answers 0. */
unsigned char HC_COLD hc_route_pin_ok(unsigned char pin, unsigned int need);

/* Recompute the two diagnostics above IF the active configuration has moved
   since the last call, and cache them. Cheap when nothing changed, which is
   almost always. Call it from the main loop; read the results with the two
   _cached accessors instead of calling the resolvers from a hot path. */
void HC_COLD hc_route_init(void); /* invalidate retained cache after HAL reset */
void HC_COLD hc_route_service(void);

unsigned int HC_COLD hc_route_check_cached(void);
unsigned int HC_COLD hc_route_routed_mask_cached(void);

#endif /* HC_ROUTE_H */
