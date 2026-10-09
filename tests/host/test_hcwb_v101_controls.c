/* Replays independent audit failures; usable against task-start V100 hcwb.c. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "hcwb_model.h"
int main(int argc, char **argv)
{
    hcwb_t w;
    model_t m;
    unsigned long t;
    unsigned char left = 0u, saw = 0u;
    hcwb_init(&w); model_init(&m);
    if (argc > 1 && atoi(argv[1]) == 1) {
        m.heat_policy = HCWB_HEAT_OFF;
        for (t = 0ul; t < 210000ul; t += 10ul) {
            step(&w, &m);
            if (w.duty_x10 || w.valid) {
                puts("N1 reproduced: heater permission without a grant");
                return 1;
            }
        }
    } else {
        m.heat_policy = HCWB_HEAT_IGNITION;
        m.write_delay = 200u; m.ack_delay = 200u; m.adc_delay = 700u;
        for (t = 0ul; t < 12000ul; t += 10ul) {
            step(&w, &m);
            if (w.cal_st == HCWB_CAL_OK) left = 1u;
            if (left && m.sample_mode == HCWB_MODE_CAL) {
                saw = 1u;
                if (w.ri_x10 || w.duty_x10 || w.valid) {
                    puts("L1 reproduced: calibration sample reused as sensor Ri");
                    return 1;
                }
            }
        }
        assert(left && saw);
    }
    puts("PASS: V101 audit replay");
    return 0;
}
