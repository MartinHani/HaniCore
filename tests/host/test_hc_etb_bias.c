#include <assert.h>
#include <stdio.h>
#include "hc_etb_sweep.h"
#include "hc_etb_bias.h"
static hc_bias_t b;
/* Every position: closing edges at c, opening at o, three clean trials. */
static void fixture(void)
{
    unsigned int j,k;
    b.integral_after=0u; bias_begin(&b,4u);
    b.min_target=0u; b.max_target=1000u;
    for(j=0u;j<8u;j++) {
        b.axis[j]=j==0u?0u:j==7u?1000u:bias_positions[j-1u];
        b.current[j]=b.proposed[j]=1000u;
    }
    for(j=0u;j<BIAS_POINTS;j++) for(k=0u;k<FRIC_REPS;k++) {
        b.fj=(unsigned char)j;
        b.fe=0u; bias_edge(&b,40+(int)(10u*j)+(int)k);
        b.fe=1u; bias_edge(&b,200+(int)(10u*j)-(int)k);
    }
}
int main(void)
{
    unsigned int n;
    fixture(); assert(bias_propose(&b)==BIAS_READY);
    /* midpoint = (mean opening + mean closing)/2, width = their difference */
    assert(b.mid[0]==120 && b.width[0]==158 && b.spread[0]==2u);
    assert(b.proposed[0]==1000u && b.proposed[7]==1000u);       /* ends kept */
    assert(b.proposed[1]==1120u && b.proposed[6]==1170u);
    assert(b.qualified_samples==2u*FRIC_REPS*BIAS_POINTS);
    /* a fourth edge is never stored over the three trials */
    b.fj=0u; b.fe=0u; bias_edge(&b,999); assert(b.edge[0][0][2]==42);
    /* AN UNRELIABLE END IS TRIMMED, AN UNRELIABLE INTERIOR REFUSES. */
    fixture(); b.got[0][1]=2u;
    assert(bias_propose(&b)==BIAS_READY && b.excluded_reason==BIAS_SAMPLES
           && (b.excluded&1u) && b.valid_min==bias_positions[1]
           && b.proposed[1]==1000u && b.proposed[2]!=1000u);
    fixture(); b.got[2][0]=2u; assert(bias_propose(&b)==BIAS_SAMPLES);
    /* a non-repeatable edge refuses; the gate is FRIC_SPREAD_MAX exactly */
    fixture(); b.edge[3][1][1]+=FRIC_SPREAD_MAX-1; assert(bias_propose(&b)==BIAS_READY);
    fixture(); b.edge[3][1][1]+=FRIC_SPREAD_MAX; assert(bias_propose(&b)==BIAS_REPEAT);
    /* opening edge at/below closing edge is not a band */
    fixture(); b.edge[2][1][0]=b.edge[2][1][1]=b.edge[2][1][2]=45;
    assert(bias_propose(&b)==BIAS_HYSTERESIS);
    /* a trial failure recorded by the procedure excludes its position */
    fixture(); b.fail[3]=BIAS_SATURATION; assert(bias_propose(&b)==BIAS_SATURATION);
    fixture(); b.fail[5]=BIAS_DRIFT;
    assert(bias_propose(&b)==BIAS_READY && b.valid_max==bias_positions[4]
           && b.proposed[6]==1000u);
    /* a correction beyond 30 % of the current value is refused */
    fixture(); b.current[2]=1600u; assert(bias_propose(&b)==BIAS_UNSUPPORTED);
    /* the travel limits bound the measured range */
    fixture(); b.min_target=85u; b.got[0][0]=b.got[0][1]=0u;
    assert(bias_propose(&b)==BIAS_READY && b.proposed[1]==1000u);
    /* THE AXIS FOLLOWS THE MEASUREMENT. rusEFI's VAG curve (0/1/4/6/14/65/
       66/100 %) with the limp-detent position excluded: points land on the
       measured 10..80 %, unsupported points outside are kept, and the two
       whose removal changes the curve least (1 %, then 6 %) go. */
    fixture();
    {
        static const unsigned int ax[8]={0u,10u,40u,60u,140u,650u,660u,1000u};
        static const unsigned int cv[8]={850u,850u,900u,1000u,1080u,1090u,1150u,1170u};
        static const unsigned int wax[8]={0u,40u,100u,200u,400u,600u,800u,1000u};
        static const unsigned int wcv[8]={850u,900u,1130u,1140u,1150u,1160u,1170u,1170u};
        unsigned int k;
        for(k=0u;k<8u;k++) {b.axis[k]=ax[k]; b.current[k]=cv[k];}
        b.fail[0]=BIAS_REPEAT;
        assert(bias_propose(&b)==BIAS_READY && b.valid_min==100u);
        for(k=0u;k<8u;k++) assert(b.pax[k]==wax[k] && b.proposed[k]==wcv[k]);
    }
    /* fewer than eight points: the widest gap gets its interpolated middle */
    fixture();
    {
        static const unsigned int ax[8]={0u,150u,250u,300u,350u,450u,500u,1000u};
        for(n=0u;n<8u;n++) b.axis[n]=ax[n];
    }
    b.min_target=100u; b.max_target=600u;   /* 2 kept + 4 measured = 6 */
    assert(bias_propose(&b)==BIAS_READY && b.pax[0]==0u && b.pax[7]==1000u
           && b.pax[1]==100u && b.pax[2]==200u && b.pax[3]==300u
           && b.pax[4]==400u && b.pax[5]==600u && b.pax[6]==800u
           && b.proposed[3]==1145u && b.proposed[6]==1080u);
    for(n=1u;n<8u;n++) assert(b.pax[n]>b.pax[n-1u]);
    /* hold statistics: P/D transients and cached acquisitions add nothing */
    fixture();
    bias_hold(&b,1600u,2000u,7u,100u,100u,0,0,50);
    bias_hold(&b,1600u,2000u,7u,100u,100u,0,0,50);
    bias_hold(&b,1600u,2000u,8u,100u,100u,40,0,50);
    bias_hold(&b,1000u,2000u,9u,100u,100u,0,0,50);
    assert(b.samples==1u && b.integral_sum==50uL);
    puts("PASS friction band: midpoint/width, repeatability, partial range, refusal gates");
    return 0;
}
