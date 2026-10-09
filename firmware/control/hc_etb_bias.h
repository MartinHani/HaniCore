/* ETB feed-forward from the FRICTION BAND, not from a held duty.
 *
 * WHY: on the VAG body the duty that holds a position is not a function of
 * position. Its gear train has a wide Coulomb friction band; anywhere inside
 * it the plate is in equilibrium, so a settled PID freezes at an arbitrary
 * point in the band (run-to-run median 11 %, worst 28.9 % duty at the same
 * position and direction). The band
 * EDGES are sharp, repeatable events: at each position the closed loop
 * settles, the loop is opened at the command that was holding, and the
 * command ramps (20 %/s) until the plate breaks away - once opening, once
 * closing, FRIC_REPS times each. Midpoint = friction-free feed-forward,
 * width = the friction band.
 *
 * Units: signed 0.1 % duty BEFORE battery compensation (13.5 V equivalent),
 * the bias curve's own unit. Unsupported curve ends stay untouched; nothing
 * is extrapolated; an excluded interior position refuses the whole update. */
#ifndef HC_ETB_BIAS_H
#define HC_ETB_BIAS_H
#define BIAS_POINTS 6u
#define FRIC_REPS 3u
#define BIAS_EMPTY 0u
#define BIAS_READY 1u
#define BIAS_SAVED 2u
#define BIAS_RUN 3u
#define BIAS_FAULT 4u
#define BIAS_SAMPLES 5u      /* a position lacks its full set of trials      */
#define BIAS_HYSTERESIS 6u   /* opening edge not above closing edge: no band */
#define BIAS_SATURATION 7u   /* no break-away within the duty authority      */
#define BIAS_CHANGED 8u
#define BIAS_UNSUPPORTED 9u
#define BIAS_VALIDATE 10u
#define BIAS_UNSETTLED 11u   /* the closed loop could not hold the position  */
#define BIAS_REPEAT 12u      /* the same edge differed between trials        */
#define BIAS_DRIFT 13u       /* the plate moved against the ramp             */
/* Largest max-min of one edge across its FRIC_REPS trials (0.1 % duty).
   MEASURED (4 runs, 12.5 V): with within-run edge
   spreads up to 9.8 % the band MIDPOINT repeated run-to-run within 0.5 %
   at 10/20/40 % and 2.6 % at 80 %; the limp-detent position (5 %) spreads
   25-27 % and must stay excluded. 10 % is a third of the band half-width. */
#define FRIC_SPREAD_MAX 100
static const unsigned int bias_positions[BIAS_POINTS] = {50u,100u,200u,400u,600u,800u};
typedef struct {
    int edge[BIAS_POINTS][2][FRIC_REPS];   /* [.][0] closing, [.][1] opening */
    unsigned char got[BIAS_POINTS][2];
    unsigned char fail[BIAS_POINTS];
    int mid[BIAS_POINTS], width[BIAS_POINTS];
    unsigned int spread[BIAS_POINTS];
    unsigned int axis[8], current[8], proposed[8], pax[8];
    unsigned int wx[BIAS_POINTS+8u]; int wv[BIAS_POINTS+8u]; unsigned char wn;
    unsigned int revision, samples, changed;
    unsigned int min_target, max_target;
    unsigned int integral_before, integral_after;
    unsigned long integral_sum;
    unsigned char state, pending, busy;
    unsigned int valid_min, valid_max, excluded, excluded_reason, qualified_samples;
    /* the running trial, hcetbcal.c */
    unsigned char fj, fr, fe, fsub, fmov, fn;
    unsigned int fms, fms_now, ft, fref, hold_ms;
    int fu0, fu, fcross;
    unsigned long fsum;
} hc_bias_t;
static void bias_begin(hc_bias_t HC_SWEEP_PTR *b, unsigned int revision)
{
    unsigned int j;
    unsigned char HC_SWEEP_PTR *p=(unsigned char HC_SWEEP_PTR *)b;
    unsigned int prior=b->integral_after;
    for(j=0u;j<sizeof(hc_bias_t);j++) p[j]=0u;
    b->revision=revision; b->state=BIAS_RUN; b->integral_before=prior;
}
/* Controller workload at the settled hold plateaus: the mean |I| the loop
   needs once P/D have nothing left to do. A comparison figure, not a bias. */
static void bias_hold(hc_bias_t HC_SWEEP_PTR *b, unsigned int elapsed,
    unsigned int duration, unsigned int sample_ms, unsigned int target,
    unsigned int actual, int p, int d, int i)
{
    if (sample_ms==b->hold_ms) return;
    b->hold_ms=sample_ms;
    if (elapsed+500u<duration || sweep_abs((int)target-(int)actual)>10u
        || sweep_abs(p)>30u || sweep_abs(d)>15u) return;
    b->samples++; b->integral_sum+=sweep_abs(i);
}
static void bias_edge(hc_bias_t HC_SWEEP_PTR *b, int command)
{
    unsigned char j=b->fj, e=b->fe;
    if(j<BIAS_POINTS && b->got[j][e]<FRIC_REPS)
        b->edge[j][e][b->got[j][e]++]=command;
}
static int bias_mean(long sum, unsigned int n)
{
    unsigned long mag=(unsigned long)(sum<0L ? -sum : sum);
    unsigned int mean=(unsigned int)(mag/n);
    return sum<0L ? -(int)mean : (int)mean;
}
/* v0 + (v1-v0)(x-x0)/(x1-x0), x0 <= x <= x1, x0 < x1. 16x16 MUL + 32:16 DIV. */
static int bias_lerp(unsigned int x0, int v0, unsigned int x1, int v1, unsigned int x)
{
    int delta=v1-v0;
    int a=(int)((unsigned long)sweep_abs(delta)*(x-x0)/(x1-x0));
    return v0+(delta<0 ? -a : a);
}
/* The CURRENT curve at x, as hc_cal_curve16 evaluates it (ends clamped). */
static int bias_current(hc_bias_t HC_SWEEP_PTR *b, unsigned int x)
{
    unsigned char k;
    if(x<=b->axis[0]) return (int)b->current[0]-1000;
    for(k=1u;k<8u;k++) if(x<=b->axis[k])
        return bias_lerp(b->axis[k-1u],(int)b->current[k-1u]-1000,b->axis[k],(int)b->current[k]-1000,x);
    return (int)b->current[7]-1000;
}
static void bias_drop(hc_bias_t HC_SWEEP_PTR *b, unsigned char i)
{
    for(;i+1u<b->wn;i++) {b->wx[i]=b->wx[i+1u]; b->wv[i]=b->wv[i+1u];}
    b->wn--;
}
/* THE PROPOSED CURVE: a point at every supported measurement position
   (value = band midpoint) plus the current points outside the supported
   range, untouched. Over eight points, the unsupported interior point whose
   removal changes the curve least goes first; under eight, the widest gap
   gets its interpolated midpoint (no new information either way). */
static void bias_shape(hc_bias_t HC_SWEEP_PTR *b, unsigned char first, unsigned char last)
{
    unsigned char k,i,best;
    unsigned int e,beste,gap;
    b->wn=0u;
    for(k=0u;k<8u;k++) if(b->axis[k]<bias_positions[first])
        {b->wx[b->wn]=b->axis[k]; b->wv[b->wn++]=(int)b->current[k]-1000;}
    for(k=first;k<=last;k++) {b->wx[b->wn]=bias_positions[k]; b->wv[b->wn++]=b->mid[k];}
    for(k=0u;k<8u;k++) if(b->axis[k]>bias_positions[last])
        {b->wx[b->wn]=b->axis[k]; b->wv[b->wn++]=(int)b->current[k]-1000;}
    while(b->wn>8u) {
        best=0u; beste=65535u;
        for(i=1u;i+1u<b->wn;i++) {
            if(b->wx[i]>=bias_positions[first] && b->wx[i]<=bias_positions[last]) continue;
            e=sweep_abs(b->wv[i]-bias_lerp(b->wx[i-1u],b->wv[i-1u],b->wx[i+1u],b->wv[i+1u],b->wx[i]));
            if(e<beste) {beste=e; best=i;}
        }
        bias_drop(b,best);
    }
    while(b->wn<8u) {
        best=1u; gap=0u;
        for(i=1u;i<b->wn;i++) if(b->wx[i]-b->wx[i-1u]>gap) {gap=b->wx[i]-b->wx[i-1u]; best=i;}
        for(i=b->wn;i>best;i--) {b->wx[i]=b->wx[i-1u]; b->wv[i]=b->wv[i-1u];}
        b->wx[best]=b->wx[best-1u]+gap/2u;
        b->wv[best]=bias_lerp(b->wx[best-1u],b->wv[best-1u],b->wx[best+1u],b->wv[best+1u],b->wx[best]);
        b->wn++;
    }
}
static unsigned char bias_propose(hc_bias_t HC_SWEEP_PTR *b)
{
    unsigned char j,k,r,dir,first=0u,last=BIAS_POINTS-1u;
    unsigned char reason[BIAS_POINTS];
    int m[2],v,lo,hi;
    long s;
    b->excluded=0u; b->excluded_reason=0u;
    b->valid_min=0u; b->valid_max=0u; b->qualified_samples=0u;
    while(first<BIAS_POINTS && bias_positions[first]<b->min_target) first++;
    while(last && bias_positions[last]>b->max_target) last--;
    if(first>=last || last-first<2) return BIAS_UNSUPPORTED;
    for(j=first;j<=last;j++) {
        reason[j]=b->fail[j];
        b->spread[j]=0u; m[0]=m[1]=0;
        for(dir=0u;dir<2u;dir++) {
            if(b->got[j][dir]<FRIC_REPS) {if(!reason[j]) reason[j]=BIAS_SAMPLES; continue;}
            lo=hi=b->edge[j][dir][0]; s=0L;
            for(r=0u;r<FRIC_REPS;r++) {
                v=b->edge[j][dir][r]; s+=v;
                if(v<lo) lo=v;
                if(v>hi) hi=v;
            }
            if((unsigned int)(hi-lo)>b->spread[j]) b->spread[j]=(unsigned int)(hi-lo);
            m[dir]=bias_mean(s,FRIC_REPS);
            if(hi-lo>FRIC_SPREAD_MAX && !reason[j]) reason[j]=BIAS_REPEAT;
        }
        b->mid[j]=(m[0]+m[1])/2; b->width[j]=m[1]-m[0];
        if(!reason[j] && m[1]<=m[0]) reason[j]=BIAS_HYSTERESIS;
        if(reason[j]) {
            b->excluded|=1u<<j;
            if(!b->excluded_reason) b->excluded_reason=reason[j];
        }
    }
    /* Retain unsupported curve ends. Never bridge an unreliable interior
       position, extrapolate, or relax a confidence threshold. At least three
       adjacent measurement positions must independently pass every gate. */
    while(first<last && reason[first]) first++;
    while(last>first && reason[last]) last--;
    if(last-first<2) return b->excluded_reason ? (unsigned char)b->excluded_reason : BIAS_UNSUPPORTED;
    for(j=first;j<=last;j++) {
        if(reason[j]) return reason[j];
        b->qualified_samples+=2u*FRIC_REPS;
    }
    b->valid_min=bias_positions[first];b->valid_max=bias_positions[last];
    /* No measured midpoint beyond +-80 % duty or 30 % from the current curve. */
    for(j=first;j<=last;j++)
        if(sweep_abs(b->mid[j])>800u
           || sweep_abs(b->mid[j]-bias_current(b,bias_positions[j]))>300u)
            return BIAS_UNSUPPORTED;
    bias_shape(b,first,last);
    b->changed=0u;
    for(k=0u;k<8u;k++) {
        b->pax[k]=b->wx[k]; b->proposed[k]=(unsigned int)(b->wv[k]+1000);
        if(b->pax[k]!=b->axis[k] || b->proposed[k]!=b->current[k]) b->changed++;
    }
    if(!b->changed) return BIAS_UNSUPPORTED;
    return BIAS_READY;
}
#endif
