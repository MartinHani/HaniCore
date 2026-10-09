/*
 * hcevlog711.c - V99: the engine EVENT RING, the lambda dynamics check and
 * the vehicle-test telemetry. FAR code (FCODE), TASK CONTEXT ONLY.
 *
 * WHY (the first V98r2 car session, 2026-10-02). The engine died on a sharp
 * throttle "as if the ignition were cut", AutoCal failed "NOT A STOP A",
 * lambda read ~1.04 whatever the fuel - and nothing recorded what the
 * firmware decided at the moment it mattered. A logger polling the output
 * channels over the K-line sees 20..80 snapshots a second at best, misses a
 * state that lasts one frame, and sees nothing while the link drops - which
 * is exactly when an engine stalls. This ring records TRANSITIONS where they
 * happen, timestamped, in battery-backed SRAM, and the host reads them later.
 *
 * HOW. hc_evlog_service() runs once per output-channel frame from
 * hc_io_publish() (the same task-context pass that composes the block a
 * logger reads) and compares what the firmware PUBLISHES - the output
 * channels themselves, plus three counters the block does not carry -
 * against its snapshot of the previous pass. Nothing runs on the tooth path
 * or in an interrupt; the serial reply that exports the ring runs in the same
 * main loop, so a reply never sees a half-written record. Every record
 * carries a sequence number: a host that reads too slowly sees the gap and
 * reports LOST records - an overflow is never silent.
 *
 * REGION (TGT_RAM_EVLOG, 1 KB, the unused tail of the calibration region):
 *   0x000 header (exported): magic "HE", version, next seq, record count,
 *         record size, boots seen, 6 reserved
 *   0x010 records (exported): EV_N x 10 bytes, big-endian:
 *         seq u16, ms u16 (uptime), type u8, arg u8, v1 u16, v2 u16
 *   after them: the snapshot (not exported).
 * The export follows the boot history in the extended output-channel window
 * (hc_io_boothist_byte -> hc_evlog_byte), so TunerStudio's poll does not
 * grow by a byte.
 *
 * PASSIVE LAMBDA ACTIVITY (hc_lamdyn_step). Quiet steady exhaust can be
 * valid; electrical noise can imitate a changing process. These historical
 * alive/stuck bits mean variation observed/sustained low variation only.
 * They never gate measurement validity, trim, or analysis acceptance.
 */
#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hc_config_generated.h"
#include "hcsched_dry.h"
#include "hcetbcal.h"
#include "hcwb.h"
#include "hcevlog711.h"

#define EV_MAGIC     0x4845u     /* "HE" */
#define EV_VERSION   1u
#define EV_REC       10u
#define EV_HDR       16u

typedef struct {                 /* the snapshot: what was published last */
    unsigned int sync, cyc_lost, cyc_acq, phcorr, loss_n, fuelcut, flags;
    unsigned int ovd, ovd_latch, missed, seq, dbw, dbwf, limp, lamst, lamwhy;
    unsigned int etb, skips, rx[5], dyn, eng;
    unsigned int t_skip, t_missed, t_rx;
    unsigned char ok;
} hc_ev_snap_t;


#define EVB   ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_EVLOG))
#define EV_RECS (EVB + EV_HDR)
#define SNAP  (*(hc_ev_snap_t huge *)(TGT_EXTRAM_BASE + TGT_RAM_EVLOG \
                                      + EV_HDR + EV_N * EV_REC))
typedef char hc_ev_fits[(EV_HDR + EV_N * EV_REC + sizeof(hc_ev_snap_t)
                         <= TGT_RAM_EVLOG_LIMIT) ? 1 : -1];
/* the dynamics state: the core is sensors/hcwb.c hcwb_dyn_step (host-tested,
   tests/host/test_hcwb_dyn.c); 24 bytes of the far modules' XRAM */
static hcwb_dyn_t ld[2];

#define OCH1B ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH))
#define OCH2B ((unsigned char huge *)(TGT_EXTRAM_BASE + TGT_RAM_OCH2))

#define EV_RATE_MS     200u     /* counter events: at most one per 200 ms    */

static unsigned int rd16(unsigned char huge *p)
{
    return (unsigned int)(((unsigned int)p[0] << 8) | p[1]);
}

static void wr16(unsigned char huge *p, unsigned int v)
{
    p[0] = (unsigned char)(v >> 8);
    p[1] = (unsigned char)(v & 0xFFu);
}

static unsigned int och(unsigned int at)
{
    return rd16((at >= 1024u) ? (OCH2B + (at - 1024u)) : (OCH1B + at));
}

static void och_set(unsigned int at, unsigned int v)
{
    wr16((at >= 1024u) ? (OCH2B + (at - 1024u)) : (OCH1B + at), v);
}

static unsigned int ev_ms;      /* the pass's uptime, for every record */

static void ev(unsigned char type, unsigned char arg, unsigned int v1,
               unsigned int v2)
{
    unsigned int seq = rd16(EVB + 4u);
    unsigned char huge *r = EV_RECS + (unsigned int)((seq % EV_N) * EV_REC);

    wr16(r, 0xFFFFu);            /* a record being written is never valid */
    wr16(r + 2u, ev_ms);
    r[4] = type;
    r[5] = arg;
    wr16(r + 6u, v1);
    wr16(r + 8u, v2);
    wr16(r, seq);
    wr16(EVB + 4u, (unsigned int)(seq + 1u));
}

void far hc_evlog_init(unsigned int boots, unsigned int reset_raw)
{
    unsigned int i;

    if (rd16(EVB) != EV_MAGIC || rd16(EVB + 2u) != EV_VERSION
        || rd16(EVB + 6u) != EV_N || rd16(EVB + 8u) != EV_REC) {
        for (i = 0u; i < EV_HDR + EV_N * EV_REC; i++) {
            EVB[i] = 0u;
        }
        wr16(EVB, EV_MAGIC);
        wr16(EVB + 2u, EV_VERSION);
        wr16(EVB + 6u, EV_N);
        wr16(EVB + 8u, EV_REC);
    }
    wr16(EVB + 10u, (unsigned int)(rd16(EVB + 10u) + 1u));
    SNAP.ok = 0u;               /* the first pass only takes the snapshot */
    for (i = 0u; i < 2u; i++) {
        ld[i].alive = 0u; ld[i].stuck = 0u; ld[i].frozen = 0u; ld[i].on = 0u;
        ld[i].span = 0u; ld[i].t0 = 0u; ld[i].umin = 0xFFFFu; ld[i].umax = 0u;
    }
    ev_ms = 0u;
    ev(EV_BOOT, 0u, boots, reset_raw);   /* the records survive a reset */
}

unsigned char far hc_evlog_byte(unsigned int off)
{
    return (off < (unsigned int)(EV_HDR + EV_N * EV_REC)) ? EVB[off] : 0u;
}

/* ---------------------------------------------------- lambda dynamics -- */
unsigned char far hc_lamdyn_step(unsigned char b, unsigned char valid,
                                 unsigned int ua, unsigned char running,
                                 unsigned int ms)
{
    return hcwb_dyn_step(&ld[b & 1u], valid, ua, running, ms);
}

unsigned char far hc_lamdyn_alive(unsigned char b)
{
    return ld[b & 1u].alive;
}

/* lamDyn: bit 0/1 variation observed, bit 2/3 sustained low variation, bit 4/5 being watched;
   high byte the last window's span of bank 1 (saturated) */
static unsigned int lamdyn_word(void)
{
    unsigned int w = 0u;
    unsigned char b;

    for (b = 0u; b < 2u; b++) {
        if (ld[b].alive) w |= (unsigned int)(1u << b);
        if (ld[b].stuck) w |= (unsigned int)(4u << b);
        if (ld[b].on)    w |= (unsigned int)(16u << b);
    }
    return (unsigned int)(w | ((ld[0].span > 255u ? 255u : ld[0].span) << 8));
}

/* ------------------------------------------------------------ service -- */
static unsigned char changed(unsigned int now, unsigned int huge *was)
{
    if (now != *was) {
        *was = now;
        return 1u;
    }
    return 0u;
}

/* a counter's event, at most one per EV_RATE_MS; the record carries the
   counter itself, so nothing is lost between two records */
static void counted(unsigned char type, unsigned int now,
                    unsigned int huge *was, unsigned int huge *t,
                    unsigned int rpm)
{
    if (now != *was && (unsigned int)(ev_ms - *t) >= EV_RATE_MS) {
        ev(type, 0u, rpm, now);
        *was = now;
        *t = ev_ms;
    }
}

void far hc_evlog_service(unsigned int ms)
{
    unsigned int rpm, v, i;
    hc_ev_snap_t huge *s = &SNAP;

    ev_ms = ms;
    rpm = och(160u);

    /* the vehicle-test telemetry (OCH 1224..1247) */
    och_set(1224u, hc_etbcal_value(ETBV_HOLD1));
    och_set(1226u, hc_etbcal_value(ETBV_PUSH1));
    och_set(1228u, hc_etbcal_value(ETBV_LIMIT));
    och_set(1230u, hc_etbcal_value(ETBV_MOVED));
    och_set(1232u, hc_etbcal_value(ETBV_HOLD_MS));
    och_set(1234u, hc_etbcal_value(ETBV_DISP));
    och_set(1236u, lamdyn_word());
    och_set(1238u, (unsigned int)(ld[1].span > 255u ? 255u : ld[1].span));
    och_set(1240u, dry_spark_skips);
    och_set(1242u, rd16(EVB + 4u));
    och_set(1244u, ms);                 /* the ECU clock the records carry */
    och_set(1246u, (unsigned int)EV_N);

    if (!s->ok) {
        s->sync = och(162u); s->cyc_lost = och(794u); s->cyc_acq = och(792u);
        s->phcorr = och(804u); s->loss_n = och(242u); s->fuelcut = och(158u);
        s->flags = och(1166u); s->ovd = och(778u); s->ovd_latch = och(782u);
        s->missed = och(292u); s->seq = och(974u); s->dbw = och(400u);
        s->dbwf = och(402u); s->limp = och(946u); s->lamst = och(738u);
        s->lamwhy = och(1010u); s->etb = hc_etbcal_status();
        s->skips = dry_spark_skips; s->dyn = lamdyn_word();
        for (i = 0u; i < 5u; i++) s->rx[i] = och((unsigned int)(20u + 2u * i));
        s->eng = 0u;
        s->t_skip = ms; s->t_missed = ms; s->t_rx = ms;
        s->ok = 1u;
        return;
    }

    /* crank / cycle sync */
    v = s->sync;
    if (changed(och(162u), &s->sync)) {
        ev(EV_SYNC, (unsigned char)s->sync, rpm,
           (unsigned int)((v << 8) | (och(244u) & 0xFFu)));
    }
    if (changed(och(242u), &s->loss_n)) {
        ev(EV_SYNC_LOSS, (unsigned char)och(244u), rpm, s->loss_n);
    }
    if (changed(och(792u), &s->cyc_acq)) {
        ev(EV_CYCLE, 1u, rpm, s->cyc_acq);
    }
    if (changed(och(794u), &s->cyc_lost)) {
        ev(EV_CYCLE, 0u, rpm, och(280u));
    }
    if (changed(och(804u), &s->phcorr)) {
        ev(EV_PHASE_CORR, 0u, rpm, s->phcorr);
    }
    if (changed(och(974u), &s->seq)) {
        ev(EV_SEQ, (unsigned char)s->seq, rpm, och(978u));
    }

    /* the engine: stopped / cranking / running (engineFlags bits 0, 1) */
    v = och(1166u);
    i = (v & 1u) ? 2u : ((v & 2u) ? 1u : 0u);
    if (changed(i, &s->eng)) {
        ev(EV_ENGINE, (unsigned char)i, rpm, och(1148u));
    }
    /* cut and limiter flags: DFCO, any fuel cut, launch, flat shift,
       anti-lag, rev limit, MAP estimate */
    if (changed((unsigned int)(v & 0x7E20u), &s->flags)) {
        ev(EV_FLAGS, 0u, rpm, s->flags);
    }
    if (changed(och(158u), &s->fuelcut)) {
        ev(EV_FUELCUT, 0u, rpm, s->fuelcut);
    }
    if (changed(och(946u), &s->limp)) {
        ev(EV_LIMP, 0u, rpm, s->limp);
    }

    /* ignition: overdwell releases and latches, cut-ratio skips, missed */
    v = och(782u);
    if (changed(och(778u), &s->ovd) | changed(v, &s->ovd_latch)) {
        ev(EV_OVERDWELL, (unsigned char)v, rpm, s->ovd);
    }
    counted(EV_SPARK_SKIP, dry_spark_skips, &s->skips, &s->t_skip, rpm);
    counted(EV_SCHED_MISSED, och(292u), &s->missed, &s->t_missed, rpm);

    /* the throttle and its procedures */
    v = hc_etbcal_status();
    if (changed(v, &s->etb)) {
        ev(EV_ETB, (unsigned char)((v >> 4) & 0x0Fu), v,
           hc_etbcal_value(ETBV_DETAIL));
    }
    v = s->dbwf;
    if (changed(och(400u) & 0x00FFu, &s->dbw) | changed(och(402u), &s->dbwf)) {
        ev(EV_DBW, (unsigned char)s->dbw, rpm, s->dbwf);
    }

    /* lambda: status (valid / heater state / READY / pump) and why */
    v = s->lamst;
    if (changed(och(738u), &s->lamst) | changed(och(1010u), &s->lamwhy)) {
        ev(EV_LAMBDA, 0u, s->lamst, s->lamwhy);
    }
    if (changed(lamdyn_word() & 0x00FFu, &s->dyn)) {
        ev(EV_LAMDYN, (unsigned char)s->dyn, rpm, ld[0].span);
    }

    /* the K-line: a resync, hardware overrun, framing error, ring overflow
       or lost echo since the last record (rate-limited, counts carried) */
    for (i = 0u; i < 5u; i++) {
        v = och((unsigned int)(20u + 2u * i));
        if (v != s->rx[i] && (unsigned int)(ms - s->t_rx) >= EV_RATE_MS) {
            ev(EV_KLINE, (unsigned char)i, rpm, v);
            s->rx[i] = v;
            s->t_rx = ms;
        }
    }
}
