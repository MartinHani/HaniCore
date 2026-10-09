/* Cold telemetry and commissioning commands. ISR/control ownership stays near. */
#include "hcfarbridge.h"
#include <reg167.h>
#include "hctarget.h"
#include "hcconfig.h"
#include "hcts.h"
#include "hcasic.h"
#include "hcasicframe.h"
#include "hcasicstart.h"
#include "hcasicdump.h"
#include "hcpower.h"
#include "hchal.h"
#include "hchal_me711.h"
#include "hctrigger.h"
#include "hcsched_dry.h"
#include "hcdeadline711.h"
#include "hcbench.h"
#include "hcnvm.h"
#include "hcburnforensics.h"
#include "hcliveforensics.h"
#include "hcsafety.h"
#include "hcengine.h"
#include "hcmainrelay.h"
#include "hcfuelpump.h"
#include "hc_dbw.h"
#include "hcetbcal.h"         /* ETB calibration / autotune (far) */
#include "hc_config_manager.h"
#include "hc_pin_descriptor.h"
#include "hc_presets.h"
#include "hc_route.h"
#include "hcio711.h"
#include "hcboost711.h"
#include "hcidle711.h"
#include "hcknock711.h"       /* knock window, CC195, retard per slot */
#include "hcvvt711.h"         /* cam phase control, POUT0/POUT1 */
#include "hctrans711.h"    /* transient fuel */
#include "hcdtc711.h"
#include "hclimp711.h"
#include "hckwp_me711.h"      /* VAG/KWP vehicle entry (far) */


extern unsigned int hc_badvec, hc_firstvec, hc_lastvec, hc_tick_ms;
extern unsigned int adc_raw[];
#define tick_ms hc_tick_ms
#define OCHP OCH
extern unsigned int boot_stage;
extern unsigned int loop_count;
extern unsigned int frames;
extern unsigned int tick_ok;
extern unsigned int cal_ticks;
extern unsigned int status;
extern unsigned int cfg_fault_cache;
extern unsigned int stack_scan_ms;
extern unsigned int io_boost_req;
static unsigned int get16(unsigned int at)
{
    return (unsigned int)(((unsigned int)OCHP[at] << 8)
                          | (unsigned int)OCHP[at + 1]);
}

static void put16(unsigned int at, unsigned int v)
{
    /* NO YIELD HERE. One was needed while update_live()
       wrote every channel in one stretch and a TunerStudio reply held the
       main loop inside hcts_tx(); the publication is now one bounded slice
       per pass (hc_diag_publish_step, <= ~2 ms CPU measured at 7000 rpm),
       replies are an interrupt job and the receive path is PEC. Called per
       channel, the tick-gated yield ran its whole service set (ADC, ASIC,
       bench, overdwell, AIN snapshot, DBW: up to 1.2 ms) once per wall
       millisecond INSIDE the slice: at 9600 rpm, where the main loop has a
       third of the CPU, that cost more than the millisecond held and a slice
       stretched to 48 ms (simulator, docs/ARCHITECTURE.md). */
    hcts_rx_pump();
    OCHP[at]     = (unsigned char)((v >> 8) & 0xFF);
    OCHP[at + 1] = (unsigned char)(v & 0xFF);
}

static unsigned int adc_to_cv(unsigned int raw)
{
    return (unsigned int)(((unsigned long)raw
                           * (unsigned long)TGT_ADC_BATT_FS_DV
                           * 10uL) / 1023uL);
}

static const unsigned char bf_och_map[] = {
    HCBF_SEQUENCE, HCBF_CHECKSUM, HCBF_FLAGS, HCBF_BOOT_EPOCH,
    HCBF_BURN_EPOCH, HCBF_HCTS_INITS, HCBF_HCTS_BOOT,
    (unsigned char)(0x80u | HCBF_BURNS_PRE),
    (unsigned char)(0x80u | HCBF_WRITES_PRE), HCBF_RESET_RAW,
    (unsigned char)(0x80u | HCBF_BOOT_STAGE),
    (unsigned char)(0x80u | HCBF_PREV_STAGE),
    (unsigned char)(0x80u | HCBF_PREV_TRAP), HCBF_PREV_TRAP_MS,
    HCBF_PREV_UPTIME, HCBF_PREV_LOOP, HCBF_PREV_WDT,
    (unsigned char)(0x80u | HCBF_NVM_STATE),
    (unsigned char)(0x80u | HCBF_NVM_PHASE),
    (unsigned char)(0x80u | HCBF_NVM_RESULT),
    (unsigned char)(0x80u | HCBF_NVM_CELL), HCBF_NVM_POS,
    HCBF_NVM_ATTEMPTS, (unsigned char)(0x80u | HCBF_NVM_ERROR),
    (unsigned char)(0x80u | HCBF_WRITER_RESULT), HCBF_NVM_RETRIES,
    HCBF_FAIL_WORD, HCBF_FAIL_EXP, HCBF_FAIL_GOT, HCBF_FAIL_GOT2,
    HCBF_POLL_MIN, HCBF_POLL_MAX, (unsigned char)(0x80u | HCBF_STAGE),
    (unsigned char)(0x80u | HCBF_LAST_STAGE),
    (unsigned char)(0x80u | HCBF_FAIL_STAGE),
    (unsigned char)(0x80u | HCBF_FAILURE)
};
static const unsigned char rst_och_map[] = {
    RST_BOOTS, RST_RESET_RAW, RST_STAGE, RST_PREV_STAGE, RST_PREV_MS,
    RST_PREV_LOOP, RST_PREV_FIRSTVEC, RST_PREV_LASTVEC, RST_PREV_TRAP,
    RST_PREV_TRAP_MS, RST_PREV_WDT_COUNT, RST_PREV_MARKER, RST_PREV_TGT0,
    RST_PREV_TGT1, RST_PREV_TGT2, RST_PREV_TGT3, RST_PREV_TGT4, RST_TRAP,
    RST_TRAP_MS, RST_WDT_COUNT, RST_MARKER, RST_TGT0, RST_TGT1, RST_TGT2,
    RST_TGT3, RST_TGT4
};

static void update_forensics_live(unsigned char part)
{
    unsigned int i;
    unsigned char off;
    if(part==0u) {
    put16(478, (hc_bf_u8(HCBF_VERSION) << 8) | hc_bf_u8(HCBF_LENGTH));
    for (i = 0u; i < sizeof(bf_och_map); i++) {
        off = bf_och_map[i];
        put16((unsigned int)(480u + 2u * i), (off & 0x80u)
              ? hc_bf_u8((unsigned int)(off & 0x7Fu)) : hc_bf_u16(off));
    }
        return;
    }
    for (i = 0u; i < sizeof(rst_och_map); i++) {
        put16((unsigned int)(552u + 2u * i), hc_rst_get(rst_och_map[i]));
    }
    /* The V45 diary is compiled out in this qualification profile. Preserve
       its established channel offsets but make its three header scalars name
       the active V49 record, so the normal 680-byte view can prove that the
       forensic layout exists before the one permitted Burn. */
    put16(604, HC_LF_WORD(LF_MAGIC0));
    put16(606, HC_LF_WORD(LF_MAGIC1));
    put16(484, HC_LF_WORD(LF_FLAGS));
    put16(608, (unsigned int)(HC_LF_WORD(LF_MAGIC0) == 0x4843u
          && HC_LF_WORD(LF_MAGIC1) == 0x4C46u
          && HC_LF_WORD(LF_VERSION) == 0x0049u
          && HC_LF_WORD(LF_LENGTH) == HC_LF_BYTES
          && (HC_LF_WORD(LF_FLAGS) & LF_F_VALID) != 0u));
}



/* THE PUBLICATION IS SLICED. The whole block took up to 5.4 ms
   of uninterrupted main-loop time (runtime audit P0-2: the longest planner-
   free stretch, then; still the longest wait for DBW and eng_service once the
   planner had its own level). hc_diag_publish_step() runs ONE slice per
   main-loop pass - the platform, the runtime and store, the live-Burn and
   decoder words, three parts of hc_io_publish(), the tail - and says when a
   cycle is complete; hcmain_me711.c starts one every 40 ms. A channel is
   still written whole, by one slice, so a reply can mix two cycles' slices
   but never two halves of one value (and hcserial711.c sends each 16-bit
   channel from one interrupt). */
static void pub_platform(void)
{
    unsigned int i;

    frames++;

    status = HC_ST_WDT;
#ifdef HANICORE_BENCH_SAFE
    status |= HC_ST_BENCHSAFE;          /* only a build with no output backends */
#endif
    if (tick_ok) {
        status |= HC_ST_TICK;
    }
    if (rx_tick_ok || rx_irq_ok) {
        status |= HC_ST_RXTICK;
    }
    if (hc_asic_state != HC_ASIC_ST_IDLE) {
        status |= HC_ST_ASIC_INIT;
    }
    if (hc_asic_start_ok) {
        status |= HC_ST_ASIC_START;
    }
    if (hc_asic_run_ok) {
        status |= HC_ST_ASIC_RUN;
    }
    if (hc_asic_start_csum_err || hc_asic_run_csum_err
        || hc_asic_start_timeout || hc_asic_run_timeout
        || hc_asic_ssc_errors) {
        status |= HC_ST_ASIC_ERR;
    }
    if (hc_ram_bad) {
        status |= HC_ST_RAMBAD;
    }
    if (rx_hw_ovr || rx_frame_err || hc_rx_ovf) {
        status |= HC_ST_RXLOSS;
    }
    if (hc_badvec) {
        status |= HC_ST_BADVEC;
    }
    if (hc_cfg_source) {
        status |= HC_ST_TUNESTORED;
    }
    if (cfg_fault_cache) {
        status |= HC_ST_SETUPFAULT;
    }

    /* --- what it is doing right now ----------------------------------- */
    put16(0,  status);
    put16(2,  boot_stage);
    put16(4,  tick_ms);
    put16(6,  loop_count);
    put16(8,  frames);
    put16(10, cal_ticks);          /* MUST read about 220 - see cal_measure */
    put16(12, hc_cfg_source);
    put16(14, hc_ram_bad);

    /* --- the serial link ---------------------------------------------- */
    put16(16, rx_bytes);
    put16(18, rx_reqs);
    put16(20, rx_resync);
    put16(22, rx_hw_ovr);
    put16(24, rx_frame_err);
    put16(26, hc_rx_ovf);
    put16(28, rx_echo_lost);
    put16(30, rx_ticks);
    put16(32, (unsigned int)rx_irq_ok);
    put16(34, (unsigned int)rx_tick_ok);
    put16(36, (unsigned int)hc_s0r_trap);
    put16(38, probe_bad);

    /* --- interrupts nobody asked for ---------------------------------- */
    put16(40, hc_badvec);
    put16(42, hc_firstvec);
    put16(44, hc_lastvec);

    /* --- the ASIC ------------------------------------------------------ */
    put16(46, (unsigned int)hc_asic_state);
    put16(48, (unsigned int)
          ((hc_asic_start_ok || hc_asic_run_ok)
           && ((unsigned int)(tick_ms - hc_asic_last_ok_ms) < 100u)));
    put16(50, (unsigned int)(hc_asic_start_tx + hc_asic_run_tx));
    put16(52, (unsigned int)(hc_asic_start_rx + hc_asic_run_rx));
    put16(54, hc_asic_start_ok);
    put16(56, hc_asic_run_ok);
    put16(58, (unsigned int)(hc_asic_start_ok + hc_asic_run_ok));
    put16(60, (unsigned int)(hc_asic_start_csum_err + hc_asic_run_csum_err));
    put16(62, hc_asic_retries);
    put16(64, (unsigned int)(hc_asic_start_timeout + hc_asic_run_timeout));
    put16(66, hc_asic_ssc_errors);
    put16(68, (unsigned int)(hc_asic_reply_w0 & 0x00FFu));
    put16(70, hc_asic_last_calc);
    put16(72, hc_asic_last_recv);
    /* Four raw frame words. Not named, because this repo cannot yet prove what
       any individual payload word means, and a wrong name is worse than none:
       somebody would tune against it. */
    put16(74, asic_frame_word(0));
    put16(76, asic_frame_word(1));
    put16(78, asic_frame_word(2));
    put16(80, asic_frame_word(3));

    /* --- the calibration page ------------------------------------------ */
    put16(82, cfg_writes);
    put16(84, cfg_burns);
    put16(86, cfg_fault_cache);
    put16(88, (unsigned int)hc_cfg_stable);

    /* --- battery, and then every raw ADC count ------------------------- */
    put16(90, adc_to_cv(adc_raw[TGT_ADC_BATT_CH]));
    put16(92, hc_stalls);
    put16(94, (unsigned int)TGT_ID);

    /* All sixteen raw counts, so the channel map is CONFIRMED on the bench
       rather than trusted. It comes from Bosch's own ME7.1.1 port map, which
       is strong evidence - and strong evidence is still not a measurement. */
    for (i = 0; i < TGT_ADC_CH_COUNT; i++) {
        put16((unsigned int)(96 + 2 * i), adc_raw[i]);
    }
}

static void pub_runtime(void)
{
    unsigned int i;

    /* ===================== the HaniCore runtime, V20 =====================
     *
     * Everything above this line is the platform - boot, serial, supervision.
     * Everything below is the ENGINE RUNTIME actually running: the same
     * hcengine.c the ME7.5 board compiles, reading this board's sensors
     * through the HAL, computing load, injection time, advance and dwell off
     * the calibration page, while not one output can be energised.
     *
     * That is the point of the block: it makes the common logic OBSERVABLE
     * before anything is armed. */
    /* 128..162 (engine runtime) and 222..334 (trigger + scheduler)
       are written by hc_io_publish() (hcio711.c, FCODE): NCODE relief. */

    /* Which sensors this board actually has. A bit per HC_AIN_*, so the
       S5500-backed channels reading as unavailable is VISIBLE rather than
       looking like a dead sensor. */
    put16(164, hc_hal_ain_mask());

    /* The output census. Nothing is driven, so this is how a bench run proves
       the common logic is asking for the right things. */
    put16(166, hc_hal_out_calls);

    /* --- the S5500 correlation window --------------------------------------
     * The mechanism that closes the runtime-frame analog mapping WITHOUT
     * another flash. hc_s5500_idx reading 0xFFFF means all sixteen words in
     * the window decode as ADDAT channel i at position i - the exact
     * signature the V9 startup frame produced on hardware. Sweep the base
     * with the '!W' command and watch for it. */
    put16(168, (unsigned int)hc_s5500_base);
    put16(170, hc_s5500_idx);
    put16(172, hc_s5500_snaps);
    put16(174, hc_s5500_plausible);
    for (i = 0; i < 16u; i++) {
        put16((unsigned int)(176 + 2 * i), hc_s5500_raw((unsigned char)i));
    }

    /* --- generic main-power-relay subsystem, V21 ------------------------
     * Command is the requested logical state. `bound` and feedback-valid
     * make the deliberately unbound Bosch HAL visible, so an ON request
     * cannot be mistaken for an electrical output. Mismatch is informational
     * only and remains clear while feedback is unavailable. */

    /* --- V27 Bosch position and counting-only angle scheduler -------- */
    /* ---- configuration state, in the block's own unused slots -----------
     *
     * 336..354, in the 32 bytes TGT_OCH_SIZE was grown by. 176..206 looked
     * free to a grep for put16() and is NOT: it is the S5500 runtime-frame
     * window, written in a LOOP by hc_hal_ain_service(), so it has no literal
     * offset to find. The .ini is the only complete list of what the block
     * contains, and check_hanicore_ts_ini_syntax.py caught the collision.
     *
     * These nine answer the questions a bench session actually asks about the
     * universal configuration, none of which the ECU could answer before:
     * is my edit staged or running, is something waiting for the engine to
     * stop, did it refuse, does the page describe a runnable engine, and does
     * what I configured agree with what the firmware reads. */
    put16(348, (unsigned int)((hc_cfg_restart_pending ? 1u : 0u)
                              | (hc_cfg_migrated ? 2u : 0u)
                              | ((unsigned int)hc_cfg_persist_class() << 2)));
    put16(356, eng_lambda_x1000());         /* THE canonical fuel target */
    /* 208..220, 336..346, 350..354, 358..396 and 428 are published by
       hc_io_publish() (hcio711.c, FCODE) - NCODE relief for the engine
       model; same offsets, same values, the same pass. */
    /* The air model, so a bench can see WHY the fuel is what it is
       rather than only what it came out as. */
    /* Events the angle scheduler had to issue immediately because the
       offset moved further between two teeth than the crank did. Zero
       on a steady engine; a number, not a fault. */
    /* The bench output qualifier. hcbState is the one to watch: 3 REFUSED
       with hcbRefuse naming every unmet invariant is the normal answer on a
       bench that has not armed outputs. */
    /* DBW-only, and meaningless outside a DBW run - which is why the mode is
       published beside them at offset 368. */

    /* --- the fuel pump lifecycle ---------------------------------------
     * command in bit 8 so state and command are one word and can never be
     * read from two different passes. */

    /* --- the power path ------------------------------------------------
     * The NLEN_FR latch this CPU is actually holding, and what the S5600
     * network turns it into for each of the ASIC's two possible states. A
     * bench can read the veto directly instead of inferring it. */
    /* --- the closed-loop throttle -------------------------------------
     * The whole chain, so a bench can see WHY a duty is what it is rather
     * than only what it came out as. */
    put16(400, (unsigned int)((unsigned int)hc_dbw_state()
                              | ((unsigned int)hc_dbw_bridge_on() << 8)
                              | ((unsigned int)hc_dbw_dir() << 9)));
    put16(402, hc_dbw_faults());
    put16(404, hc_dbw_pedal_x10());
    put16(406, hc_dbw_target_x10());
    put16(408, hc_dbw_actual_x10());
    put16(410, (unsigned int)hc_dbw_error_x10());
    put16(412, hc_dbw_duty_x10());
    put16(414, (unsigned int)hc_dbw_integ());
    put16(416, hc_dbw_app1_x10());
    put16(418, hc_dbw_app2_x10());
    put16(420, hc_dbw_tps1_x10());
    put16(422, hc_dbw_tps2_x10());
    put16(424, hc_dbw_steps());
    put16(426, (unsigned int)hc_hal_dbw_sf_level());

    /* --- the logical main relay's lifecycle ---------------------------- */

    /* --- non-volatile calibration storage -------------------------------
     *
     * "I pressed Burn - did it actually save?" has to have an answer, and
     * these six words are it. hc_cfg_persist_class() is included because it is
     * the one that says whether the answer is worth anything: STANDBY means
     * the tune dies with the battery, NONVOL means there is a committed record
     * in the flash device. */
    put16(430, (unsigned int)(hc_nvm_state() | (hc_nvm_phase() << 8)));
    put16(432, (unsigned int)(hc_nvm_error() | (hc_nvm_slot() << 8)));
    put16(434, (unsigned int)(hc_nvm_source() | (hc_cfg_persist_class() << 8)));
    put16(436, hc_nvm_generation());
    put16(438, hc_nvm_commits());
    put16(440, hc_nvm_attempts());

    /* --- the VE table's own tracing channel -----------------------------
     *
     * EXACTLY the value hcengine.c passed to the VE lookup, recomputed from
     * the same two published globals and the same page byte rather than
     * mirrored into a new variable - near RAM is the scarce thing on this
     * board and the output-channel block is not.
     *
     * It exists because the .ini's table editor needs a tracing channel per
     * axis, and the VE table's load is TPS or MAP depending on
     * CAL_LOAD_SOURCE. Publishing either one alone would put the cursor on
     * the wrong cell in the other mode - a quieter lie than a file that will
     * not load, and the sort this project does not ship. */
    put16(442, (unsigned int)((hc_cal_u8(CAL_LOAD_SOURCE) == CAL_LOAD_TPS)
                              ? eng_tps_x10 : eng_map_kpa_x10));

    /* THE EXTERNAL-SRAM EXECUTION PROBE. Low byte of 444 is HCNV_RP_*, high
     * byte is how many probes this battery has seen. RUNNING after a reset is
     * the diagnosis for a board that cannot execute from 0x386000 at all -
     * the state is written before the call and the block is battery-backed,
     * so it is still there when the ECU comes back. */
    put16(444, (unsigned int)(hc_nvm_ram_state()
                              | ((hc_nvm_ram_runs() & 0x00FFu) << 8)));
    put16(446, hc_nvm_ram_seed());
    put16(448, hc_nvm_ram_result());

    /* --- THE PROGRAMMER'S DIARY ----------------------------------------
     *
     * TWO BENCH BURNS FAILED WITH "a word would not program" AND NEITHER
     * 1 MiB READBACK COULD SAY WHY. The dumps proved what did NOT happen -
     * nothing was skipped, nothing was partly programmed, nothing was written
     * outside a cell - and the reason a command sequence was refused lives in
     * microseconds that a dump cannot hold. These eight words are the RAM
     * writer's own account of the Burn in front of the operator, so the next
     * physical session answers the question instead of producing a fourth
     * dump. See hcnvm.h; they cost zero near RAM. */
    put16(454, hc_nvm_fail_word());
    put16(456, hc_nvm_fail_exp());
    put16(458, hc_nvm_fail_got());
    put16(460, hc_nvm_fail_got2());
    put16(462, hc_nvm_prog_flags());
    put16(464, hc_nvm_prog_retries());
    put16(466, hc_nvm_poll_min());
    put16(468, hc_nvm_poll_max());
    put16(470, hc_nvm_commit_stage());
    put16(472, hc_nvm_commit_last_stage());
    put16(474, hc_nvm_commit_fail_stage());
    put16(476, (unsigned int)TGT_RELEASE_ID);
    /* --- V75: the pump and relay PINS, read back from the port ------------
     * bit0 the fuel pump pin is an output at the active level
     * bit1 the main relay pin is an output at the active level
     * bit2 the HAL permits the fuel pump output (armed, link up, page valid)
     * bit3 the main relay is requested ON, bound, and refused permission
     * The request words (390, 210) say what the lifecycle ASKED for; this
     * says what the CPU port is DOING. Neither is a claim about the CJ920
     * stage or a relay - that is a meter at the cavity.
     *
     * V77, bits 4..6: the LIVE PIN LEVEL of the three capture inputs, P2.15
     * (CC15, KWDG), P2.8 (CC8, NWDG1) and P2.9 (CC9, NWDG2), read now and not
     * latched at an edge. cam1Raw/cam2Raw only move when a capture fires, so a
     * cam input held statically by a bench driver that never pulls it low was
     * invisible: the V77 bench saw zero cam edges on both banks and could not
     * say whether the pin sat HIGH, sat LOW, or was never armed. A level read
     * of an input costs no RAM and settles that. */
    put16(610, (unsigned int)((unsigned int)hc_hal_fuelpump_driven()
                              | ((unsigned int)hc_hal_main_relay_driven() << 1)
                              | ((unsigned int)hc_fuelpump_live() << 2)
                              | ((unsigned int)hc_hal_main_relay_inhibited() << 3)
                              | ((P2 & 0x8000u) ? 0x0010u : 0u)
                              | ((P2 & 0x0100u) ? 0x0020u : 0u)
                              | ((P2 & 0x0200u) ? 0x0040u : 0u)
                              /* bit 7: KL15_STAT, P6.2 - the CJ910's own view
                                 of the key, which the native main-relay stage
                                 on cavity 23 follows. */
                              | ((P6 & (1u << TGT_KL15STAT_PORT_BIT))
                                 ? 0x0080u : 0u)));

}

static void pub_live(void)
{
    /* V47 live-Burn qualification block.  Each field is producer-owned here;
       the generated INI cross-checks these offsets and the final block size. */
    put16(612, hc_nvm_live_owner());
    put16(614, hc_nvm_live_admission());
    put16(616, hc_nvm_live_pause_reason());
    put16(618, hc_nvm_live_windows_ok());
    put16(620, hc_nvm_live_windows_rejected());
    put16(622, hc_nvm_live_deadline_ms());
    put16(624, hc_nvm_live_predicted_ms());
    put16(626, hc_nvm_live_horizon_us());
    put16(628, hc_nvm_live_writer_entries());
    put16(630, hc_nvm_live_writer_success());
    put16(632, hc_nvm_live_writer_failures());
    put16(634, hc_nvm_live_mask());
    put16(636, hc_nvm_live_pending_before());
    put16(638, hc_nvm_live_pending_after());
    put16(640, hc_nvm_live_vector_violations());
    put16(642, hc_ssc_pec_tx_left());
    put16(644, hc_ssc_pec_rx_left());
    put16(646, hc_ssc_sscon());
    put16(648, hc_asic_state);
    put16(650, (unsigned int)(tick_ms - hc_asic_last_ok_ms));
    put16(652, trg_rpm);
    put16(654, hc_nvm_words_total());
    put16(656, hc_nvm_words_completed());
    put16(658, hc_nvm_words_remaining());
    put16(660, hc_nvm_fail_word());
    put16(662, hc_nvm_poll_max());
    put16(664, hc_asic_busy_refusals);
    put16(666, hc_asic_run_timeout);
    put16(668, hc_ssc_err_vec);
    put16(670, hc_nvm_prog_flags());
    put16(672, hc_nvm_attempts());
    put16(674, hc_nvm_generation());
    put16(676, hc_nvm_commits());
    put16(678, hc_nvm_error());
    /* V53, the reclaim. The store is erased at runtime now and that has never
       run on this ECU; without these a bench cannot tell a slow erase from one
       that will never converge. */
    put16(680, hc_nvm_free_cells());
    put16(682, hc_nvm_cells_total());
    put16(684, hc_nvm_erase_state());
    put16(686, hc_nvm_erase_slices());
    put16(688, hc_nvm_erase_ms());
    put16(690, hc_nvm_reclaims());
    put16(692, hc_nvm_erase_fails());
    put16(694, hc_nvm_erase_tries());

    /* ---- V55: WHAT THE DECODER THINKS THE WHEEL IS -----------------------
     *
     * Thirteen channels that cost 26 bytes of the block and answer the one
     * question every previous trigger session would have had to guess at:
     * whether "no sync" means the SIGNAL is wrong or the CONFIGURATION is.
     * Until V55 the geometry was three #defines inside hctrig_me711.c and
     * there was nothing to publish.
     *
     * trigCfgGeneration is the one a bench procedure uses: it counts the
     * times the decoder re-read the page at RPM zero, so a TunerStudio edit
     * that has NOT reached the decoder is visible as a number that did not
     * move, rather than as a behaviour that did not change. */
    /* THE OUTPUT CENSUS - V63. Built here rather than kept as two more
       globals: hc_hal_out_value() already holds it, and a mirror would be a
       second copy of the same fact. Sixteen far reads once per publish, on the
       path that already does hundreds. */
    /* THE HAL HOLDS THESE AS MASKS NOW, so the publisher stops rebuilding
       them a bit at a time - sixteen calls became two reads. */
    put16(724, hc_hal_out_mask_ign());
    put16(726, hc_hal_out_mask_inj());
    /* 776 the ETB calibration (hc_dbw_cal_status), 778 coils released
       by the maximum-dwell watch (hcsched_dry.c). */
    put16(776, hc_etbcal_status());
    put16(778, dry_sched_overdwell);
    put16(780, eng_clt_dc);             /* CLT as the models use it */
    put16(782, hc_ign_ovd_latch);       /* coils latched after overdwell */
    /* tooth profile test, trigger corrections and the cycle. */
    /* what the ETB calibration / autotune measured (hc_dbw.c). */
    /* and 822..838 what the procedure is doing right now, so neither
       a tuner nor the DBW commissioning tool has to guess from the plate
       (hcetbcal.h ETBV_*). */
    put16(840, hc_etbcal_proc());       /* which procedure, failed stage */
    put16(842, hcts_link_state());      /* link rate, lock, rate changes */
    put16(844, hc_kwp_state());         /* KWP state, 5-baud stage, inits */
    put16(846, hc_kwp_counts());        /* failed inits, wrong addresses */
    put16(848, (unsigned int)(((unsigned int)hc_kwp_drops() << 8)
                              | hcts_link_evid()));   /* link diagnosis */
    put16(728, hc_hal_out_calls);

    /* V65 - THE TWO NUMBERS THAT ONLY HARDWARE CAN ANSWER.
     *
     * stackPeak is the point of the stack guard. me711_stack_proof measures
     * 176 of 256 bytes in a SIMULATOR, on a workload its own text admits runs
     * "no trigger, injection or ignition path" - so the 1.5x margin is a
     * measurement of the paths somebody thought to exercise. This one is the
     * depth reached by whatever the engine and TunerStudio really did.
     *
     * REFRESHED ON A TICK, NOT EVERY PASS. hc_stack_used() scans up to 96
     * words looking for where the 0x5A5A pattern stops, and update_live()
     * runs every main-loop pass; paying ~300 instructions per pass to re-read
     * a high-water mark that moves a handful of times per boot is exactly the
     * kind of cost this project keeps finding in its own hot paths. The
     * cached hc_stack_hwm is published continuously and refreshed about ten
     * times a second, which is far more often than a new deepest call chain
     * can appear. */
    if ((unsigned int)(tick_ms - stack_scan_ms) >= 100u) {
        stack_scan_ms = tick_ms;
        (void)hc_stack_used();
    }
    put16(730, hc_stack_hwm);
    put16(732, hc_nvm_lkg_steps());
}

static void pub_tail(void)
{
    /* 734..763 - wideband, CJ120, heaters, N75, ASIC image, run-on -
       and 696..722, 784..840 are hc_io_publish()'s (hcio711.c), in three
       slices of their own (hc_diag_publish_step). */
    /* --- V45 one-Burn reset forensics, 478..610 ---------------------- */
    /* 450 AND 452 ARE NOT WRITTEN HERE. They are the endpoint grab's verdict
       and its counter, and the '!G' handler owns them outright: put16() writes
       into external SRAM and update_live() only rewrites the offsets it knows,
       so an offset nothing here touches simply keeps its last value. That is
       what makes the grab cost ZERO near RAM - see hcengine.h. */

    put16(398, (unsigned int)((unsigned int)hc_power_hold_state()
                              | ((unsigned int)hc_power_nl_predict(
                                     hc_power_hold_state(), 0u) << 4)
                              | ((unsigned int)hc_power_nl_predict(
                                     hc_power_hold_state(), 1u) << 8)));

}

static unsigned char pub_stage;

unsigned char far hc_diag_publish_step(void)
{
    switch (pub_stage) {
    case 0u: pub_platform(); break;
    case 1u: pub_runtime(); break;
    case 2u: pub_live(); break;
    case 3u: hc_io_publish(io_boost_req, 0u); break;
    case 4u: hc_io_publish(io_boost_req, 1u); break;
    case 5u: hc_io_publish(io_boost_req, 2u); break;
    case 6u: update_forensics_live(0u); break;
    case 7u: update_forensics_live(1u); break;
    default:
        pub_tail();
        pub_stage = 0u;
        return 1u;
    }
    pub_stage++;
    return 0u;
}

/* The whole block at once - the boot path only, before the loop runs. */
void far hc_diag_publish(void)
{
    pub_stage = 0u;
    while (!hc_diag_publish_step()) {
    }
}

#define PRESET_V_NEVER        0u
#define PRESET_V_APPLIED      1u
#define PRESET_V_NOT_STOPPED  2u
#define PRESET_V_NO_SUCH      3u   /* includes 0 = Custom, which sets nothing */
#define PRESET_V_WRONG_BOARD  4u
#define PRESET_V_INVALID      5u   /* whole page refused - NOTHING changed    */
#define PRESET_V_BENCH_BUSY   6u
#define PRESET_V_PENDING      7u
#define PRESET_REFRESH_MS     2500u

void far hc_preset_cmd_service_cold(void);   /* public: me711_preset_apply_proof calls it */
void far hc_preset_cmd_service_cold(void)
{
    unsigned int req = get16(772);
    unsigned char id, rc, verdict;
    unsigned int faults = 0u, bad_off = 0u;

    hc_etbcal_bias_service(tick_ms);

    if (get16(770) != 0u
        && (unsigned int)(tick_ms - get16(774)) >= PRESET_REFRESH_MS) {
        put16(770, 0u);
    }
    /* A PASSED ETB CALIBRATION REACHES THE PAGE TUNERSTUDIO READS - the
       same route as a Grab: both tracks' closed/open counts, the motor
       direction the run observed, tpsCorrelation SAME, then a page re-read.
       dbwEnable is NOT touched: closed-loop DBW stays the tuner's act. */
    {
        unsigned int e[5];

        if (hc_etbcal_take(e)) {
            hc_cfg_mgr_write_u16(CAL_TPS1_MIN, e[0]);
            hc_cfg_mgr_write_u16(CAL_TPS1_MAX, e[1]);
            hc_cfg_mgr_write_u16(CAL_TPS2_MIN, e[2]);
            hc_cfg_mgr_write_u16(CAL_TPS2_MAX, e[3]);
            hc_cfg_mgr_write_u8(CFG_U_DBW_MOTOR_DIR, (unsigned char)e[4]);
            hc_cfg_mgr_write_u8(CFG_U_TPS_CORR, (unsigned char)HC_TRACK_SAME);
            put16(774, tick_ms);
            put16(770, 1u);
            /* Publication never clears sensor/bridge/supply fault latches. */
        }
        /* THE AUTOTUNE'S GAINS, the same way: DESIRED through the
           config manager, TunerStudio told to re-read, nothing burned and
           dbwEnable untouched. */
        if (hc_etbcal_tune_take(e)) {
            hc_cfg_mgr_write_u16(CAL_DBW_KP, e[0]);
            hc_cfg_mgr_write_u16(CAL_DBW_KI, e[1]);
            hc_cfg_mgr_write_u16(CAL_DBW_KD, e[2]);
            put16(774, tick_ms);
            put16(770, 1u);
        }
    }
    if (req == 0u) {
        return;
    }
    put16(772, 0u);
    id = (unsigned char)(req & 0x00FFu);

    if (trg_rpm != 0u || trg_state != TRG_NO_SIGNAL) {
        verdict = PRESET_V_NOT_STOPPED;
    } else if (hcb_state == HCB_RUNNING) {
        verdict = PRESET_V_BENCH_BUSY;
    } else if (id == 0u) {
        verdict = PRESET_V_NO_SUCH;
    } else {
        hc_tlog_on = 0u;     /* the tooth log shares the undo log's SRAM */
        rc = hc_preset_apply_engine(id, trg_rpm);
        if (rc == HC_PRESET_APPLIED) {
            verdict = PRESET_V_APPLIED;
        } else if (rc == HC_PRESET_WRONG_BOARD) {
            verdict = PRESET_V_WRONG_BOARD;
        } else if (rc == HC_PRESET_NOT_STOPPED) {
            verdict = PRESET_V_NOT_STOPPED;
        } else if (rc == HC_PRESET_PAGE_INVALID) {
            verdict = PRESET_V_INVALID;
            faults = hc_cfg_txn_faults;
            bad_off = hc_val_first_bad_offset;
        } else {
            verdict = PRESET_V_NO_SUCH;
        }
    }
    put16(766, faults);
    put16(768, bad_off);
    put16(764, (unsigned int)((unsigned int)verdict | ((unsigned int)id << 8)));
    if (verdict == PRESET_V_APPLIED) {
        put16(774, tick_ms);
        put16(770, 1u);
    }
}

void far hc_target_cmd_cold(unsigned char *p, unsigned int n)
{
    if (n < 2) {
        return;
    }
    /* WHAT IS IMPLEMENTED HERE IS WHAT THE .INI MAY OFFER, and
       tests/test_ts_commands.py enforces that in both directions. Two dead
       commands used to be advertised: '!Z' and '!z' toggled `alive_on`, a flag
       nothing had read since V23 removed banner() and step_line(). A button in
       TunerStudio that does nothing is worse than a missing one, because a
       bench operator uses it to rule something out. */
    switch (p[1]) {
    case 'A':               /* RESETDIAG_V1 never emits the unknown frame    */
        asic_isolate();
        break;
    case 'T':
        /* START ONE BENCH OUTPUT TEST. p[2] is the HC_TEST_* mode, p[3] the
           1-based channel within it. This does NOT by itself drive anything:
           hcbench_start() evaluates every invariant - RPM zero and no crank
           signal, a valid page, the supervision link
           running, a mode with a PROVEN port on this board, a channel inside
           it - and publishes exactly which ones failed. See hcbench.h. */
        if (n >= 4) {
            (void)hcbench_start(p[2], p[3]);
        }
        break;
    case 'X':
        /* ABORT. Unconditional, from any state, and it puts the pin back
           before it does anything else. A stop command that can itself be
           refused is not a stop command. */
        hcbench_abort(HCB_A_HOST);
        hc_etbcal_request(0u);           /* and an ETB calibration */
        hc_tl_request(0u, tick_ms);      /* and a tooth-profile test */
        break;
    case 'K':
        /* TOOTH PROFILE. p[2] 1 = compression profile (engine stopped;
           spark and fuel held off until the crank stops or 30 s), 2 =
           running profile (outputs untouched, 64 revolutions), 0 = abort.
           Only the request is recorded; hc_tl_service() runs it and the
           result is published at 784.. and in the extended window. */
        hc_tl_request((unsigned char)((n >= 3) ? p[2] : 0u), tick_ms);
        break;
    case 'C':
        /* AUTO CALIBRATE ETB. p[2] 1 = start, 0 = abort. Only the
           request is recorded here; hc_dbw_service() runs the procedure on
           its own raster and publishes it at 776, and hc_preset_cmd_service()
           writes a PASS into the page. No pedal, no dbwEnable needed. */
        /* p[2] 2 = the relay AUTOTUNE. V93: both live in hcetbcal.c. */
        hc_etbcal_request((unsigned char)((n >= 3) ? p[2] : 0u));
        break;
    case 'M':
        /* THE EXTERNAL-SRAM EXECUTION PROBE, and it is the one thing that
           should be run before this ECU is ever asked to erase a sector.
           hc_nvm_payload() executes from TGT_RAM_FLASHRT because the device it
           erases is the device the CPU fetches from - and that precondition
           has only ever been proven in a simulator. This proves it on the
           board, with nothing at stake: no flash access, no pin, no
           calibration change. See hcnvm.h.

           p[2] is a seed byte from the host and it is mixed with the tick, so
           the answer cannot be a constant and a stale result cannot pass.

           The safety facts are passed in the same way hc_nvm_service() takes
           them, because a board that CANNOT do this resets when asked. */
        if (n >= 3) {
            (void)hc_nvm_ramtest(
                (unsigned int)(((unsigned int)p[2] << 8)
                               | (unsigned int)(tick_ms & 0x00FFu)),
                (unsigned char)((trg_rpm == 0u)
                                && (trg_state == TRG_NO_SIGNAL)
                                && (hcb_state != HCB_RUNNING)));
        }
        break;
    case 'G':
        /* GRAB ONE CALIBRATION ENDPOINT. p[2] is the ENG_GRAB_* endpoint.
           This is rusEFI's cmd_calibrate_tps_closed / _open /
           cmd_calibrate_pedal_up / _down, and it writes the LIVE page in RAM
           and nothing else - never flash. eng_calib_grab() evaluates every
           invariant itself and publishes which one refused, so a button that
           cannot do its job says why instead of appearing to work.

           NO OUTPUT IS DRIVEN. This reads two analog channels and writes four
           bytes of the calibration page; it is not a bench command and it does
           not go through hcbench.c. */
        if (n >= 3) {
            unsigned int v = (hc_dbw_bridge_on()
                || (hc_etbcal_status() & 0x00F0u) != 0u
                || hcb_state == HCB_RUNNING) ? ENG_GRAB_RPM : eng_calib_grab(p[2]);

            /* THE GRAB REACHES THE PAGE TUNERSTUDIO READS. Until V90
               eng_calib_grab() wrote ACTIVE only (hc_cal_set_u16). A page
               READ returns DESIRED, so TunerStudio kept showing the old
               endpoints, a later DESIRED->ACTIVE apply could put them back,
               and on the AWT (2026-09-26) the operator saw the Grab buttons
               "do nothing" and typed the raw counts by hand. Now both tracks
               go through the config manager like a typed value, the pair's
               correlation becomes SAME - the only correct mode for grabbed
               endpoints, since each track is normalised closed->open
               whichever way its voltage runs - and TunerStudio is told to
               re-read the page (the preset's triggeredPageRefresh). */
            if (v == ENG_GRAB_PASS && p[2] >= 1u && p[2] <= 4u) {
                unsigned int o1, o2, oc;

                if (p[2] <= 2u) {
                    o1 = (p[2] == 1u) ? CAL_TPS1_MIN : CAL_TPS1_MAX;
                    o2 = (p[2] == 1u) ? CAL_TPS2_MIN : CAL_TPS2_MAX;
                    oc = CFG_U_TPS_CORR;
                } else {
                    o1 = (p[2] == 3u) ? CAL_PEDAL1_MIN : CAL_PEDAL1_MAX;
                    o2 = (p[2] == 3u) ? CAL_PEDAL2_MIN : CAL_PEDAL2_MAX;
                    oc = CFG_U_APP_CORR;
                }
                hc_cfg_mgr_write_u16(o1, hc_cal_u16(o1));
                hc_cfg_mgr_write_u16(o2, hc_cal_u16(o2));
                hc_cfg_mgr_write_u8(oc, (unsigned char)HC_TRACK_SAME);
                v = ENG_GRAB_PASS_SAME;
                put16(774, tick_ms);
                put16(770, 1u);
            }

            /* Packed the way every other status word on this ECU is: low byte
               the ENG_GRAB_* verdict, high byte which endpoint was asked for.
               The .ini splits it and names both halves, so nobody has to know
               that 514 is "TPS open, engine not demonstrably stopped". */
            put16(450, (unsigned int)(v | ((unsigned int)p[2] << 8)));
            put16(452, (unsigned int)(get16(452) + 1u));
        }
        break;
    case 'D':
        /* CLEAR TROUBLE CODES (OBD mode 04). Only the request is
           recorded; hc_dtc_service() clears on its next pass. A fault
           still present re-confirms after its set time. */
        hc_dtc_clear_req = 1u;
        break;
    case 'E':
        /* APPLY AN ENGINE PRESET - rusEFI's "Base Tunes" button.
           p[2], when present and non-zero, names the preset; otherwise it is
           the one the tuner selected in enginePreset (TunerStudio has already
           written that selection to DESIRED). Only the REQUEST is recorded:
           a preset stages, validates and applies a whole page, and no long
           work belongs in a command handler. hc_preset_cmd_service()
           does it from the main loop and publishes the verdict at 764. */
        {
            unsigned char id = (unsigned char)((n >= 3 && p[2] != 0u)
                ? p[2] : hc_cfg_mgr_read_u8(CFG_U_ENGINE_PRESET));

            put16(772, (unsigned int)(0x0100u | id));
            put16(764, (unsigned int)(PRESET_V_PENDING
                                      | ((unsigned int)id << 8)));
        }
        break;
    case 'W':
        /* Move the S5500 correlation window. p[2] is the first frame word.
           This is what makes the runtime-frame analog mapping measurable from
           the NORMAL image: sweep the base and read hc_s5500_idx. Bounded
           inside hc_hal_s5500_window(), so it can never read past the
           frame. */
        if (n >= 3) {
            hc_hal_s5500_window(p[2]);
        }
        break;
    default:
        break;
    }
}

