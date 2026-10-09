/*
 * hc_pin_descriptor.c - queries over whichever descriptor was linked.
 */
#include "hc_pin_descriptor.h"

const hc_pin_desc_t *HC_COLD hc_pin_desc(unsigned char pin)
{
    if (pin == 0u || pin > HC_PHYSICAL_PIN_COUNT) {
        return (const hc_pin_desc_t *)0;
    }
    return &hc_pin_table[pin - 1u];
}

static unsigned char can(const hc_pin_desc_t *d, unsigned int have,
                         unsigned int need)
{
    if (d == (const hc_pin_desc_t *)0) {
        return 0u;
    }
    if (!d->routable) {
        return 0u;              /* no resource on this board drives it */
    }
    if (need == 0u) {
        /* "does this pin exist, and does its circuit do anything at all". A
           ground or a screen answers no here, because it carries
           SPECIAL_LOCKED and no capability bit beside it. */
        return (unsigned char)(((have & ~HC_PINCAP_SPECIAL_LOCKED) != 0u)
                               ? 1u : 0u);
    }
    /* EVERY requested bit, not any of them. See the note in the header for
       why SPECIAL_LOCKED is not a veto. */
    return (unsigned char)(((have & need) == need) ? 1u : 0u);
}

unsigned char HC_COLD hc_pin_is_dedicated(unsigned char pin)
{
    const hc_pin_desc_t *d = hc_pin_desc(pin);
    if (d == (const hc_pin_desc_t *)0) {
        return 0u;
    }
    return (unsigned char)((d->caps & HC_PINCAP_SPECIAL_LOCKED) ? 1u : 0u);
}

unsigned char HC_COLD hc_pin_can(unsigned char pin, unsigned int need)
{
    const hc_pin_desc_t *d = hc_pin_desc(pin);
    return can(d, d ? d->caps : 0u, need);
}

unsigned char HC_COLD hc_pin_can_verified(unsigned char pin, unsigned int need)
{
    const hc_pin_desc_t *d = hc_pin_desc(pin);
    return can(d, d ? d->caps_verified : 0u, need);
}

unsigned char HC_COLD hc_pin_adc_channel(unsigned char pin)
{
    const hc_pin_desc_t *d = hc_pin_desc(pin);
    if (d == (const hc_pin_desc_t *)0) {
        return HC_ADC_NONE;
    }
    return d->adc_ch;
}
