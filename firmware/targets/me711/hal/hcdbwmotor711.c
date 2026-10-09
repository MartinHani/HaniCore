#include "hcfarbridge.h"
#include <reg167.h>
#include <intrins.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hchal.h"

/* The complete physical motor transaction. Every DBW owner uses this:
   !C4/!C5, AutoCal, tune/verify, normal PID and the legacy pulse bench.
   Disable first; establish push/pull outputs before touching their latches;
   program direction and PWM with DI inactive; enable LAST. A release bypasses
   every permission gate and disconnects/stops PWM before releasing all pins. */
sbit DBW_IN1 = P7 ^ TGT_DBW_PWM_PORT_BIT;
sbit DBW_IN2 = P7 ^ TGT_DBW_DIR_PORT_BIT;
void hc_hal_dbw_motor(unsigned char on, unsigned char dir, unsigned int duty)
{
    hc_hal_out(HC_OUT_THR_EN, 0u);
    PWMCON1 &= (unsigned int)~0x0004u;
    PWMCON0 &= (unsigned int)~0x0004u;
    if (!on || !hc_hal_out_class_live(HC_OUT_THR_EN)) {
        P7 &= (unsigned int)~0x0084u;
        DP7 &= (unsigned int)~0x0084u;
        return;
    }
    /* CC11/CC31 must not clock the DI/IN2 latches. Preserve all siblings. */
    CCM2 &= 0x0FFFu;
    CCM7 &= 0x0FFFu;
    ODP2 &= (unsigned int)~0x0800u;
    ODP7 &= (unsigned int)~0x0084u;
    DP7 |= 0x0084u;
    _nop_();
    DBW_IN1 = (unsigned char)(dir != 0u);
    DBW_IN2 = (unsigned char)(dir != 0u);
    /* PWM2: edge aligned, independent, fCPU clock; preserve other channels. */
    PWMCON1 &= (unsigned int)~0x4040u;
    PWMCON0 &= (unsigned int)~0x0040u;
    PT2 = 0u;
    hc_hal_out_duty(HC_OUT_THR_PWM, duty);
    hc_hal_out(HC_OUT_THR_EN, 1u);
}

