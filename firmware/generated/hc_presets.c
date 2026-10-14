/*
 * hc_presets.c - GENERATED. Do not edit.
 *
 * Provenance for every value below is in
 * tools/config_source/hanicore_presets.py, and the gaps - the values a
 * preset deliberately does NOT set because this repository cannot prove
 * them - are listed there too. Run
 *   py tools\config_source\hanicore_presets.py --gaps
 */
#ifdef HC_FAR_BRIDGE
#include "hcfarbridge.h"  /* FIRST: FAR code on ME7.1.1 (V98 NCODE relief) */
#endif
#include "hc_presets.h"
#include "hc_config_manager.h"
#include "hc_pin_descriptor.h"

/* Custom / user defined */
/* VAG 1.8T AWT (ME7.5 image only) */
/* ITEM {    2u,     4u, 1u } cylinders */
/* ITEM {    3u,     4u, 1u } strokes */
/* ITEM {    4u,     0u, 2u } tdcCylDegX10[0] */
/* ITEM {    6u,  5400u, 2u } tdcCylDegX10[1] */
/* ITEM {    8u,  1800u, 2u } tdcCylDegX10[2] */
/* ITEM {   10u,  3600u, 2u } tdcCylDegX10[3] */
/* ITEM { 2516u,     1u, 1u } cylBank[0] */
/* ITEM { 2517u,     1u, 1u } cylBank[1] */
/* ITEM { 2518u,     1u, 1u } cylBank[2] */
/* ITEM { 2519u,     1u, 1u } cylBank[3] */
/* ITEM {   20u,    60u, 2u } syTeeth */
/* ITEM {   22u,     2u, 1u } syGap */
/* ITEM {   23u,     0u, 1u } trigEdge */
/* ITEM {   24u,    25u, 2u } trigGapRatioX10 */
/* ITEM {   26u,     6u, 1u } trigMinTeeth */
/* ITEM {   27u,   200u, 1u } trigTimeoutMs */
/* ITEM { 2539u,     1u, 1u } trigDecoder */
/* ITEM {   32u,     1u, 1u } camEnable */
/* ITEM {   28u,  7500u, 2u } revMax */
/* ITEM {   30u,    80u, 2u } revMin */
/* ITEM {   34u,     0u, 1u } injChannel[0] */
/* ITEM {   35u,     3u, 1u } injChannel[1] */
/* ITEM {   36u,     1u, 1u } injChannel[2] */
/* ITEM {   37u,     2u, 1u } injChannel[3] */
/* ITEM {   42u,     0u, 1u } ignChannel[0] */
/* ITEM {   43u,     3u, 1u } ignChannel[1] */
/* ITEM {   44u,     1u, 1u } ignChannel[2] */
/* ITEM {   45u,     2u, 1u } ignChannel[3] */
/* ITEM { 2551u,    96u, 1u } injPin[0] */
/* ITEM { 2552u,    89u, 1u } injPin[1] */
/* ITEM { 2553u,    97u, 1u } injPin[2] */
/* ITEM { 2554u,    88u, 1u } injPin[3] */
/* ITEM { 2563u,   102u, 1u } ignPin[0] */
/* ITEM { 2564u,    95u, 1u } ignPin[1] */
/* ITEM { 2565u,   103u, 1u } ignPin[2] */
/* ITEM { 2566u,    94u, 1u } ignPin[3] */
/* ITEM { 2548u,    82u, 1u } pinCrank */
/* ITEM { 2549u,    86u, 1u } pinCam1 */
/* ITEM { 2575u,   101u, 1u } pinMap */
/* ITEM { 2577u,    93u, 1u } pinClt */
/* ITEM { 2579u,    92u, 1u } pinTps1 */
/* ITEM { 2580u,    84u, 1u } pinTps2 */
/* ITEM { 2581u,    35u, 1u } pinApp1 */
/* ITEM { 2582u,    34u, 1u } pinApp2 */
/* ITEM { 2583u,    26u, 1u } pinVbat */
/* ITEM { 2591u,    65u, 1u } pinFuelPump */
/* ITEM { 2593u,   104u, 1u } pinBoost */
/* ITEM { 2587u,    29u, 1u } pinMaf */
/* ITEM { 2620u,     0u, 1u } tpsCorrelation */
/* ITEM { 2621u,     0u, 1u } appCorrelation */
/* ITEM { 2636u,  1470u, 2u } stoichAfrX100 */
static const unsigned char HC_PRESET_MEM runs_vag_18t_me75_awt[] = {
    0x00u, 0x02u, 10u, /* offset 2 */
        0x04u, 0x04u, 0x00u, 0x00u, 0x15u, 0x18u, 0x07u, 0x08u, 0x0Eu, 0x10u,
    0x09u, 0xD4u, 4u, /* offset 2516 */
        0x01u, 0x01u, 0x01u, 0x01u,
    0x00u, 0x14u, 8u, /* offset 20 */
        0x00u, 0x3Cu, 0x02u, 0x00u, 0x00u, 0x19u, 0x06u, 0xC8u,
    0x09u, 0xEBu, 1u, /* offset 2539 */
        0x01u,
    0x00u, 0x20u, 1u, /* offset 32 */
        0x01u,
    0x00u, 0x1Cu, 4u, /* offset 28 */
        0x1Du, 0x4Cu, 0x00u, 0x50u,
    0x00u, 0x22u, 4u, /* offset 34 */
        0x00u, 0x03u, 0x01u, 0x02u,
    0x00u, 0x2Au, 4u, /* offset 42 */
        0x00u, 0x03u, 0x01u, 0x02u,
    0x09u, 0xF7u, 4u, /* offset 2551 */
        0x60u, 0x59u, 0x61u, 0x58u,
    0x0Au, 0x03u, 4u, /* offset 2563 */
        0x66u, 0x5Fu, 0x67u, 0x5Eu,
    0x09u, 0xF4u, 2u, /* offset 2548 */
        0x52u, 0x56u,
    0x0Au, 0x0Fu, 1u, /* offset 2575 */
        0x65u,
    0x0Au, 0x11u, 1u, /* offset 2577 */
        0x5Du,
    0x0Au, 0x13u, 5u, /* offset 2579 */
        0x5Cu, 0x54u, 0x23u, 0x22u, 0x1Au,
    0x0Au, 0x1Fu, 1u, /* offset 2591 */
        0x41u,
    0x0Au, 0x21u, 1u, /* offset 2593 */
        0x68u,
    0x0Au, 0x1Bu, 1u, /* offset 2587 */
        0x1Du,
    0x0Au, 0x3Cu, 2u, /* offset 2620 */
        0x00u, 0x00u,
    0x0Au, 0x4Cu, 2u, /* offset 2636 */
        0x05u, 0xBEu,
};

/* Porsche V8 donor - incomplete, refused */
/* ITEM {    2u,     8u, 1u } cylinders */
/* ITEM {    3u,     4u, 1u } strokes */
/* ITEM {   20u,    60u, 2u } syTeeth */
/* ITEM {   22u,     2u, 1u } syGap */
/* ITEM {   23u,     0u, 1u } trigEdge */
/* ITEM {   24u,    20u, 2u } trigGapRatioX10 */
/* ITEM { 2539u,     3u, 1u } trigDecoder */
/* ITEM {   32u,     1u, 1u } camEnable */
/* ITEM { 2538u,     1u, 1u } syncMode */
/* ITEM { 2548u,    82u, 1u } pinCrank */
/* ITEM { 2549u,    86u, 1u } pinCam1 */
/* ITEM { 2550u,    87u, 1u } pinCam2 */
/* ITEM { 2579u,    92u, 1u } pinTps1 */
/* ITEM { 2580u,    84u, 1u } pinTps2 */
/* ITEM { 2581u,    35u, 1u } pinApp1 */
/* ITEM { 2582u,    34u, 1u } pinApp2 */
/* ITEM { 2636u,  1470u, 2u } stoichAfrX100 */
/* ITEM { 2630u,     0u, 1u } lambda1Source */
/* ITEM { 2633u,     0u, 1u } lambda2Source */
/* ITEM { 2681u,     0u, 1u } lambdaHeatPolicy */
static const unsigned char HC_PRESET_MEM runs_bosch_me711[] = {
    0x00u, 0x02u, 2u, /* offset 2 */
        0x08u, 0x04u,
    0x00u, 0x14u, 6u, /* offset 20 */
        0x00u, 0x3Cu, 0x02u, 0x00u, 0x00u, 0x14u,
    0x09u, 0xEBu, 1u, /* offset 2539 */
        0x03u,
    0x00u, 0x20u, 1u, /* offset 32 */
        0x01u,
    0x09u, 0xEAu, 1u, /* offset 2538 */
        0x01u,
    0x09u, 0xF4u, 3u, /* offset 2548 */
        0x52u, 0x56u, 0x57u,
    0x0Au, 0x13u, 4u, /* offset 2579 */
        0x5Cu, 0x54u, 0x23u, 0x22u,
    0x0Au, 0x4Cu, 2u, /* offset 2636 */
        0x05u, 0xBEu,
    0x0Au, 0x46u, 1u, /* offset 2630 */
        0x00u,
    0x0Au, 0x49u, 1u, /* offset 2633 */
        0x00u,
    0x0Au, 0x79u, 1u, /* offset 2681 */
        0x00u,
};

/* Board defaults - routing only, no engine */
/* ITEM { 2548u,    82u, 1u } pinCrank */
/* ITEM { 2549u,    86u, 1u } pinCam1 */
/* ITEM { 2550u,    87u, 1u } pinCam2 */
/* ITEM { 2538u,     1u, 1u } syncMode */
/* ITEM { 2579u,    92u, 1u } pinTps1 */
/* ITEM { 2580u,    84u, 1u } pinTps2 */
/* ITEM { 2581u,    35u, 1u } pinApp1 */
/* ITEM { 2582u,    34u, 1u } pinApp2 */
/* ITEM { 2591u,    65u, 1u } pinFuelPump */
/* ITEM { 2678u,     4u, 1u } s5500WindowBase */
/* ITEM { 2865u,    47u, 1u } pinMil */
/* ITEM { 2864u,     0u, 1u } celEnable */
/* ITEM { 2866u,     1u, 1u } celTestEnable */
/* ITEM { 2868u,  3000u, 2u } celTestOnMs */
/* ITEM { 2870u,  1000u, 2u } celTestGapMs */
/* ITEM { 2980u,   250u, 2u } vvtFreqHz */
static const unsigned char HC_PRESET_MEM runs_bosch_me711_board[] = {
    0x09u, 0xF4u, 3u, /* offset 2548 */
        0x52u, 0x56u, 0x57u,
    0x09u, 0xEAu, 1u, /* offset 2538 */
        0x01u,
    0x0Au, 0x13u, 4u, /* offset 2579 */
        0x5Cu, 0x54u, 0x23u, 0x22u,
    0x0Au, 0x1Fu, 1u, /* offset 2591 */
        0x41u,
    0x0Au, 0x76u, 1u, /* offset 2678 */
        0x04u,
    0x0Bu, 0x31u, 1u, /* offset 2865 */
        0x2Fu,
    0x0Bu, 0x30u, 1u, /* offset 2864 */
        0x00u,
    0x0Bu, 0x32u, 1u, /* offset 2866 */
        0x01u,
    0x0Bu, 0x34u, 4u, /* offset 2868 */
        0x0Bu, 0xB8u, 0x03u, 0xE8u,
    0x0Bu, 0xA4u, 2u, /* offset 2980 */
        0x00u, 0xFAu,
};

/* VAG 1.8T DBW (AWT) */
/* ITEM {    2u,     4u, 1u } cylinders */
/* ITEM {    3u,     4u, 1u } strokes */
/* ITEM {    4u,     0u, 2u } tdcCylDegX10[0] */
/* ITEM {    6u,  5400u, 2u } tdcCylDegX10[1] */
/* ITEM {    8u,  1800u, 2u } tdcCylDegX10[2] */
/* ITEM {   10u,  3600u, 2u } tdcCylDegX10[3] */
/* ITEM { 3306u,     1u, 1u } firingOrder */
/* ITEM { 2516u,     1u, 1u } cylBank[0] */
/* ITEM { 2517u,     1u, 1u } cylBank[1] */
/* ITEM { 2518u,     1u, 1u } cylBank[2] */
/* ITEM { 2519u,     1u, 1u } cylBank[3] */
/* ITEM {   20u,    60u, 2u } syTeeth */
/* ITEM {   22u,     2u, 1u } syGap */
/* ITEM {   23u,     0u, 1u } trigEdge */
/* ITEM {   24u,    25u, 2u } trigGapRatioX10 */
/* ITEM {   26u,     6u, 1u } trigMinTeeth */
/* ITEM {   27u,   200u, 1u } trigTimeoutMs */
/* ITEM { 2539u,     1u, 1u } trigDecoder */
/* ITEM {   32u,     1u, 1u } camEnable */
/* ITEM { 2538u,     2u, 1u } syncMode */
/* ITEM {   28u,  7500u, 2u } revMax */
/* ITEM {   30u,    80u, 2u } revMin */
/* ITEM { 2551u,    96u, 1u } injPin[0] */
/* ITEM { 2552u,    89u, 1u } injPin[1] */
/* ITEM { 2553u,    97u, 1u } injPin[2] */
/* ITEM { 2554u,    88u, 1u } injPin[3] */
/* ITEM { 2555u,   255u, 1u } injPin[4] */
/* ITEM { 2556u,   255u, 1u } injPin[5] */
/* ITEM { 2557u,   255u, 1u } injPin[6] */
/* ITEM { 2558u,   255u, 1u } injPin[7] */
/* ITEM { 2559u,   255u, 1u } injPin[8] */
/* ITEM { 2560u,   255u, 1u } injPin[9] */
/* ITEM { 2561u,   255u, 1u } injPin[10] */
/* ITEM { 2562u,   255u, 1u } injPin[11] */
/* ITEM { 2563u,   102u, 1u } ignPin[0] */
/* ITEM { 2564u,    95u, 1u } ignPin[1] */
/* ITEM { 2565u,   103u, 1u } ignPin[2] */
/* ITEM { 2566u,    94u, 1u } ignPin[3] */
/* ITEM { 2567u,   255u, 1u } ignPin[4] */
/* ITEM { 2568u,   255u, 1u } ignPin[5] */
/* ITEM { 2569u,   255u, 1u } ignPin[6] */
/* ITEM { 2570u,   255u, 1u } ignPin[7] */
/* ITEM { 2571u,   255u, 1u } ignPin[8] */
/* ITEM { 2572u,   255u, 1u } ignPin[9] */
/* ITEM { 2573u,   255u, 1u } ignPin[10] */
/* ITEM { 2574u,   255u, 1u } ignPin[11] */
/* ITEM {   34u,     0u, 1u } injChannel[0] */
/* ITEM {   35u,     3u, 1u } injChannel[1] */
/* ITEM {   36u,     1u, 1u } injChannel[2] */
/* ITEM {   37u,     2u, 1u } injChannel[3] */
/* ITEM {   42u,     0u, 1u } ignChannel[0] */
/* ITEM {   43u,     3u, 1u } ignChannel[1] */
/* ITEM {   44u,     1u, 1u } ignChannel[2] */
/* ITEM {   45u,     2u, 1u } ignChannel[3] */
/* ITEM { 2548u,    82u, 1u } pinCrank */
/* ITEM { 2549u,    86u, 1u } pinCam1 */
/* ITEM { 2550u,   255u, 1u } pinCam2 */
/* ITEM { 2579u,    92u, 1u } pinTps1 */
/* ITEM { 2580u,    84u, 1u } pinTps2 */
/* ITEM { 2581u,    35u, 1u } pinApp1 */
/* ITEM { 2582u,    34u, 1u } pinApp2 */
/* ITEM { 2575u,   101u, 1u } pinMap */
/* ITEM { 2577u,    93u, 1u } pinClt */
/* ITEM { 2578u,    26u, 1u } pinIat */
/* ITEM { 2536u,     2u, 1u } injStrategy */
/* ITEM { 2537u,     2u, 1u } ignStrategy */
/* ITEM { 2730u,     1u, 1u } injTimingMode */
/* ITEM {   58u,  4400u, 2u } injStartDegX10 */
/* ITEM { 2630u,     1u, 1u } lambda1Source */
/* ITEM { 2681u,     1u, 1u } lambdaHeatPolicy */
/* ITEM { 2631u,     1u, 1u } lambda1Bank */
/* ITEM { 2626u,    15u, 2u } lambda1CylMask */
/* ITEM { 2633u,     0u, 1u } lambda2Source */
/* ITEM { 2591u,    65u, 1u } pinFuelPump */
/* ITEM { 1152u,   182u, 2u } cltSensAx[0] */
/* ITEM { 1154u,   238u, 2u } cltSensAx[1] */
/* ITEM { 1156u,   284u, 2u } cltSensAx[2] */
/* ITEM { 1158u,   337u, 2u } cltSensAx[3] */
/* ITEM { 1160u,   428u, 2u } cltSensAx[4] */
/* ITEM { 1162u,   533u, 2u } cltSensAx[5] */
/* ITEM { 1164u,   680u, 2u } cltSensAx[6] */
/* ITEM { 1166u,   751u, 2u } cltSensAx[7] */
/* ITEM { 1168u,   783u, 2u } cltSensAx[8] */
/* ITEM { 1170u,   812u, 2u } cltSensAx[9] */
/* ITEM { 1172u,   866u, 2u } cltSensAx[10] */
/* ITEM { 1174u,   908u, 2u } cltSensAx[11] */
/* ITEM { 1176u,   942u, 2u } cltSensAx[12] */
/* ITEM { 1178u,   967u, 2u } cltSensAx[13] */
/* ITEM { 1180u,   996u, 2u } cltSensAx[14] */
/* ITEM { 1182u,  1008u, 2u } cltSensAx[15] */
/* ITEM { 1184u, 11432u, 2u } cltSensVal[0] */
/* ITEM { 1186u, 11300u, 2u } cltSensVal[1] */
/* ITEM { 1188u, 11200u, 2u } cltSensVal[2] */
/* ITEM { 1190u, 11100u, 2u } cltSensVal[3] */
/* ITEM { 1192u, 10950u, 2u } cltSensVal[4] */
/* ITEM { 1194u, 10800u, 2u } cltSensVal[5] */
/* ITEM { 1196u, 10600u, 2u } cltSensVal[6] */
/* ITEM { 1198u, 10500u, 2u } cltSensVal[7] */
/* ITEM { 1200u, 10450u, 2u } cltSensVal[8] */
/* ITEM { 1202u, 10400u, 2u } cltSensVal[9] */
/* ITEM { 1204u, 10300u, 2u } cltSensVal[10] */
/* ITEM { 1206u, 10200u, 2u } cltSensVal[11] */
/* ITEM { 1208u, 10100u, 2u } cltSensVal[12] */
/* ITEM { 1210u, 10000u, 2u } cltSensVal[13] */
/* ITEM { 1212u,  9800u, 2u } cltSensVal[14] */
/* ITEM { 1214u,  9600u, 2u } cltSensVal[15] */
/* ITEM { 1254u,    28u, 2u } iatSensAx[0] */
/* ITEM { 1256u,    48u, 2u } iatSensAx[1] */
/* ITEM { 1258u,    64u, 2u } iatSensAx[2] */
/* ITEM { 1260u,    92u, 2u } iatSensAx[3] */
/* ITEM { 1262u,   116u, 2u } iatSensAx[4] */
/* ITEM { 1264u,   148u, 2u } iatSensAx[5] */
/* ITEM { 1266u,   192u, 2u } iatSensAx[6] */
/* ITEM { 1268u,   244u, 2u } iatSensAx[7] */
/* ITEM { 1270u,   308u, 2u } iatSensAx[8] */
/* ITEM { 1272u,   372u, 2u } iatSensAx[9] */
/* ITEM { 1274u,   432u, 2u } iatSensAx[10] */
/* ITEM { 1276u,   572u, 2u } iatSensAx[11] */
/* ITEM { 1278u,   664u, 2u } iatSensAx[12] */
/* ITEM { 1280u,   744u, 2u } iatSensAx[13] */
/* ITEM { 1282u,   864u, 2u } iatSensAx[14] */
/* ITEM { 1284u,   900u, 2u } iatSensAx[15] */
/* ITEM { 1286u, 11403u, 2u } iatSensVal[0] */
/* ITEM { 1288u, 11200u, 2u } iatSensVal[1] */
/* ITEM { 1290u, 11050u, 2u } iatSensVal[2] */
/* ITEM { 1292u, 10900u, 2u } iatSensVal[3] */
/* ITEM { 1294u, 10803u, 2u } iatSensVal[4] */
/* ITEM { 1296u, 10698u, 2u } iatSensVal[5] */
/* ITEM { 1298u, 10600u, 2u } iatSensVal[6] */
/* ITEM { 1300u, 10503u, 2u } iatSensVal[7] */
/* ITEM { 1302u, 10398u, 2u } iatSensVal[8] */
/* ITEM { 1304u, 10323u, 2u } iatSensVal[9] */
/* ITEM { 1306u, 10248u, 2u } iatSensVal[10] */
/* ITEM { 1308u, 10098u, 2u } iatSensVal[11] */
/* ITEM { 1310u, 10000u, 2u } iatSensVal[12] */
/* ITEM { 1312u,  9902u, 2u } iatSensVal[13] */
/* ITEM { 1314u,  9700u, 2u } iatSensVal[14] */
/* ITEM { 1316u,  9602u, 2u } iatSensVal[15] */
/* ITEM { 2593u,   104u, 1u } pinBoost */
/* ITEM { 2590u,    23u, 1u } pinMainRelay */
/* ITEM {   73u,     2u, 1u } mainRelayModeCfg */
/* ITEM { 2510u,  1781u, 2u } displacementCc */
/* ITEM { 2638u,   301u, 2u } injFlowCcMin */
/* ITEM { 2640u,   300u, 2u } injRefPressureKpa */
/* ITEM { 1136u,  1877u, 2u } deadtimeVal[0] */
/* ITEM { 1138u,  1850u, 2u } deadtimeVal[1] */
/* ITEM { 1140u,  1085u, 2u } deadtimeVal[2] */
/* ITEM { 1142u,   685u, 2u } deadtimeVal[3] */
/* ITEM { 1144u,   557u, 2u } deadtimeVal[4] */
/* ITEM { 1146u,   437u, 2u } deadtimeVal[5] */
/* ITEM { 1148u,   267u, 2u } deadtimeVal[6] */
/* ITEM { 1150u,   267u, 2u } deadtimeVal[7] */
/* ITEM { 1120u,  1000u, 2u } dwellBattVal[0] */
/* ITEM { 1122u,   800u, 2u } dwellBattVal[1] */
/* ITEM { 1124u,   420u, 2u } dwellBattVal[2] */
/* ITEM { 1126u,   320u, 2u } dwellBattVal[3] */
/* ITEM { 1128u,   290u, 2u } dwellBattVal[4] */
/* ITEM { 1130u,   270u, 2u } dwellBattVal[5] */
/* ITEM { 1132u,   240u, 2u } dwellBattVal[6] */
/* ITEM { 1134u,   200u, 2u } dwellBattVal[7] */
/* ITEM { 1104u,   598u, 2u } dwellBattAx[0] */
/* ITEM { 1106u,   803u, 2u } dwellBattAx[1] */
/* ITEM { 1108u,  1000u, 2u } dwellBattAx[2] */
/* ITEM { 1110u,  1197u, 2u } dwellBattAx[3] */
/* ITEM { 1112u,  1302u, 2u } dwellBattAx[4] */
/* ITEM { 1114u,  1401u, 2u } dwellBattAx[5] */
/* ITEM { 1116u,  1598u, 2u } dwellBattAx[6] */
/* ITEM { 1118u,  1795u, 2u } dwellBattAx[7] */
/* ITEM { 2642u,     0u, 2u } crankingDwellMsX100 */
/* ITEM { 1216u,     0u, 2u } mapSensOff */
/* ITEM { 1218u,  2642u, 2u } mapSensGrd */
/* ITEM { 1236u,     1u, 1u } loadSource */
/* ITEM { 3710u,     0u, 1u } fuelModel */
/* ITEM { 3711u,     2u, 1u } pressureRole */
/* ITEM { 3713u,     2u, 1u } ambientSource */
/* ITEM {  640u,   500u, 2u } fuelRpmAx[0] */
/* ITEM {  642u,   950u, 2u } fuelRpmAx[1] */
/* ITEM {  644u,  1400u, 2u } fuelRpmAx[2] */
/* ITEM {  646u,  1850u, 2u } fuelRpmAx[3] */
/* ITEM {  648u,  2300u, 2u } fuelRpmAx[4] */
/* ITEM {  650u,  2750u, 2u } fuelRpmAx[5] */
/* ITEM {  652u,  3200u, 2u } fuelRpmAx[6] */
/* ITEM {  654u,  3650u, 2u } fuelRpmAx[7] */
/* ITEM {  656u,  4100u, 2u } fuelRpmAx[8] */
/* ITEM {  658u,  4550u, 2u } fuelRpmAx[9] */
/* ITEM {  660u,  5000u, 2u } fuelRpmAx[10] */
/* ITEM {  662u,  5450u, 2u } fuelRpmAx[11] */
/* ITEM {  664u,  5900u, 2u } fuelRpmAx[12] */
/* ITEM {  666u,  6350u, 2u } fuelRpmAx[13] */
/* ITEM {  668u,  6800u, 2u } fuelRpmAx[14] */
/* ITEM {  670u,  7250u, 2u } fuelRpmAx[15] */
/* ITEM {  672u,     0u, 2u } fuelLoadAx[0] */
/* ITEM {  674u,    10u, 2u } fuelLoadAx[1] */
/* ITEM {  676u,    20u, 2u } fuelLoadAx[2] */
/* ITEM {  678u,    30u, 2u } fuelLoadAx[3] */
/* ITEM {  680u,    40u, 2u } fuelLoadAx[4] */
/* ITEM {  682u,    55u, 2u } fuelLoadAx[5] */
/* ITEM {  684u,    70u, 2u } fuelLoadAx[6] */
/* ITEM {  686u,   100u, 2u } fuelLoadAx[7] */
/* ITEM {  688u,   130u, 2u } fuelLoadAx[8] */
/* ITEM {  690u,   160u, 2u } fuelLoadAx[9] */
/* ITEM {  692u,   200u, 2u } fuelLoadAx[10] */
/* ITEM {  694u,   250u, 2u } fuelLoadAx[11] */
/* ITEM {  696u,   300u, 2u } fuelLoadAx[12] */
/* ITEM {  698u,   400u, 2u } fuelLoadAx[13] */
/* ITEM {  700u,   500u, 2u } fuelLoadAx[14] */
/* ITEM {  702u,  1000u, 2u } fuelLoadAx[15] */
/* ITEM {  128u,    90u, 2u } veTable[0] */
/* ITEM {  130u,    48u, 2u } veTable[1] */
/* ITEM {  132u,    32u, 2u } veTable[2] */
/* ITEM {  134u,    24u, 2u } veTable[3] */
/* ITEM {  136u,    20u, 2u } veTable[4] */
/* ITEM {  138u,    16u, 2u } veTable[5] */
/* ITEM {  140u,    14u, 2u } veTable[6] */
/* ITEM {  142u,    12u, 2u } veTable[7] */
/* ITEM {  144u,    11u, 2u } veTable[8] */
/* ITEM {  146u,    10u, 2u } veTable[9] */
/* ITEM {  148u,     9u, 2u } veTable[10] */
/* ITEM {  150u,     8u, 2u } veTable[11] */
/* ITEM {  152u,     8u, 2u } veTable[12] */
/* ITEM {  154u,     7u, 2u } veTable[13] */
/* ITEM {  156u,     7u, 2u } veTable[14] */
/* ITEM {  158u,     6u, 2u } veTable[15] */
/* ITEM {  160u,   181u, 2u } veTable[16] */
/* ITEM {  162u,    95u, 2u } veTable[17] */
/* ITEM {  164u,    64u, 2u } veTable[18] */
/* ITEM {  166u,    48u, 2u } veTable[19] */
/* ITEM {  168u,    39u, 2u } veTable[20] */
/* ITEM {  170u,    32u, 2u } veTable[21] */
/* ITEM {  172u,    28u, 2u } veTable[22] */
/* ITEM {  174u,    24u, 2u } veTable[23] */
/* ITEM {  176u,    22u, 2u } veTable[24] */
/* ITEM {  178u,    20u, 2u } veTable[25] */
/* ITEM {  180u,    18u, 2u } veTable[26] */
/* ITEM {  182u,    16u, 2u } veTable[27] */
/* ITEM {  184u,    15u, 2u } veTable[28] */
/* ITEM {  186u,    14u, 2u } veTable[29] */
/* ITEM {  188u,    13u, 2u } veTable[30] */
/* ITEM {  190u,    12u, 2u } veTable[31] */
/* ITEM {  192u,   301u, 2u } veTable[32] */
/* ITEM {  194u,   159u, 2u } veTable[33] */
/* ITEM {  196u,   106u, 2u } veTable[34] */
/* ITEM {  198u,    79u, 2u } veTable[35] */
/* ITEM {  200u,    64u, 2u } veTable[36] */
/* ITEM {  202u,    53u, 2u } veTable[37] */
/* ITEM {  204u,    46u, 2u } veTable[38] */
/* ITEM {  206u,    40u, 2u } veTable[39] */
/* ITEM {  208u,    36u, 2u } veTable[40] */
/* ITEM {  210u,    32u, 2u } veTable[41] */
/* ITEM {  212u,    29u, 2u } veTable[42] */
/* ITEM {  214u,    27u, 2u } veTable[43] */
/* ITEM {  216u,    25u, 2u } veTable[44] */
/* ITEM {  218u,    23u, 2u } veTable[45] */
/* ITEM {  220u,    21u, 2u } veTable[46] */
/* ITEM {  222u,    20u, 2u } veTable[47] */
/* ITEM {  224u,   444u, 2u } veTable[48] */
/* ITEM {  226u,   234u, 2u } veTable[49] */
/* ITEM {  228u,   157u, 2u } veTable[50] */
/* ITEM {  230u,   118u, 2u } veTable[51] */
/* ITEM {  232u,    95u, 2u } veTable[52] */
/* ITEM {  234u,    79u, 2u } veTable[53] */
/* ITEM {  236u,    68u, 2u } veTable[54] */
/* ITEM {  238u,    60u, 2u } veTable[55] */
/* ITEM {  240u,    53u, 2u } veTable[56] */
/* ITEM {  242u,    48u, 2u } veTable[57] */
/* ITEM {  244u,    44u, 2u } veTable[58] */
/* ITEM {  246u,    40u, 2u } veTable[59] */
/* ITEM {  248u,    37u, 2u } veTable[60] */
/* ITEM {  250u,    34u, 2u } veTable[61] */
/* ITEM {  252u,    32u, 2u } veTable[62] */
/* ITEM {  254u,    30u, 2u } veTable[63] */
/* ITEM {  256u,   557u, 2u } veTable[64] */
/* ITEM {  258u,   309u, 2u } veTable[65] */
/* ITEM {  260u,   209u, 2u } veTable[66] */
/* ITEM {  262u,   157u, 2u } veTable[67] */
/* ITEM {  264u,   126u, 2u } veTable[68] */
/* ITEM {  266u,   105u, 2u } veTable[69] */
/* ITEM {  268u,    90u, 2u } veTable[70] */
/* ITEM {  270u,    79u, 2u } veTable[71] */
/* ITEM {  272u,    71u, 2u } veTable[72] */
/* ITEM {  274u,    64u, 2u } veTable[73] */
/* ITEM {  276u,    58u, 2u } veTable[74] */
/* ITEM {  278u,    53u, 2u } veTable[75] */
/* ITEM {  280u,    49u, 2u } veTable[76] */
/* ITEM {  282u,    46u, 2u } veTable[77] */
/* ITEM {  284u,    43u, 2u } veTable[78] */
/* ITEM {  286u,    40u, 2u } veTable[79] */
/* ITEM {  288u,   680u, 2u } veTable[80] */
/* ITEM {  290u,   448u, 2u } veTable[81] */
/* ITEM {  292u,   302u, 2u } veTable[82] */
/* ITEM {  294u,   226u, 2u } veTable[83] */
/* ITEM {  296u,   181u, 2u } veTable[84] */
/* ITEM {  298u,   152u, 2u } veTable[85] */
/* ITEM {  300u,   130u, 2u } veTable[86] */
/* ITEM {  302u,   113u, 2u } veTable[87] */
/* ITEM {  304u,   100u, 2u } veTable[88] */
/* ITEM {  306u,    90u, 2u } veTable[89] */
/* ITEM {  308u,    83u, 2u } veTable[90] */
/* ITEM {  310u,    76u, 2u } veTable[91] */
/* ITEM {  312u,    70u, 2u } veTable[92] */
/* ITEM {  314u,    65u, 2u } veTable[93] */
/* ITEM {  316u,    61u, 2u } veTable[94] */
/* ITEM {  318u,    57u, 2u } veTable[95] */
/* ITEM {  320u,   741u, 2u } veTable[96] */
/* ITEM {  322u,   559u, 2u } veTable[97] */
/* ITEM {  324u,   395u, 2u } veTable[98] */
/* ITEM {  326u,   296u, 2u } veTable[99] */
/* ITEM {  328u,   237u, 2u } veTable[100] */
/* ITEM {  330u,   198u, 2u } veTable[101] */
/* ITEM {  332u,   169u, 2u } veTable[102] */
/* ITEM {  334u,   146u, 2u } veTable[103] */
/* ITEM {  336u,   129u, 2u } veTable[104] */
/* ITEM {  338u,   117u, 2u } veTable[105] */
/* ITEM {  340u,   108u, 2u } veTable[106] */
/* ITEM {  342u,    99u, 2u } veTable[107] */
/* ITEM {  344u,    91u, 2u } veTable[108] */
/* ITEM {  346u,    85u, 2u } veTable[109] */
/* ITEM {  348u,    79u, 2u } veTable[110] */
/* ITEM {  350u,    74u, 2u } veTable[111] */
/* ITEM {  352u,   799u, 2u } veTable[112] */
/* ITEM {  354u,   695u, 2u } veTable[113] */
/* ITEM {  356u,   567u, 2u } veTable[114] */
/* ITEM {  358u,   444u, 2u } veTable[115] */
/* ITEM {  360u,   358u, 2u } veTable[116] */
/* ITEM {  362u,   302u, 2u } veTable[117] */
/* ITEM {  364u,   260u, 2u } veTable[118] */
/* ITEM {  366u,   228u, 2u } veTable[119] */
/* ITEM {  368u,   203u, 2u } veTable[120] */
/* ITEM {  370u,   181u, 2u } veTable[121] */
/* ITEM {  372u,   163u, 2u } veTable[122] */
/* ITEM {  374u,   148u, 2u } veTable[123] */
/* ITEM {  376u,   136u, 2u } veTable[124] */
/* ITEM {  378u,   126u, 2u } veTable[125] */
/* ITEM {  380u,   117u, 2u } veTable[126] */
/* ITEM {  382u,   110u, 2u } veTable[127] */
/* ITEM {  384u,   820u, 2u } veTable[128] */
/* ITEM {  386u,   758u, 2u } veTable[129] */
/* ITEM {  388u,   671u, 2u } veTable[130] */
/* ITEM {  390u,   578u, 2u } veTable[131] */
/* ITEM {  392u,   492u, 2u } veTable[132] */
/* ITEM {  394u,   423u, 2u } veTable[133] */
/* ITEM {  396u,   369u, 2u } veTable[134] */
/* ITEM {  398u,   325u, 2u } veTable[135] */
/* ITEM {  400u,   290u, 2u } veTable[136] */
/* ITEM {  402u,   260u, 2u } veTable[137] */
/* ITEM {  404u,   235u, 2u } veTable[138] */
/* ITEM {  406u,   212u, 2u } veTable[139] */
/* ITEM {  408u,   192u, 2u } veTable[140] */
/* ITEM {  410u,   178u, 2u } veTable[141] */
/* ITEM {  412u,   166u, 2u } veTable[142] */
/* ITEM {  414u,   156u, 2u } veTable[143] */
/* ITEM {  416u,   833u, 2u } veTable[144] */
/* ITEM {  418u,   799u, 2u } veTable[145] */
/* ITEM {  420u,   745u, 2u } veTable[146] */
/* ITEM {  422u,   684u, 2u } veTable[147] */
/* ITEM {  424u,   611u, 2u } veTable[148] */
/* ITEM {  426u,   541u, 2u } veTable[149] */
/* ITEM {  428u,   479u, 2u } veTable[150] */
/* ITEM {  430u,   428u, 2u } veTable[151] */
/* ITEM {  432u,   387u, 2u } veTable[152] */
/* ITEM {  434u,   351u, 2u } veTable[153] */
/* ITEM {  436u,   322u, 2u } veTable[154] */
/* ITEM {  438u,   291u, 2u } veTable[155] */
/* ITEM {  440u,   264u, 2u } veTable[156] */
/* ITEM {  442u,   244u, 2u } veTable[157] */
/* ITEM {  444u,   228u, 2u } veTable[158] */
/* ITEM {  446u,   214u, 2u } veTable[159] */
/* ITEM {  448u,   841u, 2u } veTable[160] */
/* ITEM {  450u,   826u, 2u } veTable[161] */
/* ITEM {  452u,   798u, 2u } veTable[162] */
/* ITEM {  454u,   767u, 2u } veTable[163] */
/* ITEM {  456u,   718u, 2u } veTable[164] */
/* ITEM {  458u,   665u, 2u } veTable[165] */
/* ITEM {  460u,   613u, 2u } veTable[166] */
/* ITEM {  462u,   561u, 2u } veTable[167] */
/* ITEM {  464u,   514u, 2u } veTable[168] */
/* ITEM {  466u,   473u, 2u } veTable[169] */
/* ITEM {  468u,   437u, 2u } veTable[170] */
/* ITEM {  470u,   397u, 2u } veTable[171] */
/* ITEM {  472u,   363u, 2u } veTable[172] */
/* ITEM {  474u,   337u, 2u } veTable[173] */
/* ITEM {  476u,   315u, 2u } veTable[174] */
/* ITEM {  478u,   295u, 2u } veTable[175] */
/* ITEM {  480u,   845u, 2u } veTable[176] */
/* ITEM {  482u,   841u, 2u } veTable[177] */
/* ITEM {  484u,   829u, 2u } veTable[178] */
/* ITEM {  486u,   819u, 2u } veTable[179] */
/* ITEM {  488u,   796u, 2u } veTable[180] */
/* ITEM {  490u,   773u, 2u } veTable[181] */
/* ITEM {  492u,   750u, 2u } veTable[182] */
/* ITEM {  494u,   715u, 2u } veTable[183] */
/* ITEM {  496u,   678u, 2u } veTable[184] */
/* ITEM {  498u,   640u, 2u } veTable[185] */
/* ITEM {  500u,   596u, 2u } veTable[186] */
/* ITEM {  502u,   551u, 2u } veTable[187] */
/* ITEM {  504u,   509u, 2u } veTable[188] */
/* ITEM {  506u,   474u, 2u } veTable[189] */
/* ITEM {  508u,   443u, 2u } veTable[190] */
/* ITEM {  510u,   416u, 2u } veTable[191] */
/* ITEM {  512u,   847u, 2u } veTable[192] */
/* ITEM {  514u,   846u, 2u } veTable[193] */
/* ITEM {  516u,   840u, 2u } veTable[194] */
/* ITEM {  518u,   838u, 2u } veTable[195] */
/* ITEM {  520u,   825u, 2u } veTable[196] */
/* ITEM {  522u,   814u, 2u } veTable[197] */
/* ITEM {  524u,   804u, 2u } veTable[198] */
/* ITEM {  526u,   778u, 2u } veTable[199] */
/* ITEM {  528u,   752u, 2u } veTable[200] */
/* ITEM {  530u,   732u, 2u } veTable[201] */
/* ITEM {  532u,   708u, 2u } veTable[202] */
/* ITEM {  534u,   669u, 2u } veTable[203] */
/* ITEM {  536u,   632u, 2u } veTable[204] */
/* ITEM {  538u,   599u, 2u } veTable[205] */
/* ITEM {  540u,   569u, 2u } veTable[206] */
/* ITEM {  542u,   540u, 2u } veTable[207] */
/* ITEM {  544u,   848u, 2u } veTable[208] */
/* ITEM {  546u,   852u, 2u } veTable[209] */
/* ITEM {  548u,   851u, 2u } veTable[210] */
/* ITEM {  550u,   857u, 2u } veTable[211] */
/* ITEM {  552u,   856u, 2u } veTable[212] */
/* ITEM {  554u,   860u, 2u } veTable[213] */
/* ITEM {  556u,   868u, 2u } veTable[214] */
/* ITEM {  558u,   859u, 2u } veTable[215] */
/* ITEM {  560u,   851u, 2u } veTable[216] */
/* ITEM {  562u,   854u, 2u } veTable[217] */
/* ITEM {  564u,   854u, 2u } veTable[218] */
/* ITEM {  566u,   826u, 2u } veTable[219] */
/* ITEM {  568u,   798u, 2u } veTable[220] */
/* ITEM {  570u,   776u, 2u } veTable[221] */
/* ITEM {  572u,   755u, 2u } veTable[222] */
/* ITEM {  574u,   734u, 2u } veTable[223] */
/* ITEM {  576u,   849u, 2u } veTable[224] */
/* ITEM {  578u,   853u, 2u } veTable[225] */
/* ITEM {  580u,   854u, 2u } veTable[226] */
/* ITEM {  582u,   863u, 2u } veTable[227] */
/* ITEM {  584u,   864u, 2u } veTable[228] */
/* ITEM {  586u,   872u, 2u } veTable[229] */
/* ITEM {  588u,   885u, 2u } veTable[230] */
/* ITEM {  590u,   881u, 2u } veTable[231] */
/* ITEM {  592u,   879u, 2u } veTable[232] */
/* ITEM {  594u,   891u, 2u } veTable[233] */
/* ITEM {  596u,   899u, 2u } veTable[234] */
/* ITEM {  598u,   876u, 2u } veTable[235] */
/* ITEM {  600u,   853u, 2u } veTable[236] */
/* ITEM {  602u,   836u, 2u } veTable[237] */
/* ITEM {  604u,   822u, 2u } veTable[238] */
/* ITEM {  606u,   806u, 2u } veTable[239] */
/* ITEM {  608u,   850u, 2u } veTable[240] */
/* ITEM {  610u,   856u, 2u } veTable[241] */
/* ITEM {  612u,   858u, 2u } veTable[242] */
/* ITEM {  614u,   869u, 2u } veTable[243] */
/* ITEM {  616u,   874u, 2u } veTable[244] */
/* ITEM {  618u,   888u, 2u } veTable[245] */
/* ITEM {  620u,   909u, 2u } veTable[246] */
/* ITEM {  622u,   912u, 2u } veTable[247] */
/* ITEM {  624u,   919u, 2u } veTable[248] */
/* ITEM {  626u,   943u, 2u } veTable[249] */
/* ITEM {  628u,   967u, 2u } veTable[250] */
/* ITEM {  630u,   952u, 2u } veTable[251] */
/* ITEM {  632u,   938u, 2u } veTable[252] */
/* ITEM {  634u,   932u, 2u } veTable[253] */
/* ITEM {  636u,   929u, 2u } veTable[254] */
/* ITEM {  638u,   926u, 2u } veTable[255] */
/* ITEM { 1240u,     0u, 1u } dbwEnable */
/* ITEM { 2636u,  1470u, 2u } stoichAfrX100 */
/* ITEM { 1242u,  5120u, 2u } dbwKp */
/* ITEM { 1244u, 47000u, 2u } dbwKi */
/* ITEM { 1322u, 17600u, 2u } dbwKd */
/* ITEM { 1332u,     0u, 2u } dbwBiasAx[0] */
/* ITEM { 1334u,    10u, 2u } dbwBiasAx[1] */
/* ITEM { 1336u,    50u, 2u } dbwBiasAx[2] */
/* ITEM { 1338u,    70u, 2u } dbwBiasAx[3] */
/* ITEM { 1340u,   140u, 2u } dbwBiasAx[4] */
/* ITEM { 1342u,   650u, 2u } dbwBiasAx[5] */
/* ITEM { 1344u,   660u, 2u } dbwBiasAx[6] */
/* ITEM { 1346u,  1000u, 2u } dbwBiasAx[7] */
/* ITEM { 1348u,   850u, 2u } dbwBiasVal[0] */
/* ITEM { 1350u,   850u, 2u } dbwBiasVal[1] */
/* ITEM { 1352u,   900u, 2u } dbwBiasVal[2] */
/* ITEM { 1354u,  1000u, 2u } dbwBiasVal[3] */
/* ITEM { 1356u,  1190u, 2u } dbwBiasVal[4] */
/* ITEM { 1358u,  1200u, 2u } dbwBiasVal[5] */
/* ITEM { 1360u,  1260u, 2u } dbwBiasVal[6] */
/* ITEM { 1362u,  1280u, 2u } dbwBiasVal[7] */
/* ITEM { 2620u,     1u, 1u } tpsCorrelation */
/* ITEM { 2621u,     1u, 1u } appCorrelation */
/* ITEM {   72u,     1u, 1u } trigSource */
/* ITEM { 2680u,     1u, 1u } fuelPumpMode */
/* ITEM { 2540u, 64756u, 2u } trigAngleX10 = -780 */
/* ITEM { 1228u,   150u, 2u } pedal1Min */
/* ITEM { 1230u,   849u, 2u } pedal1Max */
/* ITEM { 1232u,    75u, 2u } pedal2Min */
/* ITEM { 1234u,   424u, 2u } pedal2Max */
/* ITEM { 1220u,   102u, 2u } tps1Min */
/* ITEM { 1222u,   954u, 2u } tps1Max */
/* ITEM { 1224u,   919u, 2u } tps2Min */
/* ITEM { 1226u,    71u, 2u } tps2Max */
/* ITEM {  704u,   500u, 2u } ignRpmAx[0] */
/* ITEM {  706u,   800u, 2u } ignRpmAx[1] */
/* ITEM {  708u,  1000u, 2u } ignRpmAx[2] */
/* ITEM {  710u,  1250u, 2u } ignRpmAx[3] */
/* ITEM {  712u,  1500u, 2u } ignRpmAx[4] */
/* ITEM {  714u,  1750u, 2u } ignRpmAx[5] */
/* ITEM {  716u,  2000u, 2u } ignRpmAx[6] */
/* ITEM {  718u,  2500u, 2u } ignRpmAx[7] */
/* ITEM {  720u,  3000u, 2u } ignRpmAx[8] */
/* ITEM {  722u,  3500u, 2u } ignRpmAx[9] */
/* ITEM {  724u,  4000u, 2u } ignRpmAx[10] */
/* ITEM {  726u,  4500u, 2u } ignRpmAx[11] */
/* ITEM {  728u,  5000u, 2u } ignRpmAx[12] */
/* ITEM {  730u,  5500u, 2u } ignRpmAx[13] */
/* ITEM {  732u,  6000u, 2u } ignRpmAx[14] */
/* ITEM {  734u,  6800u, 2u } ignRpmAx[15] */
/* ITEM {  736u,     0u, 2u } ignLoadAx[0] */
/* ITEM {  738u,    10u, 2u } ignLoadAx[1] */
/* ITEM {  740u,    20u, 2u } ignLoadAx[2] */
/* ITEM {  742u,    30u, 2u } ignLoadAx[3] */
/* ITEM {  744u,    40u, 2u } ignLoadAx[4] */
/* ITEM {  746u,    55u, 2u } ignLoadAx[5] */
/* ITEM {  748u,    70u, 2u } ignLoadAx[6] */
/* ITEM {  750u,   100u, 2u } ignLoadAx[7] */
/* ITEM {  752u,   130u, 2u } ignLoadAx[8] */
/* ITEM {  754u,   160u, 2u } ignLoadAx[9] */
/* ITEM {  756u,   200u, 2u } ignLoadAx[10] */
/* ITEM {  758u,   250u, 2u } ignLoadAx[11] */
/* ITEM {  760u,   300u, 2u } ignLoadAx[12] */
/* ITEM {  762u,   400u, 2u } ignLoadAx[13] */
/* ITEM {  764u,   500u, 2u } ignLoadAx[14] */
/* ITEM {  766u,  1000u, 2u } ignLoadAx[15] */
/* ITEM { 3310u,   500u, 2u } lambdaRpmAx[0] */
/* ITEM { 3312u,   950u, 2u } lambdaRpmAx[1] */
/* ITEM { 3314u,  1400u, 2u } lambdaRpmAx[2] */
/* ITEM { 3316u,  1850u, 2u } lambdaRpmAx[3] */
/* ITEM { 3318u,  2300u, 2u } lambdaRpmAx[4] */
/* ITEM { 3320u,  2750u, 2u } lambdaRpmAx[5] */
/* ITEM { 3322u,  3200u, 2u } lambdaRpmAx[6] */
/* ITEM { 3324u,  3650u, 2u } lambdaRpmAx[7] */
/* ITEM { 3326u,  4100u, 2u } lambdaRpmAx[8] */
/* ITEM { 3328u,  4550u, 2u } lambdaRpmAx[9] */
/* ITEM { 3330u,  5000u, 2u } lambdaRpmAx[10] */
/* ITEM { 3332u,  5450u, 2u } lambdaRpmAx[11] */
/* ITEM { 3334u,  5900u, 2u } lambdaRpmAx[12] */
/* ITEM { 3336u,  6350u, 2u } lambdaRpmAx[13] */
/* ITEM { 3338u,  6800u, 2u } lambdaRpmAx[14] */
/* ITEM { 3340u,  7250u, 2u } lambdaRpmAx[15] */
/* ITEM { 3342u,     0u, 2u } lambdaLoadAx[0] */
/* ITEM { 3344u,    10u, 2u } lambdaLoadAx[1] */
/* ITEM { 3346u,    20u, 2u } lambdaLoadAx[2] */
/* ITEM { 3348u,    30u, 2u } lambdaLoadAx[3] */
/* ITEM { 3350u,    40u, 2u } lambdaLoadAx[4] */
/* ITEM { 3352u,    55u, 2u } lambdaLoadAx[5] */
/* ITEM { 3354u,    70u, 2u } lambdaLoadAx[6] */
/* ITEM { 3356u,   100u, 2u } lambdaLoadAx[7] */
/* ITEM { 3358u,   130u, 2u } lambdaLoadAx[8] */
/* ITEM { 3360u,   160u, 2u } lambdaLoadAx[9] */
/* ITEM { 3362u,   200u, 2u } lambdaLoadAx[10] */
/* ITEM { 3364u,   250u, 2u } lambdaLoadAx[11] */
/* ITEM { 3366u,   300u, 2u } lambdaLoadAx[12] */
/* ITEM { 3368u,   400u, 2u } lambdaLoadAx[13] */
/* ITEM { 3370u,   500u, 2u } lambdaLoadAx[14] */
/* ITEM { 3372u,  1000u, 2u } lambdaLoadAx[15] */
/* ITEM { 3390u,     0u, 2u } mapEstTpsAx[0] */
/* ITEM { 3392u,    50u, 2u } mapEstTpsAx[1] */
/* ITEM { 3394u,   100u, 2u } mapEstTpsAx[2] */
/* ITEM { 3396u,   200u, 2u } mapEstTpsAx[3] */
/* ITEM { 3398u,   400u, 2u } mapEstTpsAx[4] */
/* ITEM { 3400u,   600u, 2u } mapEstTpsAx[5] */
/* ITEM { 3402u,   800u, 2u } mapEstTpsAx[6] */
/* ITEM { 3404u,  1000u, 2u } mapEstTpsAx[7] */
/* ITEM { 3374u,   800u, 2u } mapEstRpmAx[0] */
/* ITEM { 3376u,  1500u, 2u } mapEstRpmAx[1] */
/* ITEM { 3378u,  2000u, 2u } mapEstRpmAx[2] */
/* ITEM { 3380u,  2500u, 2u } mapEstRpmAx[3] */
/* ITEM { 3382u,  3000u, 2u } mapEstRpmAx[4] */
/* ITEM { 3384u,  4000u, 2u } mapEstRpmAx[5] */
/* ITEM { 3386u,  5000u, 2u } mapEstRpmAx[6] */
/* ITEM { 3388u,  6500u, 2u } mapEstRpmAx[7] */
/* ITEM { 3406u,   100u, 1u } mapEstimate[0] */
/* ITEM { 3407u,   100u, 1u } mapEstimate[1] */
/* ITEM { 3408u,   100u, 1u } mapEstimate[2] */
/* ITEM { 3409u,   100u, 1u } mapEstimate[3] */
/* ITEM { 3410u,   100u, 1u } mapEstimate[4] */
/* ITEM { 3411u,   100u, 1u } mapEstimate[5] */
/* ITEM { 3412u,   100u, 1u } mapEstimate[6] */
/* ITEM { 3413u,   100u, 1u } mapEstimate[7] */
/* ITEM { 3414u,   100u, 1u } mapEstimate[8] */
/* ITEM { 3415u,   100u, 1u } mapEstimate[9] */
/* ITEM { 3416u,   100u, 1u } mapEstimate[10] */
/* ITEM { 3417u,   100u, 1u } mapEstimate[11] */
/* ITEM { 3418u,   100u, 1u } mapEstimate[12] */
/* ITEM { 3419u,   100u, 1u } mapEstimate[13] */
/* ITEM { 3420u,   100u, 1u } mapEstimate[14] */
/* ITEM { 3421u,   100u, 1u } mapEstimate[15] */
/* ITEM { 3422u,   100u, 1u } mapEstimate[16] */
/* ITEM { 3423u,   100u, 1u } mapEstimate[17] */
/* ITEM { 3424u,   100u, 1u } mapEstimate[18] */
/* ITEM { 3425u,   100u, 1u } mapEstimate[19] */
/* ITEM { 3426u,   100u, 1u } mapEstimate[20] */
/* ITEM { 3427u,   100u, 1u } mapEstimate[21] */
/* ITEM { 3428u,   100u, 1u } mapEstimate[22] */
/* ITEM { 3429u,   100u, 1u } mapEstimate[23] */
/* ITEM { 3430u,   100u, 1u } mapEstimate[24] */
/* ITEM { 3431u,   100u, 1u } mapEstimate[25] */
/* ITEM { 3432u,   100u, 1u } mapEstimate[26] */
/* ITEM { 3433u,   100u, 1u } mapEstimate[27] */
/* ITEM { 3434u,   100u, 1u } mapEstimate[28] */
/* ITEM { 3435u,   100u, 1u } mapEstimate[29] */
/* ITEM { 3436u,   100u, 1u } mapEstimate[30] */
/* ITEM { 3437u,   100u, 1u } mapEstimate[31] */
/* ITEM { 3438u,   100u, 1u } mapEstimate[32] */
/* ITEM { 3439u,   100u, 1u } mapEstimate[33] */
/* ITEM { 3440u,   100u, 1u } mapEstimate[34] */
/* ITEM { 3441u,   100u, 1u } mapEstimate[35] */
/* ITEM { 3442u,   100u, 1u } mapEstimate[36] */
/* ITEM { 3443u,   100u, 1u } mapEstimate[37] */
/* ITEM { 3444u,   100u, 1u } mapEstimate[38] */
/* ITEM { 3445u,   100u, 1u } mapEstimate[39] */
/* ITEM { 3446u,   100u, 1u } mapEstimate[40] */
/* ITEM { 3447u,   100u, 1u } mapEstimate[41] */
/* ITEM { 3448u,   105u, 1u } mapEstimate[42] */
/* ITEM { 3449u,   115u, 1u } mapEstimate[43] */
/* ITEM { 3450u,   125u, 1u } mapEstimate[44] */
/* ITEM { 3451u,   125u, 1u } mapEstimate[45] */
/* ITEM { 3452u,   120u, 1u } mapEstimate[46] */
/* ITEM { 3453u,   115u, 1u } mapEstimate[47] */
/* ITEM { 3454u,   100u, 1u } mapEstimate[48] */
/* ITEM { 3455u,   100u, 1u } mapEstimate[49] */
/* ITEM { 3456u,   110u, 1u } mapEstimate[50] */
/* ITEM { 3457u,   125u, 1u } mapEstimate[51] */
/* ITEM { 3458u,   140u, 1u } mapEstimate[52] */
/* ITEM { 3459u,   140u, 1u } mapEstimate[53] */
/* ITEM { 3460u,   135u, 1u } mapEstimate[54] */
/* ITEM { 3461u,   125u, 1u } mapEstimate[55] */
/* ITEM { 3462u,   100u, 1u } mapEstimate[56] */
/* ITEM { 3463u,   105u, 1u } mapEstimate[57] */
/* ITEM { 3464u,   115u, 1u } mapEstimate[58] */
/* ITEM { 3465u,   135u, 1u } mapEstimate[59] */
/* ITEM { 3466u,   150u, 1u } mapEstimate[60] */
/* ITEM { 3467u,   150u, 1u } mapEstimate[61] */
/* ITEM { 3468u,   145u, 1u } mapEstimate[62] */
/* ITEM { 3469u,   135u, 1u } mapEstimate[63] */
/* ITEM { 3493u,     1u, 1u } stftEnable */
/* ITEM { 3506u,    10u, 1u } stftMaxAdd[0] */
/* ITEM { 3507u,     0u, 1u } stftMaxAdd[1] */
/* ITEM { 3508u,     5u, 1u } stftMaxAdd[2] */
/* ITEM { 3509u,    10u, 1u } stftMaxAdd[3] */
/* ITEM { 3510u,    10u, 1u } stftMaxRemove[0] */
/* ITEM { 3511u,     0u, 1u } stftMaxRemove[1] */
/* ITEM { 3512u,     0u, 1u } stftMaxRemove[2] */
/* ITEM { 3513u,    10u, 1u } stftMaxRemove[3] */
/* ITEM { 3500u,     2u, 1u } stftOverrunLoad */
/* ITEM { 3501u,    40u, 1u } stftPowerLoad */
/* ITEM { 2418u,  2000u, 2u } overrunRpm */
/* ITEM { 2422u,  1600u, 2u } overrunResume */
/* ITEM { 2420u,    20u, 2u } overrunTpsX10 */
/* ITEM { 2670u, 11150u, 2u } cltMaxDegX10 */
/* ITEM { 2426u,     1u, 1u } idleEnable */
/* ITEM { 2476u,    61u, 2u } idleBaseVal[0] */
/* ITEM { 2478u,    56u, 2u } idleBaseVal[1] */
/* ITEM { 2480u,    51u, 2u } idleBaseVal[2] */
/* ITEM { 2482u,    46u, 2u } idleBaseVal[3] */
/* ITEM { 2484u,    41u, 2u } idleBaseVal[4] */
/* ITEM { 2486u,    36u, 2u } idleBaseVal[5] */
/* ITEM { 2488u,    36u, 2u } idleBaseVal[6] */
/* ITEM { 2490u,    36u, 2u } idleBaseVal[7] */
/* ITEM { 2498u,   600u, 2u } idleRpmBand */
/* ITEM { 3838u,    64u, 1u } ignMap[0] */
/* ITEM { 3839u,    64u, 1u } ignMap[1] */
/* ITEM { 3840u,    64u, 1u } ignMap[2] */
/* ITEM { 3841u,    64u, 1u } ignMap[3] */
/* ITEM { 3842u,    66u, 1u } ignMap[4] */
/* ITEM { 3843u,    72u, 1u } ignMap[5] */
/* ITEM { 3844u,    80u, 1u } ignMap[6] */
/* ITEM { 3845u,    95u, 1u } ignMap[7] */
/* ITEM { 3846u,    97u, 1u } ignMap[8] */
/* ITEM { 3847u,    97u, 1u } ignMap[9] */
/* ITEM { 3848u,    96u, 1u } ignMap[10] */
/* ITEM { 3849u,    96u, 1u } ignMap[11] */
/* ITEM { 3850u,   100u, 1u } ignMap[12] */
/* ITEM { 3851u,   107u, 1u } ignMap[13] */
/* ITEM { 3852u,   114u, 1u } ignMap[14] */
/* ITEM { 3853u,   120u, 1u } ignMap[15] */
/* ITEM { 3854u,    64u, 1u } ignMap[16] */
/* ITEM { 3855u,    64u, 1u } ignMap[17] */
/* ITEM { 3856u,    64u, 1u } ignMap[18] */
/* ITEM { 3857u,    64u, 1u } ignMap[19] */
/* ITEM { 3858u,    66u, 1u } ignMap[20] */
/* ITEM { 3859u,    72u, 1u } ignMap[21] */
/* ITEM { 3860u,    80u, 1u } ignMap[22] */
/* ITEM { 3861u,    95u, 1u } ignMap[23] */
/* ITEM { 3862u,    97u, 1u } ignMap[24] */
/* ITEM { 3863u,    97u, 1u } ignMap[25] */
/* ITEM { 3864u,    96u, 1u } ignMap[26] */
/* ITEM { 3865u,    96u, 1u } ignMap[27] */
/* ITEM { 3866u,   100u, 1u } ignMap[28] */
/* ITEM { 3867u,   107u, 1u } ignMap[29] */
/* ITEM { 3868u,   114u, 1u } ignMap[30] */
/* ITEM { 3869u,   120u, 1u } ignMap[31] */
/* ITEM { 3870u,    60u, 1u } ignMap[32] */
/* ITEM { 3871u,    64u, 1u } ignMap[33] */
/* ITEM { 3872u,    64u, 1u } ignMap[34] */
/* ITEM { 3873u,    64u, 1u } ignMap[35] */
/* ITEM { 3874u,    66u, 1u } ignMap[36] */
/* ITEM { 3875u,    72u, 1u } ignMap[37] */
/* ITEM { 3876u,    80u, 1u } ignMap[38] */
/* ITEM { 3877u,    95u, 1u } ignMap[39] */
/* ITEM { 3878u,    97u, 1u } ignMap[40] */
/* ITEM { 3879u,    97u, 1u } ignMap[41] */
/* ITEM { 3880u,    96u, 1u } ignMap[42] */
/* ITEM { 3881u,    96u, 1u } ignMap[43] */
/* ITEM { 3882u,   100u, 1u } ignMap[44] */
/* ITEM { 3883u,   107u, 1u } ignMap[45] */
/* ITEM { 3884u,   114u, 1u } ignMap[46] */
/* ITEM { 3885u,   120u, 1u } ignMap[47] */
/* ITEM { 3886u,    51u, 1u } ignMap[48] */
/* ITEM { 3887u,    64u, 1u } ignMap[49] */
/* ITEM { 3888u,    64u, 1u } ignMap[50] */
/* ITEM { 3889u,    64u, 1u } ignMap[51] */
/* ITEM { 3890u,    66u, 1u } ignMap[52] */
/* ITEM { 3891u,    72u, 1u } ignMap[53] */
/* ITEM { 3892u,    80u, 1u } ignMap[54] */
/* ITEM { 3893u,    95u, 1u } ignMap[55] */
/* ITEM { 3894u,    97u, 1u } ignMap[56] */
/* ITEM { 3895u,    97u, 1u } ignMap[57] */
/* ITEM { 3896u,    96u, 1u } ignMap[58] */
/* ITEM { 3897u,    96u, 1u } ignMap[59] */
/* ITEM { 3898u,   100u, 1u } ignMap[60] */
/* ITEM { 3899u,   107u, 1u } ignMap[61] */
/* ITEM { 3900u,   114u, 1u } ignMap[62] */
/* ITEM { 3901u,   120u, 1u } ignMap[63] */
/* ITEM { 3902u,    45u, 1u } ignMap[64] */
/* ITEM { 3903u,    64u, 1u } ignMap[65] */
/* ITEM { 3904u,    64u, 1u } ignMap[66] */
/* ITEM { 3905u,    64u, 1u } ignMap[67] */
/* ITEM { 3906u,    66u, 1u } ignMap[68] */
/* ITEM { 3907u,    72u, 1u } ignMap[69] */
/* ITEM { 3908u,    80u, 1u } ignMap[70] */
/* ITEM { 3909u,    95u, 1u } ignMap[71] */
/* ITEM { 3910u,    97u, 1u } ignMap[72] */
/* ITEM { 3911u,    97u, 1u } ignMap[73] */
/* ITEM { 3912u,    96u, 1u } ignMap[74] */
/* ITEM { 3913u,    96u, 1u } ignMap[75] */
/* ITEM { 3914u,   100u, 1u } ignMap[76] */
/* ITEM { 3915u,   107u, 1u } ignMap[77] */
/* ITEM { 3916u,   114u, 1u } ignMap[78] */
/* ITEM { 3917u,   120u, 1u } ignMap[79] */
/* ITEM { 3918u,    40u, 1u } ignMap[80] */
/* ITEM { 3919u,    64u, 1u } ignMap[81] */
/* ITEM { 3920u,    64u, 1u } ignMap[82] */
/* ITEM { 3921u,    66u, 1u } ignMap[83] */
/* ITEM { 3922u,    70u, 1u } ignMap[84] */
/* ITEM { 3923u,    76u, 1u } ignMap[85] */
/* ITEM { 3924u,    82u, 1u } ignMap[86] */
/* ITEM { 3925u,    98u, 1u } ignMap[87] */
/* ITEM { 3926u,    97u, 1u } ignMap[88] */
/* ITEM { 3927u,    97u, 1u } ignMap[89] */
/* ITEM { 3928u,    96u, 1u } ignMap[90] */
/* ITEM { 3929u,    96u, 1u } ignMap[91] */
/* ITEM { 3930u,   100u, 1u } ignMap[92] */
/* ITEM { 3931u,   107u, 1u } ignMap[93] */
/* ITEM { 3932u,   114u, 1u } ignMap[94] */
/* ITEM { 3933u,   120u, 1u } ignMap[95] */
/* ITEM { 3934u,    40u, 1u } ignMap[96] */
/* ITEM { 3935u,    60u, 1u } ignMap[97] */
/* ITEM { 3936u,    68u, 1u } ignMap[98] */
/* ITEM { 3937u,    72u, 1u } ignMap[99] */
/* ITEM { 3938u,    78u, 1u } ignMap[100] */
/* ITEM { 3939u,    86u, 1u } ignMap[101] */
/* ITEM { 3940u,    92u, 1u } ignMap[102] */
/* ITEM { 3941u,   116u, 1u } ignMap[103] */
/* ITEM { 3942u,   107u, 1u } ignMap[104] */
/* ITEM { 3943u,    97u, 1u } ignMap[105] */
/* ITEM { 3944u,    96u, 1u } ignMap[106] */
/* ITEM { 3945u,    96u, 1u } ignMap[107] */
/* ITEM { 3946u,   100u, 1u } ignMap[108] */
/* ITEM { 3947u,   107u, 1u } ignMap[109] */
/* ITEM { 3948u,   114u, 1u } ignMap[110] */
/* ITEM { 3949u,   120u, 1u } ignMap[111] */
/* ITEM { 3950u,    40u, 1u } ignMap[112] */
/* ITEM { 3951u,    51u, 1u } ignMap[113] */
/* ITEM { 3952u,    61u, 1u } ignMap[114] */
/* ITEM { 3953u,    75u, 1u } ignMap[115] */
/* ITEM { 3954u,    83u, 1u } ignMap[116] */
/* ITEM { 3955u,    92u, 1u } ignMap[117] */
/* ITEM { 3956u,    98u, 1u } ignMap[118] */
/* ITEM { 3957u,   110u, 1u } ignMap[119] */
/* ITEM { 3958u,   120u, 1u } ignMap[120] */
/* ITEM { 3959u,   124u, 1u } ignMap[121] */
/* ITEM { 3960u,   122u, 1u } ignMap[122] */
/* ITEM { 3961u,   105u, 1u } ignMap[123] */
/* ITEM { 3962u,   101u, 1u } ignMap[124] */
/* ITEM { 3963u,   107u, 1u } ignMap[125] */
/* ITEM { 3964u,   114u, 1u } ignMap[126] */
/* ITEM { 3965u,   120u, 1u } ignMap[127] */
/* ITEM { 3966u,    40u, 1u } ignMap[128] */
/* ITEM { 3967u,    49u, 1u } ignMap[129] */
/* ITEM { 3968u,    56u, 1u } ignMap[130] */
/* ITEM { 3969u,    68u, 1u } ignMap[131] */
/* ITEM { 3970u,    76u, 1u } ignMap[132] */
/* ITEM { 3971u,    84u, 1u } ignMap[133] */
/* ITEM { 3972u,    90u, 1u } ignMap[134] */
/* ITEM { 3973u,   103u, 1u } ignMap[135] */
/* ITEM { 3974u,   113u, 1u } ignMap[136] */
/* ITEM { 3975u,   118u, 1u } ignMap[137] */
/* ITEM { 3976u,   122u, 1u } ignMap[138] */
/* ITEM { 3977u,   118u, 1u } ignMap[139] */
/* ITEM { 3978u,   117u, 1u } ignMap[140] */
/* ITEM { 3979u,   116u, 1u } ignMap[141] */
/* ITEM { 3980u,   116u, 1u } ignMap[142] */
/* ITEM { 3981u,   120u, 1u } ignMap[143] */
/* ITEM { 3982u,    40u, 1u } ignMap[144] */
/* ITEM { 3983u,    47u, 1u } ignMap[145] */
/* ITEM { 3984u,    53u, 1u } ignMap[146] */
/* ITEM { 3985u,    64u, 1u } ignMap[147] */
/* ITEM { 3986u,    71u, 1u } ignMap[148] */
/* ITEM { 3987u,    78u, 1u } ignMap[149] */
/* ITEM { 3988u,    83u, 1u } ignMap[150] */
/* ITEM { 3989u,    98u, 1u } ignMap[151] */
/* ITEM { 3990u,   106u, 1u } ignMap[152] */
/* ITEM { 3991u,   111u, 1u } ignMap[153] */
/* ITEM { 3992u,   116u, 1u } ignMap[154] */
/* ITEM { 3993u,   116u, 1u } ignMap[155] */
/* ITEM { 3994u,   113u, 1u } ignMap[156] */
/* ITEM { 3995u,   114u, 1u } ignMap[157] */
/* ITEM { 3996u,   118u, 1u } ignMap[158] */
/* ITEM { 3997u,   122u, 1u } ignMap[159] */
/* ITEM { 3998u,    40u, 1u } ignMap[160] */
/* ITEM { 3999u,    46u, 1u } ignMap[161] */
/* ITEM { 4000u,    51u, 1u } ignMap[162] */
/* ITEM { 4001u,    60u, 1u } ignMap[163] */
/* ITEM { 4002u,    66u, 1u } ignMap[164] */
/* ITEM { 4003u,    72u, 1u } ignMap[165] */
/* ITEM { 4004u,    76u, 1u } ignMap[166] */
/* ITEM { 4005u,    93u, 1u } ignMap[167] */
/* ITEM { 4006u,   100u, 1u } ignMap[168] */
/* ITEM { 4007u,   104u, 1u } ignMap[169] */
/* ITEM { 4008u,   108u, 1u } ignMap[170] */
/* ITEM { 4009u,   109u, 1u } ignMap[171] */
/* ITEM { 4010u,   108u, 1u } ignMap[172] */
/* ITEM { 4011u,   110u, 1u } ignMap[173] */
/* ITEM { 4012u,   116u, 1u } ignMap[174] */
/* ITEM { 4013u,   121u, 1u } ignMap[175] */
/* ITEM { 4014u,    40u, 1u } ignMap[176] */
/* ITEM { 4015u,    46u, 1u } ignMap[177] */
/* ITEM { 4016u,    50u, 1u } ignMap[178] */
/* ITEM { 4017u,    58u, 1u } ignMap[179] */
/* ITEM { 4018u,    64u, 1u } ignMap[180] */
/* ITEM { 4019u,    69u, 1u } ignMap[181] */
/* ITEM { 4020u,    72u, 1u } ignMap[182] */
/* ITEM { 4021u,    88u, 1u } ignMap[183] */
/* ITEM { 4022u,    93u, 1u } ignMap[184] */
/* ITEM { 4023u,    99u, 1u } ignMap[185] */
/* ITEM { 4024u,   102u, 1u } ignMap[186] */
/* ITEM { 4025u,   102u, 1u } ignMap[187] */
/* ITEM { 4026u,   101u, 1u } ignMap[188] */
/* ITEM { 4027u,   103u, 1u } ignMap[189] */
/* ITEM { 4028u,   109u, 1u } ignMap[190] */
/* ITEM { 4029u,   116u, 1u } ignMap[191] */
/* ITEM { 4030u,    40u, 1u } ignMap[192] */
/* ITEM { 4031u,    44u, 1u } ignMap[193] */
/* ITEM { 4032u,    48u, 1u } ignMap[194] */
/* ITEM { 4033u,    55u, 1u } ignMap[195] */
/* ITEM { 4034u,    59u, 1u } ignMap[196] */
/* ITEM { 4035u,    63u, 1u } ignMap[197] */
/* ITEM { 4036u,    66u, 1u } ignMap[198] */
/* ITEM { 4037u,    77u, 1u } ignMap[199] */
/* ITEM { 4038u,    82u, 1u } ignMap[200] */
/* ITEM { 4039u,    89u, 1u } ignMap[201] */
/* ITEM { 4040u,    91u, 1u } ignMap[202] */
/* ITEM { 4041u,    92u, 1u } ignMap[203] */
/* ITEM { 4042u,    91u, 1u } ignMap[204] */
/* ITEM { 4043u,    94u, 1u } ignMap[205] */
/* ITEM { 4044u,   101u, 1u } ignMap[206] */
/* ITEM { 4045u,   106u, 1u } ignMap[207] */
/* ITEM { 4046u,    40u, 1u } ignMap[208] */
/* ITEM { 4047u,    42u, 1u } ignMap[209] */
/* ITEM { 4048u,    45u, 1u } ignMap[210] */
/* ITEM { 4049u,    49u, 1u } ignMap[211] */
/* ITEM { 4050u,    53u, 1u } ignMap[212] */
/* ITEM { 4051u,    56u, 1u } ignMap[213] */
/* ITEM { 4052u,    58u, 1u } ignMap[214] */
/* ITEM { 4053u,    61u, 1u } ignMap[215] */
/* ITEM { 4054u,    60u, 1u } ignMap[216] */
/* ITEM { 4055u,    65u, 1u } ignMap[217] */
/* ITEM { 4056u,    65u, 1u } ignMap[218] */
/* ITEM { 4057u,    66u, 1u } ignMap[219] */
/* ITEM { 4058u,    69u, 1u } ignMap[220] */
/* ITEM { 4059u,    76u, 1u } ignMap[221] */
/* ITEM { 4060u,    82u, 1u } ignMap[222] */
/* ITEM { 4061u,    89u, 1u } ignMap[223] */
/* ITEM { 4062u,    40u, 1u } ignMap[224] */
/* ITEM { 4063u,    40u, 1u } ignMap[225] */
/* ITEM { 4064u,    43u, 1u } ignMap[226] */
/* ITEM { 4065u,    47u, 1u } ignMap[227] */
/* ITEM { 4066u,    46u, 1u } ignMap[228] */
/* ITEM { 4067u,    47u, 1u } ignMap[229] */
/* ITEM { 4068u,    48u, 1u } ignMap[230] */
/* ITEM { 4069u,    51u, 1u } ignMap[231] */
/* ITEM { 4070u,    48u, 1u } ignMap[232] */
/* ITEM { 4071u,    54u, 1u } ignMap[233] */
/* ITEM { 4072u,    57u, 1u } ignMap[234] */
/* ITEM { 4073u,    58u, 1u } ignMap[235] */
/* ITEM { 4074u,    60u, 1u } ignMap[236] */
/* ITEM { 4075u,    66u, 1u } ignMap[237] */
/* ITEM { 4076u,    73u, 1u } ignMap[238] */
/* ITEM { 4077u,    78u, 1u } ignMap[239] */
/* ITEM { 4078u,    40u, 1u } ignMap[240] */
/* ITEM { 4079u,    40u, 1u } ignMap[241] */
/* ITEM { 4080u,    43u, 1u } ignMap[242] */
/* ITEM { 4081u,    47u, 1u } ignMap[243] */
/* ITEM { 4082u,    46u, 1u } ignMap[244] */
/* ITEM { 4083u,    47u, 1u } ignMap[245] */
/* ITEM { 4084u,    48u, 1u } ignMap[246] */
/* ITEM { 4085u,    51u, 1u } ignMap[247] */
/* ITEM { 4086u,    48u, 1u } ignMap[248] */
/* ITEM { 4087u,    54u, 1u } ignMap[249] */
/* ITEM { 4088u,    57u, 1u } ignMap[250] */
/* ITEM { 4089u,    58u, 1u } ignMap[251] */
/* ITEM { 4090u,    60u, 1u } ignMap[252] */
/* ITEM { 4091u,    66u, 1u } ignMap[253] */
/* ITEM { 4092u,    73u, 1u } ignMap[254] */
/* ITEM { 4093u,    78u, 1u } ignMap[255] */
/* ITEM {  768u,   147u, 1u } afrMap[0] */
/* ITEM {  769u,   147u, 1u } afrMap[1] */
/* ITEM {  770u,   147u, 1u } afrMap[2] */
/* ITEM {  771u,   147u, 1u } afrMap[3] */
/* ITEM {  772u,   147u, 1u } afrMap[4] */
/* ITEM {  773u,   147u, 1u } afrMap[5] */
/* ITEM {  774u,   147u, 1u } afrMap[6] */
/* ITEM {  775u,   147u, 1u } afrMap[7] */
/* ITEM {  776u,   147u, 1u } afrMap[8] */
/* ITEM {  777u,   147u, 1u } afrMap[9] */
/* ITEM {  778u,   147u, 1u } afrMap[10] */
/* ITEM {  779u,   147u, 1u } afrMap[11] */
/* ITEM {  780u,   147u, 1u } afrMap[12] */
/* ITEM {  781u,   147u, 1u } afrMap[13] */
/* ITEM {  782u,   147u, 1u } afrMap[14] */
/* ITEM {  783u,   147u, 1u } afrMap[15] */
/* ITEM {  784u,   147u, 1u } afrMap[16] */
/* ITEM {  785u,   147u, 1u } afrMap[17] */
/* ITEM {  786u,   147u, 1u } afrMap[18] */
/* ITEM {  787u,   147u, 1u } afrMap[19] */
/* ITEM {  788u,   147u, 1u } afrMap[20] */
/* ITEM {  789u,   147u, 1u } afrMap[21] */
/* ITEM {  790u,   147u, 1u } afrMap[22] */
/* ITEM {  791u,   147u, 1u } afrMap[23] */
/* ITEM {  792u,   147u, 1u } afrMap[24] */
/* ITEM {  793u,   147u, 1u } afrMap[25] */
/* ITEM {  794u,   147u, 1u } afrMap[26] */
/* ITEM {  795u,   147u, 1u } afrMap[27] */
/* ITEM {  796u,   147u, 1u } afrMap[28] */
/* ITEM {  797u,   147u, 1u } afrMap[29] */
/* ITEM {  798u,   147u, 1u } afrMap[30] */
/* ITEM {  799u,   147u, 1u } afrMap[31] */
/* ITEM {  800u,   147u, 1u } afrMap[32] */
/* ITEM {  801u,   147u, 1u } afrMap[33] */
/* ITEM {  802u,   147u, 1u } afrMap[34] */
/* ITEM {  803u,   147u, 1u } afrMap[35] */
/* ITEM {  804u,   147u, 1u } afrMap[36] */
/* ITEM {  805u,   147u, 1u } afrMap[37] */
/* ITEM {  806u,   147u, 1u } afrMap[38] */
/* ITEM {  807u,   147u, 1u } afrMap[39] */
/* ITEM {  808u,   147u, 1u } afrMap[40] */
/* ITEM {  809u,   147u, 1u } afrMap[41] */
/* ITEM {  810u,   147u, 1u } afrMap[42] */
/* ITEM {  811u,   147u, 1u } afrMap[43] */
/* ITEM {  812u,   147u, 1u } afrMap[44] */
/* ITEM {  813u,   147u, 1u } afrMap[45] */
/* ITEM {  814u,   147u, 1u } afrMap[46] */
/* ITEM {  815u,   147u, 1u } afrMap[47] */
/* ITEM {  816u,   147u, 1u } afrMap[48] */
/* ITEM {  817u,   147u, 1u } afrMap[49] */
/* ITEM {  818u,   147u, 1u } afrMap[50] */
/* ITEM {  819u,   147u, 1u } afrMap[51] */
/* ITEM {  820u,   147u, 1u } afrMap[52] */
/* ITEM {  821u,   147u, 1u } afrMap[53] */
/* ITEM {  822u,   147u, 1u } afrMap[54] */
/* ITEM {  823u,   147u, 1u } afrMap[55] */
/* ITEM {  824u,   147u, 1u } afrMap[56] */
/* ITEM {  825u,   147u, 1u } afrMap[57] */
/* ITEM {  826u,   147u, 1u } afrMap[58] */
/* ITEM {  827u,   147u, 1u } afrMap[59] */
/* ITEM {  828u,   147u, 1u } afrMap[60] */
/* ITEM {  829u,   147u, 1u } afrMap[61] */
/* ITEM {  830u,   147u, 1u } afrMap[62] */
/* ITEM {  831u,   147u, 1u } afrMap[63] */
/* ITEM {  832u,   147u, 1u } afrMap[64] */
/* ITEM {  833u,   147u, 1u } afrMap[65] */
/* ITEM {  834u,   147u, 1u } afrMap[66] */
/* ITEM {  835u,   147u, 1u } afrMap[67] */
/* ITEM {  836u,   147u, 1u } afrMap[68] */
/* ITEM {  837u,   147u, 1u } afrMap[69] */
/* ITEM {  838u,   147u, 1u } afrMap[70] */
/* ITEM {  839u,   147u, 1u } afrMap[71] */
/* ITEM {  840u,   147u, 1u } afrMap[72] */
/* ITEM {  841u,   147u, 1u } afrMap[73] */
/* ITEM {  842u,   147u, 1u } afrMap[74] */
/* ITEM {  843u,   147u, 1u } afrMap[75] */
/* ITEM {  844u,   147u, 1u } afrMap[76] */
/* ITEM {  845u,   147u, 1u } afrMap[77] */
/* ITEM {  846u,   147u, 1u } afrMap[78] */
/* ITEM {  847u,   147u, 1u } afrMap[79] */
/* ITEM {  848u,   147u, 1u } afrMap[80] */
/* ITEM {  849u,   147u, 1u } afrMap[81] */
/* ITEM {  850u,   147u, 1u } afrMap[82] */
/* ITEM {  851u,   147u, 1u } afrMap[83] */
/* ITEM {  852u,   147u, 1u } afrMap[84] */
/* ITEM {  853u,   147u, 1u } afrMap[85] */
/* ITEM {  854u,   147u, 1u } afrMap[86] */
/* ITEM {  855u,   147u, 1u } afrMap[87] */
/* ITEM {  856u,   147u, 1u } afrMap[88] */
/* ITEM {  857u,   147u, 1u } afrMap[89] */
/* ITEM {  858u,   147u, 1u } afrMap[90] */
/* ITEM {  859u,   147u, 1u } afrMap[91] */
/* ITEM {  860u,   147u, 1u } afrMap[92] */
/* ITEM {  861u,   147u, 1u } afrMap[93] */
/* ITEM {  862u,   147u, 1u } afrMap[94] */
/* ITEM {  863u,   147u, 1u } afrMap[95] */
/* ITEM {  864u,   147u, 1u } afrMap[96] */
/* ITEM {  865u,   147u, 1u } afrMap[97] */
/* ITEM {  866u,   147u, 1u } afrMap[98] */
/* ITEM {  867u,   147u, 1u } afrMap[99] */
/* ITEM {  868u,   147u, 1u } afrMap[100] */
/* ITEM {  869u,   147u, 1u } afrMap[101] */
/* ITEM {  870u,   147u, 1u } afrMap[102] */
/* ITEM {  871u,   147u, 1u } afrMap[103] */
/* ITEM {  872u,   147u, 1u } afrMap[104] */
/* ITEM {  873u,   147u, 1u } afrMap[105] */
/* ITEM {  874u,   147u, 1u } afrMap[106] */
/* ITEM {  875u,   147u, 1u } afrMap[107] */
/* ITEM {  876u,   147u, 1u } afrMap[108] */
/* ITEM {  877u,   147u, 1u } afrMap[109] */
/* ITEM {  878u,   147u, 1u } afrMap[110] */
/* ITEM {  879u,   147u, 1u } afrMap[111] */
/* ITEM {  880u,   147u, 1u } afrMap[112] */
/* ITEM {  881u,   147u, 1u } afrMap[113] */
/* ITEM {  882u,   147u, 1u } afrMap[114] */
/* ITEM {  883u,   147u, 1u } afrMap[115] */
/* ITEM {  884u,   147u, 1u } afrMap[116] */
/* ITEM {  885u,   147u, 1u } afrMap[117] */
/* ITEM {  886u,   147u, 1u } afrMap[118] */
/* ITEM {  887u,   147u, 1u } afrMap[119] */
/* ITEM {  888u,   147u, 1u } afrMap[120] */
/* ITEM {  889u,   147u, 1u } afrMap[121] */
/* ITEM {  890u,   147u, 1u } afrMap[122] */
/* ITEM {  891u,   147u, 1u } afrMap[123] */
/* ITEM {  892u,   147u, 1u } afrMap[124] */
/* ITEM {  893u,   147u, 1u } afrMap[125] */
/* ITEM {  894u,   147u, 1u } afrMap[126] */
/* ITEM {  895u,   147u, 1u } afrMap[127] */
/* ITEM {  896u,   147u, 1u } afrMap[128] */
/* ITEM {  897u,   147u, 1u } afrMap[129] */
/* ITEM {  898u,   147u, 1u } afrMap[130] */
/* ITEM {  899u,   147u, 1u } afrMap[131] */
/* ITEM {  900u,   147u, 1u } afrMap[132] */
/* ITEM {  901u,   147u, 1u } afrMap[133] */
/* ITEM {  902u,   147u, 1u } afrMap[134] */
/* ITEM {  903u,   147u, 1u } afrMap[135] */
/* ITEM {  904u,   147u, 1u } afrMap[136] */
/* ITEM {  905u,   147u, 1u } afrMap[137] */
/* ITEM {  906u,   147u, 1u } afrMap[138] */
/* ITEM {  907u,   147u, 1u } afrMap[139] */
/* ITEM {  908u,   147u, 1u } afrMap[140] */
/* ITEM {  909u,   147u, 1u } afrMap[141] */
/* ITEM {  910u,   147u, 1u } afrMap[142] */
/* ITEM {  911u,   147u, 1u } afrMap[143] */
/* ITEM {  912u,   147u, 1u } afrMap[144] */
/* ITEM {  913u,   147u, 1u } afrMap[145] */
/* ITEM {  914u,   147u, 1u } afrMap[146] */
/* ITEM {  915u,   147u, 1u } afrMap[147] */
/* ITEM {  916u,   147u, 1u } afrMap[148] */
/* ITEM {  917u,   147u, 1u } afrMap[149] */
/* ITEM {  918u,   147u, 1u } afrMap[150] */
/* ITEM {  919u,   147u, 1u } afrMap[151] */
/* ITEM {  920u,   147u, 1u } afrMap[152] */
/* ITEM {  921u,   147u, 1u } afrMap[153] */
/* ITEM {  922u,   147u, 1u } afrMap[154] */
/* ITEM {  923u,   147u, 1u } afrMap[155] */
/* ITEM {  924u,   147u, 1u } afrMap[156] */
/* ITEM {  925u,   147u, 1u } afrMap[157] */
/* ITEM {  926u,   147u, 1u } afrMap[158] */
/* ITEM {  927u,   147u, 1u } afrMap[159] */
/* ITEM {  928u,   147u, 1u } afrMap[160] */
/* ITEM {  929u,   147u, 1u } afrMap[161] */
/* ITEM {  930u,   147u, 1u } afrMap[162] */
/* ITEM {  931u,   147u, 1u } afrMap[163] */
/* ITEM {  932u,   147u, 1u } afrMap[164] */
/* ITEM {  933u,   147u, 1u } afrMap[165] */
/* ITEM {  934u,   147u, 1u } afrMap[166] */
/* ITEM {  935u,   147u, 1u } afrMap[167] */
/* ITEM {  936u,   147u, 1u } afrMap[168] */
/* ITEM {  937u,   147u, 1u } afrMap[169] */
/* ITEM {  938u,   147u, 1u } afrMap[170] */
/* ITEM {  939u,   147u, 1u } afrMap[171] */
/* ITEM {  940u,   147u, 1u } afrMap[172] */
/* ITEM {  941u,   147u, 1u } afrMap[173] */
/* ITEM {  942u,   147u, 1u } afrMap[174] */
/* ITEM {  943u,   147u, 1u } afrMap[175] */
/* ITEM {  944u,   147u, 1u } afrMap[176] */
/* ITEM {  945u,   147u, 1u } afrMap[177] */
/* ITEM {  946u,   147u, 1u } afrMap[178] */
/* ITEM {  947u,   147u, 1u } afrMap[179] */
/* ITEM {  948u,   147u, 1u } afrMap[180] */
/* ITEM {  949u,   147u, 1u } afrMap[181] */
/* ITEM {  950u,   147u, 1u } afrMap[182] */
/* ITEM {  951u,   147u, 1u } afrMap[183] */
/* ITEM {  952u,   147u, 1u } afrMap[184] */
/* ITEM {  953u,   147u, 1u } afrMap[185] */
/* ITEM {  954u,   147u, 1u } afrMap[186] */
/* ITEM {  955u,   147u, 1u } afrMap[187] */
/* ITEM {  956u,   147u, 1u } afrMap[188] */
/* ITEM {  957u,   147u, 1u } afrMap[189] */
/* ITEM {  958u,   147u, 1u } afrMap[190] */
/* ITEM {  959u,   147u, 1u } afrMap[191] */
/* ITEM {  960u,   147u, 1u } afrMap[192] */
/* ITEM {  961u,   147u, 1u } afrMap[193] */
/* ITEM {  962u,   147u, 1u } afrMap[194] */
/* ITEM {  963u,   147u, 1u } afrMap[195] */
/* ITEM {  964u,   147u, 1u } afrMap[196] */
/* ITEM {  965u,   147u, 1u } afrMap[197] */
/* ITEM {  966u,   147u, 1u } afrMap[198] */
/* ITEM {  967u,   147u, 1u } afrMap[199] */
/* ITEM {  968u,   147u, 1u } afrMap[200] */
/* ITEM {  969u,   147u, 1u } afrMap[201] */
/* ITEM {  970u,   147u, 1u } afrMap[202] */
/* ITEM {  971u,   147u, 1u } afrMap[203] */
/* ITEM {  972u,   147u, 1u } afrMap[204] */
/* ITEM {  973u,   147u, 1u } afrMap[205] */
/* ITEM {  974u,   147u, 1u } afrMap[206] */
/* ITEM {  975u,   147u, 1u } afrMap[207] */
/* ITEM {  976u,   140u, 1u } afrMap[208] */
/* ITEM {  977u,   140u, 1u } afrMap[209] */
/* ITEM {  978u,   140u, 1u } afrMap[210] */
/* ITEM {  979u,   140u, 1u } afrMap[211] */
/* ITEM {  980u,   129u, 1u } afrMap[212] */
/* ITEM {  981u,   129u, 1u } afrMap[213] */
/* ITEM {  982u,   121u, 1u } afrMap[214] */
/* ITEM {  983u,   121u, 1u } afrMap[215] */
/* ITEM {  984u,   121u, 1u } afrMap[216] */
/* ITEM {  985u,   121u, 1u } afrMap[217] */
/* ITEM {  986u,   121u, 1u } afrMap[218] */
/* ITEM {  987u,   121u, 1u } afrMap[219] */
/* ITEM {  988u,   121u, 1u } afrMap[220] */
/* ITEM {  989u,   121u, 1u } afrMap[221] */
/* ITEM {  990u,   121u, 1u } afrMap[222] */
/* ITEM {  991u,   121u, 1u } afrMap[223] */
/* ITEM {  992u,   140u, 1u } afrMap[224] */
/* ITEM {  993u,   140u, 1u } afrMap[225] */
/* ITEM {  994u,   140u, 1u } afrMap[226] */
/* ITEM {  995u,   140u, 1u } afrMap[227] */
/* ITEM {  996u,   129u, 1u } afrMap[228] */
/* ITEM {  997u,   129u, 1u } afrMap[229] */
/* ITEM {  998u,   121u, 1u } afrMap[230] */
/* ITEM {  999u,   121u, 1u } afrMap[231] */
/* ITEM { 1000u,   121u, 1u } afrMap[232] */
/* ITEM { 1001u,   121u, 1u } afrMap[233] */
/* ITEM { 1002u,   121u, 1u } afrMap[234] */
/* ITEM { 1003u,   121u, 1u } afrMap[235] */
/* ITEM { 1004u,   121u, 1u } afrMap[236] */
/* ITEM { 1005u,   121u, 1u } afrMap[237] */
/* ITEM { 1006u,   121u, 1u } afrMap[238] */
/* ITEM { 1007u,   121u, 1u } afrMap[239] */
/* ITEM { 1008u,   140u, 1u } afrMap[240] */
/* ITEM { 1009u,   140u, 1u } afrMap[241] */
/* ITEM { 1010u,   140u, 1u } afrMap[242] */
/* ITEM { 1011u,   140u, 1u } afrMap[243] */
/* ITEM { 1012u,   129u, 1u } afrMap[244] */
/* ITEM { 1013u,   129u, 1u } afrMap[245] */
/* ITEM { 1014u,   121u, 1u } afrMap[246] */
/* ITEM { 1015u,   121u, 1u } afrMap[247] */
/* ITEM { 1016u,   121u, 1u } afrMap[248] */
/* ITEM { 1017u,   121u, 1u } afrMap[249] */
/* ITEM { 1018u,   121u, 1u } afrMap[250] */
/* ITEM { 1019u,   121u, 1u } afrMap[251] */
/* ITEM { 1020u,   121u, 1u } afrMap[252] */
/* ITEM { 1021u,   121u, 1u } afrMap[253] */
/* ITEM { 1022u,   121u, 1u } afrMap[254] */
/* ITEM { 1023u,   121u, 1u } afrMap[255] */
/* ITEM { 1024u,  9700u, 2u } cltEnrAx[0] */
/* ITEM { 1026u,  9800u, 2u } cltEnrAx[1] */
/* ITEM { 1028u,  9900u, 2u } cltEnrAx[2] */
/* ITEM { 1030u, 10000u, 2u } cltEnrAx[3] */
/* ITEM { 1032u, 10100u, 2u } cltEnrAx[4] */
/* ITEM { 1034u, 10200u, 2u } cltEnrAx[5] */
/* ITEM { 1036u, 10300u, 2u } cltEnrAx[6] */
/* ITEM { 1038u, 10400u, 2u } cltEnrAx[7] */
/* ITEM { 1040u, 10500u, 2u } cltEnrAx[8] */
/* ITEM { 1042u, 10600u, 2u } cltEnrAx[9] */
/* ITEM { 1044u, 10700u, 2u } cltEnrAx[10] */
/* ITEM { 1046u, 10800u, 2u } cltEnrAx[11] */
/* ITEM { 1048u, 10900u, 2u } cltEnrAx[12] */
/* ITEM { 1050u, 11000u, 2u } cltEnrAx[13] */
/* ITEM { 1052u, 11100u, 2u } cltEnrAx[14] */
/* ITEM { 1054u, 11200u, 2u } cltEnrAx[15] */
/* ITEM { 1056u,   170u, 1u } cltEnrVal[0] */
/* ITEM { 1057u,   160u, 1u } cltEnrVal[1] */
/* ITEM { 1058u,   150u, 1u } cltEnrVal[2] */
/* ITEM { 1059u,   140u, 1u } cltEnrVal[3] */
/* ITEM { 1060u,   131u, 1u } cltEnrVal[4] */
/* ITEM { 1061u,   122u, 1u } cltEnrVal[5] */
/* ITEM { 1062u,   116u, 1u } cltEnrVal[6] */
/* ITEM { 1063u,   111u, 1u } cltEnrVal[7] */
/* ITEM { 1064u,   107u, 1u } cltEnrVal[8] */
/* ITEM { 1065u,   104u, 1u } cltEnrVal[9] */
/* ITEM { 1066u,   102u, 1u } cltEnrVal[10] */
/* ITEM { 1067u,   100u, 1u } cltEnrVal[11] */
/* ITEM { 1068u,   100u, 1u } cltEnrVal[12] */
/* ITEM { 1069u,   100u, 1u } cltEnrVal[13] */
/* ITEM { 1070u,   100u, 1u } cltEnrVal[14] */
/* ITEM { 1071u,   100u, 1u } cltEnrVal[15] */
/* ITEM { 2732u,     1u, 1u } transEnable */
/* ITEM { 2736u,    55u, 1u } wwXPct[0] */
/* ITEM { 2737u,    52u, 1u } wwXPct[1] */
/* ITEM { 2738u,    48u, 1u } wwXPct[2] */
/* ITEM { 2739u,    45u, 1u } wwXPct[3] */
/* ITEM { 2740u,    42u, 1u } wwXPct[4] */
/* ITEM { 2741u,    40u, 1u } wwXPct[5] */
/* ITEM { 2742u,    37u, 1u } wwXPct[6] */
/* ITEM { 2743u,    35u, 1u } wwXPct[7] */
/* ITEM { 2744u,    33u, 1u } wwXPct[8] */
/* ITEM { 2745u,    31u, 1u } wwXPct[9] */
/* ITEM { 2746u,    30u, 1u } wwXPct[10] */
/* ITEM { 2747u,    30u, 1u } wwXPct[11] */
/* ITEM { 2748u,    30u, 1u } wwXPct[12] */
/* ITEM { 2749u,    30u, 1u } wwXPct[13] */
/* ITEM { 2750u,    30u, 1u } wwXPct[14] */
/* ITEM { 2751u,    30u, 1u } wwXPct[15] */
/* ITEM { 2752u,   100u, 1u } wwTau[0] */
/* ITEM { 2753u,    85u, 1u } wwTau[1] */
/* ITEM { 2754u,    70u, 1u } wwTau[2] */
/* ITEM { 2755u,    60u, 1u } wwTau[3] */
/* ITEM { 2756u,    50u, 1u } wwTau[4] */
/* ITEM { 2757u,    40u, 1u } wwTau[5] */
/* ITEM { 2758u,    32u, 1u } wwTau[6] */
/* ITEM { 2759u,    26u, 1u } wwTau[7] */
/* ITEM { 2760u,    22u, 1u } wwTau[8] */
/* ITEM { 2761u,    19u, 1u } wwTau[9] */
/* ITEM { 2762u,    17u, 1u } wwTau[10] */
/* ITEM { 2763u,    15u, 1u } wwTau[11] */
/* ITEM { 2764u,    15u, 1u } wwTau[12] */
/* ITEM { 2765u,    15u, 1u } wwTau[13] */
/* ITEM { 2766u,    15u, 1u } wwTau[14] */
/* ITEM { 2767u,    15u, 1u } wwTau[15] */
/* ITEM { 2768u,    60u, 1u } asPct[0] */
/* ITEM { 2769u,    50u, 1u } asPct[1] */
/* ITEM { 2770u,    42u, 1u } asPct[2] */
/* ITEM { 2771u,    35u, 1u } asPct[3] */
/* ITEM { 2772u,    28u, 1u } asPct[4] */
/* ITEM { 2773u,    22u, 1u } asPct[5] */
/* ITEM { 2774u,    18u, 1u } asPct[6] */
/* ITEM { 2775u,    14u, 1u } asPct[7] */
/* ITEM { 2776u,    11u, 1u } asPct[8] */
/* ITEM { 2777u,     9u, 1u } asPct[9] */
/* ITEM { 2778u,     7u, 1u } asPct[10] */
/* ITEM { 2779u,     5u, 1u } asPct[11] */
/* ITEM { 2780u,     4u, 1u } asPct[12] */
/* ITEM { 2781u,     4u, 1u } asPct[13] */
/* ITEM { 2782u,     4u, 1u } asPct[14] */
/* ITEM { 2783u,     4u, 1u } asPct[15] */
/* ITEM { 2734u,  5000u, 2u } asDecayMs */
/* ITEM { 2784u,     0u, 2u } ignCltCorr[0] */
/* ITEM { 2786u,     0u, 2u } ignCltCorr[1] */
/* ITEM { 2788u,     0u, 2u } ignCltCorr[2] */
/* ITEM { 2790u,     0u, 2u } ignCltCorr[3] */
/* ITEM { 2792u,     0u, 2u } ignCltCorr[4] */
/* ITEM { 2794u,     0u, 2u } ignCltCorr[5] */
/* ITEM { 2796u,     0u, 2u } ignCltCorr[6] */
/* ITEM { 2798u,     0u, 2u } ignCltCorr[7] */
/* ITEM { 2800u,     0u, 2u } ignCltCorr[8] */
/* ITEM { 2802u,     0u, 2u } ignCltCorr[9] */
/* ITEM { 2804u,     0u, 2u } ignCltCorr[10] */
/* ITEM { 2806u,     0u, 2u } ignCltCorr[11] */
/* ITEM { 2808u,     0u, 2u } ignCltCorr[12] */
/* ITEM { 2810u,     0u, 2u } ignCltCorr[13] */
/* ITEM { 2812u,     0u, 2u } ignCltCorr[14] */
/* ITEM { 2814u,     0u, 2u } ignCltCorr[15] */
/* ITEM { 2816u,  9800u, 2u } ignIatAx[0] */
/* ITEM { 2818u, 10000u, 2u } ignIatAx[1] */
/* ITEM { 2820u, 10200u, 2u } ignIatAx[2] */
/* ITEM { 2822u, 10400u, 2u } ignIatAx[3] */
/* ITEM { 2824u, 10600u, 2u } ignIatAx[4] */
/* ITEM { 2826u, 10800u, 2u } ignIatAx[5] */
/* ITEM { 2828u, 11000u, 2u } ignIatAx[6] */
/* ITEM { 2830u, 11200u, 2u } ignIatAx[7] */
/* ITEM { 2832u,     0u, 2u } ignIatCorr[0] */
/* ITEM { 2834u,     0u, 2u } ignIatCorr[1] */
/* ITEM { 2836u,     0u, 2u } ignIatCorr[2] */
/* ITEM { 2838u,     0u, 2u } ignIatCorr[3] */
/* ITEM { 2840u,     0u, 2u } ignIatCorr[4] */
/* ITEM { 2842u,     0u, 2u } ignIatCorr[5] */
/* ITEM { 2844u,     0u, 2u } ignIatCorr[6] */
/* ITEM { 2846u,     0u, 2u } ignIatCorr[7] */
/* ITEM { 2848u,     1u, 1u } idleTimingEnable */
/* ITEM { 2850u,   100u, 2u } idleTimingKp */
/* ITEM { 2852u, 65436u, 2u } idleTimingMinX10 = -100 */
/* ITEM { 2854u,   100u, 2u } idleTimingMaxX10 */
/* ITEM { 2856u,  1000u, 2u } idleTimingSoftMs */
/* ITEM { 2858u,     0u, 2u } idleDashX10 */
/* ITEM { 2860u,  1000u, 2u } idleDashHoldMs */
/* ITEM { 2862u,  2000u, 2u } idleDashDecayMs */
/* ITEM { 2716u,  3000u, 2u } etbLimpRpm */
/* ITEM { 2592u,    37u, 1u } pinTacho */
/* ITEM { 2865u,    47u, 1u } pinMil */
/* ITEM { 2864u,     1u, 1u } celEnable */
/* ITEM { 2866u,     1u, 1u } celTestEnable */
/* ITEM { 2868u,  3000u, 2u } celTestOnMs */
/* ITEM { 2870u,  1000u, 2u } celTestGapMs */
/* ITEM { 2976u,     0u, 1u } vvtMode[0] */
/* ITEM { 2977u,     0u, 1u } vvtMode[1] */
/* ITEM { 2594u,   115u, 1u } pinCam1Sol */
/* ITEM { 2980u,   250u, 2u } vvtFreqHz */
/* ITEM { 2872u,     1u, 1u } knockMode */
/* ITEM { 2975u,   100u, 1u } knockDiagN */
/* ITEM { 2974u,    60u, 1u } knockSafeQ */
/* ITEM { 2973u,    72u, 1u } knockMaxQ */
/* ITEM { 2972u,     9u, 1u } knockStepQ */
/* ITEM { 2971u,     0u, 1u } knockStopN */
/* ITEM { 2970u,    20u, 1u } knockLearn */
/* ITEM { 2968u,  1000u, 2u } knockRefMax */
/* ITEM { 2966u,     5u, 2u } knockRefMin */
/* ITEM { 2964u,  1500u, 2u } knockDiagRpm */
/* ITEM { 2962u,   800u, 2u } knockReapplyMs */
/* ITEM { 2960u,   204u, 2u } knockRefInit */
/* ITEM { 2958u, 10390u, 2u } knockCltMin */
/* ITEM { 2956u,   400u, 2u } knockRpmMin */
/* ITEM { 2955u,    22u, 1u } knockLoadMin */
/* ITEM { 2954u,     4u, 1u } knockTpDyn */
/* ITEM { 2953u,    16u, 1u } knockTp */
/* ITEM { 2952u,    18u, 1u } knockKefDyn */
/* ITEM { 2946u,    43u, 1u } knockKef[0] */
/* ITEM { 2947u,    43u, 1u } knockKef[1] */
/* ITEM { 2948u,    42u, 1u } knockKef[2] */
/* ITEM { 2949u,    40u, 1u } knockKef[3] */
/* ITEM { 2950u,    35u, 1u } knockKef[4] */
/* ITEM { 2951u,    32u, 1u } knockKef[5] */
/* ITEM { 2934u,  1000u, 2u } knockKefRpm[0] */
/* ITEM { 2936u,  2000u, 2u } knockKefRpm[1] */
/* ITEM { 2938u,  3000u, 2u } knockKefRpm[2] */
/* ITEM { 2940u,  4000u, 2u } knockKefRpm[3] */
/* ITEM { 2942u,  5000u, 2u } knockKefRpm[4] */
/* ITEM { 2944u,  6000u, 2u } knockKefRpm[5] */
/* ITEM { 2918u,   270u, 2u } knockWinLen[0] */
/* ITEM { 2920u,   270u, 2u } knockWinLen[1] */
/* ITEM { 2922u,   278u, 2u } knockWinLen[2] */
/* ITEM { 2924u,   330u, 2u } knockWinLen[3] */
/* ITEM { 2926u,   360u, 2u } knockWinLen[4] */
/* ITEM { 2928u,   398u, 2u } knockWinLen[5] */
/* ITEM { 2930u,   413u, 2u } knockWinLen[6] */
/* ITEM { 2932u,   413u, 2u } knockWinLen[7] */
/* ITEM { 2902u,   120u, 2u } knockWinStart[0] */
/* ITEM { 2904u,   195u, 2u } knockWinStart[1] */
/* ITEM { 2906u,   165u, 2u } knockWinStart[2] */
/* ITEM { 2908u,   172u, 2u } knockWinStart[3] */
/* ITEM { 2910u,   195u, 2u } knockWinStart[4] */
/* ITEM { 2912u,   202u, 2u } knockWinStart[5] */
/* ITEM { 2914u,   180u, 2u } knockWinStart[6] */
/* ITEM { 2916u,   180u, 2u } knockWinStart[7] */
/* ITEM { 2886u,   800u, 2u } knockRpmAx[0] */
/* ITEM { 2888u,  1600u, 2u } knockRpmAx[1] */
/* ITEM { 2890u,  2400u, 2u } knockRpmAx[2] */
/* ITEM { 2892u,  3200u, 2u } knockRpmAx[3] */
/* ITEM { 2894u,  4000u, 2u } knockRpmAx[4] */
/* ITEM { 2896u,  4800u, 2u } knockRpmAx[5] */
/* ITEM { 2898u,  5600u, 2u } knockRpmAx[6] */
/* ITEM { 2900u,  6400u, 2u } knockRpmAx[7] */
/* ITEM { 2878u,     1u, 1u } knockSensor[0] */
/* ITEM { 2879u,     1u, 1u } knockSensor[1] */
/* ITEM { 2880u,     0u, 1u } knockSensor[2] */
/* ITEM { 2881u,     0u, 1u } knockSensor[3] */
/* ITEM { 2882u,     0u, 1u } knockSensor[4] */
/* ITEM { 2883u,     0u, 1u } knockSensor[5] */
/* ITEM { 2884u,     0u, 1u } knockSensor[6] */
/* ITEM { 2885u,     0u, 1u } knockSensor[7] */
/* ITEM { 2874u,     2u, 1u } knockGain[0] */
/* ITEM { 2875u,     2u, 1u } knockGain[1] */
/* ITEM { 2876u,     2u, 1u } knockGain[2] */
/* ITEM { 2877u,     2u, 1u } knockGain[3] */
/* ITEM { 2873u,     7u, 1u } knockBand */
/* ITEM { 1626u,   500u, 2u } pedalRpmAx[0] */
/* ITEM { 1628u,   950u, 2u } pedalRpmAx[1] */
/* ITEM { 1630u,  1400u, 2u } pedalRpmAx[2] */
/* ITEM { 1632u,  1850u, 2u } pedalRpmAx[3] */
/* ITEM { 1634u,  2300u, 2u } pedalRpmAx[4] */
/* ITEM { 1636u,  2750u, 2u } pedalRpmAx[5] */
/* ITEM { 1638u,  3200u, 2u } pedalRpmAx[6] */
/* ITEM { 1640u,  3650u, 2u } pedalRpmAx[7] */
/* ITEM { 1642u,  4100u, 2u } pedalRpmAx[8] */
/* ITEM { 1644u,  4550u, 2u } pedalRpmAx[9] */
/* ITEM { 1646u,  5000u, 2u } pedalRpmAx[10] */
/* ITEM { 1648u,  5450u, 2u } pedalRpmAx[11] */
/* ITEM { 1650u,  5900u, 2u } pedalRpmAx[12] */
/* ITEM { 1652u,  6350u, 2u } pedalRpmAx[13] */
/* ITEM { 1654u,  6800u, 2u } pedalRpmAx[14] */
/* ITEM { 1656u,  7250u, 2u } pedalRpmAx[15] */
/* ITEM { 1658u,     0u, 2u } pedalAx[0] */
/* ITEM { 1660u,    50u, 2u } pedalAx[1] */
/* ITEM { 1662u,   100u, 2u } pedalAx[2] */
/* ITEM { 1664u,   150u, 2u } pedalAx[3] */
/* ITEM { 1666u,   200u, 2u } pedalAx[4] */
/* ITEM { 1668u,   250u, 2u } pedalAx[5] */
/* ITEM { 1670u,   300u, 2u } pedalAx[6] */
/* ITEM { 1672u,   400u, 2u } pedalAx[7] */
/* ITEM { 1674u,   500u, 2u } pedalAx[8] */
/* ITEM { 1676u,   600u, 2u } pedalAx[9] */
/* ITEM { 1678u,   700u, 2u } pedalAx[10] */
/* ITEM { 1680u,   800u, 2u } pedalAx[11] */
/* ITEM { 1682u,   850u, 2u } pedalAx[12] */
/* ITEM { 1684u,   900u, 2u } pedalAx[13] */
/* ITEM { 1686u,   950u, 2u } pedalAx[14] */
/* ITEM { 1688u,  1000u, 2u } pedalAx[15] */
/* ITEM { 1370u,     8u, 1u } pedalMap[0] */
/* ITEM { 1371u,     8u, 1u } pedalMap[1] */
/* ITEM { 1372u,     8u, 1u } pedalMap[2] */
/* ITEM { 1373u,     8u, 1u } pedalMap[3] */
/* ITEM { 1374u,     8u, 1u } pedalMap[4] */
/* ITEM { 1375u,     8u, 1u } pedalMap[5] */
/* ITEM { 1376u,     8u, 1u } pedalMap[6] */
/* ITEM { 1377u,     8u, 1u } pedalMap[7] */
/* ITEM { 1378u,     8u, 1u } pedalMap[8] */
/* ITEM { 1379u,     8u, 1u } pedalMap[9] */
/* ITEM { 1380u,     8u, 1u } pedalMap[10] */
/* ITEM { 1381u,     8u, 1u } pedalMap[11] */
/* ITEM { 1382u,     8u, 1u } pedalMap[12] */
/* ITEM { 1383u,     8u, 1u } pedalMap[13] */
/* ITEM { 1384u,     8u, 1u } pedalMap[14] */
/* ITEM { 1385u,     8u, 1u } pedalMap[15] */
/* ITEM { 1386u,    12u, 1u } pedalMap[16] */
/* ITEM { 1387u,    12u, 1u } pedalMap[17] */
/* ITEM { 1388u,    12u, 1u } pedalMap[18] */
/* ITEM { 1389u,    12u, 1u } pedalMap[19] */
/* ITEM { 1390u,    12u, 1u } pedalMap[20] */
/* ITEM { 1391u,    12u, 1u } pedalMap[21] */
/* ITEM { 1392u,    12u, 1u } pedalMap[22] */
/* ITEM { 1393u,    12u, 1u } pedalMap[23] */
/* ITEM { 1394u,    12u, 1u } pedalMap[24] */
/* ITEM { 1395u,    12u, 1u } pedalMap[25] */
/* ITEM { 1396u,    12u, 1u } pedalMap[26] */
/* ITEM { 1397u,    12u, 1u } pedalMap[27] */
/* ITEM { 1398u,    12u, 1u } pedalMap[28] */
/* ITEM { 1399u,    12u, 1u } pedalMap[29] */
/* ITEM { 1400u,    12u, 1u } pedalMap[30] */
/* ITEM { 1401u,    12u, 1u } pedalMap[31] */
/* ITEM { 1402u,    16u, 1u } pedalMap[32] */
/* ITEM { 1403u,    16u, 1u } pedalMap[33] */
/* ITEM { 1404u,    16u, 1u } pedalMap[34] */
/* ITEM { 1405u,    16u, 1u } pedalMap[35] */
/* ITEM { 1406u,    16u, 1u } pedalMap[36] */
/* ITEM { 1407u,    16u, 1u } pedalMap[37] */
/* ITEM { 1408u,    16u, 1u } pedalMap[38] */
/* ITEM { 1409u,    16u, 1u } pedalMap[39] */
/* ITEM { 1410u,    16u, 1u } pedalMap[40] */
/* ITEM { 1411u,    16u, 1u } pedalMap[41] */
/* ITEM { 1412u,    16u, 1u } pedalMap[42] */
/* ITEM { 1413u,    16u, 1u } pedalMap[43] */
/* ITEM { 1414u,    16u, 1u } pedalMap[44] */
/* ITEM { 1415u,    16u, 1u } pedalMap[45] */
/* ITEM { 1416u,    16u, 1u } pedalMap[46] */
/* ITEM { 1417u,    16u, 1u } pedalMap[47] */
/* ITEM { 1418u,    21u, 1u } pedalMap[48] */
/* ITEM { 1419u,    21u, 1u } pedalMap[49] */
/* ITEM { 1420u,    21u, 1u } pedalMap[50] */
/* ITEM { 1421u,    21u, 1u } pedalMap[51] */
/* ITEM { 1422u,    21u, 1u } pedalMap[52] */
/* ITEM { 1423u,    21u, 1u } pedalMap[53] */
/* ITEM { 1424u,    21u, 1u } pedalMap[54] */
/* ITEM { 1425u,    21u, 1u } pedalMap[55] */
/* ITEM { 1426u,    21u, 1u } pedalMap[56] */
/* ITEM { 1427u,    21u, 1u } pedalMap[57] */
/* ITEM { 1428u,    21u, 1u } pedalMap[58] */
/* ITEM { 1429u,    21u, 1u } pedalMap[59] */
/* ITEM { 1430u,    21u, 1u } pedalMap[60] */
/* ITEM { 1431u,    21u, 1u } pedalMap[61] */
/* ITEM { 1432u,    21u, 1u } pedalMap[62] */
/* ITEM { 1433u,    21u, 1u } pedalMap[63] */
/* ITEM { 1434u,    27u, 1u } pedalMap[64] */
/* ITEM { 1435u,    27u, 1u } pedalMap[65] */
/* ITEM { 1436u,    27u, 1u } pedalMap[66] */
/* ITEM { 1437u,    27u, 1u } pedalMap[67] */
/* ITEM { 1438u,    27u, 1u } pedalMap[68] */
/* ITEM { 1439u,    27u, 1u } pedalMap[69] */
/* ITEM { 1440u,    27u, 1u } pedalMap[70] */
/* ITEM { 1441u,    27u, 1u } pedalMap[71] */
/* ITEM { 1442u,    27u, 1u } pedalMap[72] */
/* ITEM { 1443u,    27u, 1u } pedalMap[73] */
/* ITEM { 1444u,    27u, 1u } pedalMap[74] */
/* ITEM { 1445u,    27u, 1u } pedalMap[75] */
/* ITEM { 1446u,    27u, 1u } pedalMap[76] */
/* ITEM { 1447u,    27u, 1u } pedalMap[77] */
/* ITEM { 1448u,    27u, 1u } pedalMap[78] */
/* ITEM { 1449u,    27u, 1u } pedalMap[79] */
/* ITEM { 1450u,    33u, 1u } pedalMap[80] */
/* ITEM { 1451u,    33u, 1u } pedalMap[81] */
/* ITEM { 1452u,    33u, 1u } pedalMap[82] */
/* ITEM { 1453u,    33u, 1u } pedalMap[83] */
/* ITEM { 1454u,    33u, 1u } pedalMap[84] */
/* ITEM { 1455u,    33u, 1u } pedalMap[85] */
/* ITEM { 1456u,    33u, 1u } pedalMap[86] */
/* ITEM { 1457u,    33u, 1u } pedalMap[87] */
/* ITEM { 1458u,    33u, 1u } pedalMap[88] */
/* ITEM { 1459u,    33u, 1u } pedalMap[89] */
/* ITEM { 1460u,    33u, 1u } pedalMap[90] */
/* ITEM { 1461u,    33u, 1u } pedalMap[91] */
/* ITEM { 1462u,    33u, 1u } pedalMap[92] */
/* ITEM { 1463u,    33u, 1u } pedalMap[93] */
/* ITEM { 1464u,    33u, 1u } pedalMap[94] */
/* ITEM { 1465u,    33u, 1u } pedalMap[95] */
/* ITEM { 1466u,    40u, 1u } pedalMap[96] */
/* ITEM { 1467u,    40u, 1u } pedalMap[97] */
/* ITEM { 1468u,    40u, 1u } pedalMap[98] */
/* ITEM { 1469u,    40u, 1u } pedalMap[99] */
/* ITEM { 1470u,    40u, 1u } pedalMap[100] */
/* ITEM { 1471u,    40u, 1u } pedalMap[101] */
/* ITEM { 1472u,    40u, 1u } pedalMap[102] */
/* ITEM { 1473u,    40u, 1u } pedalMap[103] */
/* ITEM { 1474u,    40u, 1u } pedalMap[104] */
/* ITEM { 1475u,    40u, 1u } pedalMap[105] */
/* ITEM { 1476u,    40u, 1u } pedalMap[106] */
/* ITEM { 1477u,    40u, 1u } pedalMap[107] */
/* ITEM { 1478u,    40u, 1u } pedalMap[108] */
/* ITEM { 1479u,    40u, 1u } pedalMap[109] */
/* ITEM { 1480u,    40u, 1u } pedalMap[110] */
/* ITEM { 1481u,    40u, 1u } pedalMap[111] */
/* ITEM { 1482u,    56u, 1u } pedalMap[112] */
/* ITEM { 1483u,    56u, 1u } pedalMap[113] */
/* ITEM { 1484u,    56u, 1u } pedalMap[114] */
/* ITEM { 1485u,    56u, 1u } pedalMap[115] */
/* ITEM { 1486u,    56u, 1u } pedalMap[116] */
/* ITEM { 1487u,    56u, 1u } pedalMap[117] */
/* ITEM { 1488u,    56u, 1u } pedalMap[118] */
/* ITEM { 1489u,    56u, 1u } pedalMap[119] */
/* ITEM { 1490u,    56u, 1u } pedalMap[120] */
/* ITEM { 1491u,    56u, 1u } pedalMap[121] */
/* ITEM { 1492u,    56u, 1u } pedalMap[122] */
/* ITEM { 1493u,    56u, 1u } pedalMap[123] */
/* ITEM { 1494u,    56u, 1u } pedalMap[124] */
/* ITEM { 1495u,    56u, 1u } pedalMap[125] */
/* ITEM { 1496u,    56u, 1u } pedalMap[126] */
/* ITEM { 1497u,    56u, 1u } pedalMap[127] */
/* ITEM { 1498u,    74u, 1u } pedalMap[128] */
/* ITEM { 1499u,    74u, 1u } pedalMap[129] */
/* ITEM { 1500u,    74u, 1u } pedalMap[130] */
/* ITEM { 1501u,    74u, 1u } pedalMap[131] */
/* ITEM { 1502u,    74u, 1u } pedalMap[132] */
/* ITEM { 1503u,    74u, 1u } pedalMap[133] */
/* ITEM { 1504u,    74u, 1u } pedalMap[134] */
/* ITEM { 1505u,    74u, 1u } pedalMap[135] */
/* ITEM { 1506u,    74u, 1u } pedalMap[136] */
/* ITEM { 1507u,    74u, 1u } pedalMap[137] */
/* ITEM { 1508u,    74u, 1u } pedalMap[138] */
/* ITEM { 1509u,    74u, 1u } pedalMap[139] */
/* ITEM { 1510u,    74u, 1u } pedalMap[140] */
/* ITEM { 1511u,    74u, 1u } pedalMap[141] */
/* ITEM { 1512u,    74u, 1u } pedalMap[142] */
/* ITEM { 1513u,    74u, 1u } pedalMap[143] */
/* ITEM { 1514u,    94u, 1u } pedalMap[144] */
/* ITEM { 1515u,    94u, 1u } pedalMap[145] */
/* ITEM { 1516u,    94u, 1u } pedalMap[146] */
/* ITEM { 1517u,    94u, 1u } pedalMap[147] */
/* ITEM { 1518u,    94u, 1u } pedalMap[148] */
/* ITEM { 1519u,    94u, 1u } pedalMap[149] */
/* ITEM { 1520u,    94u, 1u } pedalMap[150] */
/* ITEM { 1521u,    94u, 1u } pedalMap[151] */
/* ITEM { 1522u,    94u, 1u } pedalMap[152] */
/* ITEM { 1523u,    94u, 1u } pedalMap[153] */
/* ITEM { 1524u,    94u, 1u } pedalMap[154] */
/* ITEM { 1525u,    94u, 1u } pedalMap[155] */
/* ITEM { 1526u,    94u, 1u } pedalMap[156] */
/* ITEM { 1527u,    94u, 1u } pedalMap[157] */
/* ITEM { 1528u,    94u, 1u } pedalMap[158] */
/* ITEM { 1529u,    94u, 1u } pedalMap[159] */
/* ITEM { 1530u,   116u, 1u } pedalMap[160] */
/* ITEM { 1531u,   116u, 1u } pedalMap[161] */
/* ITEM { 1532u,   116u, 1u } pedalMap[162] */
/* ITEM { 1533u,   116u, 1u } pedalMap[163] */
/* ITEM { 1534u,   116u, 1u } pedalMap[164] */
/* ITEM { 1535u,   116u, 1u } pedalMap[165] */
/* ITEM { 1536u,   116u, 1u } pedalMap[166] */
/* ITEM { 1537u,   116u, 1u } pedalMap[167] */
/* ITEM { 1538u,   116u, 1u } pedalMap[168] */
/* ITEM { 1539u,   116u, 1u } pedalMap[169] */
/* ITEM { 1540u,   116u, 1u } pedalMap[170] */
/* ITEM { 1541u,   116u, 1u } pedalMap[171] */
/* ITEM { 1542u,   116u, 1u } pedalMap[172] */
/* ITEM { 1543u,   116u, 1u } pedalMap[173] */
/* ITEM { 1544u,   116u, 1u } pedalMap[174] */
/* ITEM { 1545u,   116u, 1u } pedalMap[175] */
/* ITEM { 1546u,   140u, 1u } pedalMap[176] */
/* ITEM { 1547u,   140u, 1u } pedalMap[177] */
/* ITEM { 1548u,   140u, 1u } pedalMap[178] */
/* ITEM { 1549u,   140u, 1u } pedalMap[179] */
/* ITEM { 1550u,   140u, 1u } pedalMap[180] */
/* ITEM { 1551u,   140u, 1u } pedalMap[181] */
/* ITEM { 1552u,   140u, 1u } pedalMap[182] */
/* ITEM { 1553u,   140u, 1u } pedalMap[183] */
/* ITEM { 1554u,   140u, 1u } pedalMap[184] */
/* ITEM { 1555u,   140u, 1u } pedalMap[185] */
/* ITEM { 1556u,   140u, 1u } pedalMap[186] */
/* ITEM { 1557u,   140u, 1u } pedalMap[187] */
/* ITEM { 1558u,   140u, 1u } pedalMap[188] */
/* ITEM { 1559u,   140u, 1u } pedalMap[189] */
/* ITEM { 1560u,   140u, 1u } pedalMap[190] */
/* ITEM { 1561u,   140u, 1u } pedalMap[191] */
/* ITEM { 1562u,   153u, 1u } pedalMap[192] */
/* ITEM { 1563u,   153u, 1u } pedalMap[193] */
/* ITEM { 1564u,   153u, 1u } pedalMap[194] */
/* ITEM { 1565u,   153u, 1u } pedalMap[195] */
/* ITEM { 1566u,   153u, 1u } pedalMap[196] */
/* ITEM { 1567u,   153u, 1u } pedalMap[197] */
/* ITEM { 1568u,   153u, 1u } pedalMap[198] */
/* ITEM { 1569u,   153u, 1u } pedalMap[199] */
/* ITEM { 1570u,   153u, 1u } pedalMap[200] */
/* ITEM { 1571u,   153u, 1u } pedalMap[201] */
/* ITEM { 1572u,   153u, 1u } pedalMap[202] */
/* ITEM { 1573u,   153u, 1u } pedalMap[203] */
/* ITEM { 1574u,   153u, 1u } pedalMap[204] */
/* ITEM { 1575u,   153u, 1u } pedalMap[205] */
/* ITEM { 1576u,   153u, 1u } pedalMap[206] */
/* ITEM { 1577u,   153u, 1u } pedalMap[207] */
/* ITEM { 1578u,   167u, 1u } pedalMap[208] */
/* ITEM { 1579u,   167u, 1u } pedalMap[209] */
/* ITEM { 1580u,   167u, 1u } pedalMap[210] */
/* ITEM { 1581u,   167u, 1u } pedalMap[211] */
/* ITEM { 1582u,   167u, 1u } pedalMap[212] */
/* ITEM { 1583u,   167u, 1u } pedalMap[213] */
/* ITEM { 1584u,   167u, 1u } pedalMap[214] */
/* ITEM { 1585u,   167u, 1u } pedalMap[215] */
/* ITEM { 1586u,   167u, 1u } pedalMap[216] */
/* ITEM { 1587u,   167u, 1u } pedalMap[217] */
/* ITEM { 1588u,   167u, 1u } pedalMap[218] */
/* ITEM { 1589u,   167u, 1u } pedalMap[219] */
/* ITEM { 1590u,   167u, 1u } pedalMap[220] */
/* ITEM { 1591u,   167u, 1u } pedalMap[221] */
/* ITEM { 1592u,   167u, 1u } pedalMap[222] */
/* ITEM { 1593u,   167u, 1u } pedalMap[223] */
/* ITEM { 1594u,   183u, 1u } pedalMap[224] */
/* ITEM { 1595u,   183u, 1u } pedalMap[225] */
/* ITEM { 1596u,   183u, 1u } pedalMap[226] */
/* ITEM { 1597u,   183u, 1u } pedalMap[227] */
/* ITEM { 1598u,   183u, 1u } pedalMap[228] */
/* ITEM { 1599u,   183u, 1u } pedalMap[229] */
/* ITEM { 1600u,   183u, 1u } pedalMap[230] */
/* ITEM { 1601u,   183u, 1u } pedalMap[231] */
/* ITEM { 1602u,   183u, 1u } pedalMap[232] */
/* ITEM { 1603u,   183u, 1u } pedalMap[233] */
/* ITEM { 1604u,   183u, 1u } pedalMap[234] */
/* ITEM { 1605u,   183u, 1u } pedalMap[235] */
/* ITEM { 1606u,   183u, 1u } pedalMap[236] */
/* ITEM { 1607u,   183u, 1u } pedalMap[237] */
/* ITEM { 1608u,   183u, 1u } pedalMap[238] */
/* ITEM { 1609u,   183u, 1u } pedalMap[239] */
/* ITEM { 1610u,   200u, 1u } pedalMap[240] */
/* ITEM { 1611u,   200u, 1u } pedalMap[241] */
/* ITEM { 1612u,   200u, 1u } pedalMap[242] */
/* ITEM { 1613u,   200u, 1u } pedalMap[243] */
/* ITEM { 1614u,   200u, 1u } pedalMap[244] */
/* ITEM { 1615u,   200u, 1u } pedalMap[245] */
/* ITEM { 1616u,   200u, 1u } pedalMap[246] */
/* ITEM { 1617u,   200u, 1u } pedalMap[247] */
/* ITEM { 1618u,   200u, 1u } pedalMap[248] */
/* ITEM { 1619u,   200u, 1u } pedalMap[249] */
/* ITEM { 1620u,   200u, 1u } pedalMap[250] */
/* ITEM { 1621u,   200u, 1u } pedalMap[251] */
/* ITEM { 1622u,   200u, 1u } pedalMap[252] */
/* ITEM { 1623u,   200u, 1u } pedalMap[253] */
/* ITEM { 1624u,   200u, 1u } pedalMap[254] */
/* ITEM { 1625u,   200u, 1u } pedalMap[255] */
/* ITEM { 2694u,     1u, 1u } camPhaseMode */
/* ITEM { 2695u,     1u, 1u } camPhaseLevel */
/* ITEM { 2696u,  1260u, 2u } camPhaseAngleX10 */
/* ITEM { 2698u,     2u, 1u } camPhaseConfirm */
/* ITEM { 2704u,    10u, 1u } camToothTol */
/* ITEM { 2700u,     3u, 1u } cam1Pattern */
/* ITEM { 2701u,     0u, 1u } cam2Pattern */
/* ITEM { 2684u,   800u, 2u } dbwMaxDutyX10 */
/* ITEM { 2726u,   140u, 2u } dbwFaultDebounceMs */
/* ITEM { 3746u,  2000u, 2u } dbwPwmHz */
/* ITEM { 3748u,    80u, 2u } dbwFrictionX10 */
/* ITEM { 2688u,     2u, 2u } dbwDeadbandX10 */
/* ITEM { 1320u,     1u, 2u } dbwSfMode */
static const unsigned char HC_PRESET_MEM runs_vag_18t_me711[] = {
    0x00u, 0x02u, 10u, /* offset 2 */
        0x04u, 0x04u, 0x00u, 0x00u, 0x15u, 0x18u, 0x07u, 0x08u, 0x0Eu, 0x10u,
    0x0Cu, 0xEAu, 1u, /* offset 3306 */
        0x01u,
    0x09u, 0xD4u, 4u, /* offset 2516 */
        0x01u, 0x01u, 0x01u, 0x01u,
    0x00u, 0x14u, 8u, /* offset 20 */
        0x00u, 0x3Cu, 0x02u, 0x00u, 0x00u, 0x19u, 0x06u, 0xC8u,
    0x09u, 0xEBu, 1u, /* offset 2539 */
        0x01u,
    0x00u, 0x20u, 1u, /* offset 32 */
        0x01u,
    0x09u, 0xEAu, 1u, /* offset 2538 */
        0x02u,
    0x00u, 0x1Cu, 4u, /* offset 28 */
        0x1Du, 0x4Cu, 0x00u, 0x50u,
    0x09u, 0xF7u, 24u, /* offset 2551 */
        0x60u, 0x59u, 0x61u, 0x58u, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu,
        0x66u, 0x5Fu, 0x67u, 0x5Eu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu,
    0x00u, 0x22u, 4u, /* offset 34 */
        0x00u, 0x03u, 0x01u, 0x02u,
    0x00u, 0x2Au, 4u, /* offset 42 */
        0x00u, 0x03u, 0x01u, 0x02u,
    0x09u, 0xF4u, 3u, /* offset 2548 */
        0x52u, 0x56u, 0xFFu,
    0x0Au, 0x13u, 4u, /* offset 2579 */
        0x5Cu, 0x54u, 0x23u, 0x22u,
    0x0Au, 0x0Fu, 1u, /* offset 2575 */
        0x65u,
    0x0Au, 0x11u, 2u, /* offset 2577 */
        0x5Du, 0x1Au,
    0x09u, 0xE8u, 2u, /* offset 2536 */
        0x02u, 0x02u,
    0x0Au, 0xAAu, 1u, /* offset 2730 */
        0x01u,
    0x00u, 0x3Au, 2u, /* offset 58 */
        0x11u, 0x30u,
    0x0Au, 0x46u, 1u, /* offset 2630 */
        0x01u,
    0x0Au, 0x79u, 1u, /* offset 2681 */
        0x01u,
    0x0Au, 0x47u, 1u, /* offset 2631 */
        0x01u,
    0x0Au, 0x42u, 2u, /* offset 2626 */
        0x00u, 0x0Fu,
    0x0Au, 0x49u, 1u, /* offset 2633 */
        0x00u,
    0x0Au, 0x1Fu, 1u, /* offset 2591 */
        0x41u,
    0x04u, 0x80u, 64u, /* offset 1152 */
        0x00u, 0xB6u, 0x00u, 0xEEu, 0x01u, 0x1Cu, 0x01u, 0x51u, 0x01u, 0xACu, 0x02u, 0x15u,
        0x02u, 0xA8u, 0x02u, 0xEFu, 0x03u, 0x0Fu, 0x03u, 0x2Cu, 0x03u, 0x62u, 0x03u, 0x8Cu,
        0x03u, 0xAEu, 0x03u, 0xC7u, 0x03u, 0xE4u, 0x03u, 0xF0u, 0x2Cu, 0xA8u, 0x2Cu, 0x24u,
        0x2Bu, 0xC0u, 0x2Bu, 0x5Cu, 0x2Au, 0xC6u, 0x2Au, 0x30u, 0x29u, 0x68u, 0x29u, 0x04u,
        0x28u, 0xD2u, 0x28u, 0xA0u, 0x28u, 0x3Cu, 0x27u, 0xD8u, 0x27u, 0x74u, 0x27u, 0x10u,
        0x26u, 0x48u, 0x25u, 0x80u,
    0x04u, 0xE6u, 64u, /* offset 1254 */
        0x00u, 0x1Cu, 0x00u, 0x30u, 0x00u, 0x40u, 0x00u, 0x5Cu, 0x00u, 0x74u, 0x00u, 0x94u,
        0x00u, 0xC0u, 0x00u, 0xF4u, 0x01u, 0x34u, 0x01u, 0x74u, 0x01u, 0xB0u, 0x02u, 0x3Cu,
        0x02u, 0x98u, 0x02u, 0xE8u, 0x03u, 0x60u, 0x03u, 0x84u, 0x2Cu, 0x8Bu, 0x2Bu, 0xC0u,
        0x2Bu, 0x2Au, 0x2Au, 0x94u, 0x2Au, 0x33u, 0x29u, 0xCAu, 0x29u, 0x68u, 0x29u, 0x07u,
        0x28u, 0x9Eu, 0x28u, 0x53u, 0x28u, 0x08u, 0x27u, 0x72u, 0x27u, 0x10u, 0x26u, 0xAEu,
        0x25u, 0xE4u, 0x25u, 0x82u,
    0x0Au, 0x21u, 1u, /* offset 2593 */
        0x68u,
    0x0Au, 0x1Eu, 1u, /* offset 2590 */
        0x17u,
    0x00u, 0x49u, 1u, /* offset 73 */
        0x02u,
    0x09u, 0xCEu, 2u, /* offset 2510 */
        0x06u, 0xF5u,
    0x0Au, 0x4Eu, 4u, /* offset 2638 */
        0x01u, 0x2Du, 0x01u, 0x2Cu,
    0x04u, 0x70u, 16u, /* offset 1136 */
        0x07u, 0x55u, 0x07u, 0x3Au, 0x04u, 0x3Du, 0x02u, 0xADu, 0x02u, 0x2Du, 0x01u, 0xB5u,
        0x01u, 0x0Bu, 0x01u, 0x0Bu,
    0x04u, 0x60u, 16u, /* offset 1120 */
        0x03u, 0xE8u, 0x03u, 0x20u, 0x01u, 0xA4u, 0x01u, 0x40u, 0x01u, 0x22u, 0x01u, 0x0Eu,
        0x00u, 0xF0u, 0x00u, 0xC8u,
    0x04u, 0x50u, 16u, /* offset 1104 */
        0x02u, 0x56u, 0x03u, 0x23u, 0x03u, 0xE8u, 0x04u, 0xADu, 0x05u, 0x16u, 0x05u, 0x79u,
        0x06u, 0x3Eu, 0x07u, 0x03u,
    0x0Au, 0x52u, 2u, /* offset 2642 */
        0x00u, 0x00u,
    0x04u, 0xC0u, 4u, /* offset 1216 */
        0x00u, 0x00u, 0x0Au, 0x52u,
    0x04u, 0xD4u, 1u, /* offset 1236 */
        0x01u,
    0x0Eu, 0x7Eu, 2u, /* offset 3710 */
        0x00u, 0x02u,
    0x0Eu, 0x81u, 1u, /* offset 3713 */
        0x02u,
    0x02u, 0x80u, 64u, /* offset 640 */
        0x01u, 0xF4u, 0x03u, 0xB6u, 0x05u, 0x78u, 0x07u, 0x3Au, 0x08u, 0xFCu, 0x0Au, 0xBEu,
        0x0Cu, 0x80u, 0x0Eu, 0x42u, 0x10u, 0x04u, 0x11u, 0xC6u, 0x13u, 0x88u, 0x15u, 0x4Au,
        0x17u, 0x0Cu, 0x18u, 0xCEu, 0x1Au, 0x90u, 0x1Cu, 0x52u, 0x00u, 0x00u, 0x00u, 0x0Au,
        0x00u, 0x14u, 0x00u, 0x1Eu, 0x00u, 0x28u, 0x00u, 0x37u, 0x00u, 0x46u, 0x00u, 0x64u,
        0x00u, 0x82u, 0x00u, 0xA0u, 0x00u, 0xC8u, 0x00u, 0xFAu, 0x01u, 0x2Cu, 0x01u, 0x90u,
        0x01u, 0xF4u, 0x03u, 0xE8u,
    0x00u, 0x80u, 254u, /* offset 128 */
        0x00u, 0x5Au, 0x00u, 0x30u, 0x00u, 0x20u, 0x00u, 0x18u, 0x00u, 0x14u, 0x00u, 0x10u,
        0x00u, 0x0Eu, 0x00u, 0x0Cu, 0x00u, 0x0Bu, 0x00u, 0x0Au, 0x00u, 0x09u, 0x00u, 0x08u,
        0x00u, 0x08u, 0x00u, 0x07u, 0x00u, 0x07u, 0x00u, 0x06u, 0x00u, 0xB5u, 0x00u, 0x5Fu,
        0x00u, 0x40u, 0x00u, 0x30u, 0x00u, 0x27u, 0x00u, 0x20u, 0x00u, 0x1Cu, 0x00u, 0x18u,
        0x00u, 0x16u, 0x00u, 0x14u, 0x00u, 0x12u, 0x00u, 0x10u, 0x00u, 0x0Fu, 0x00u, 0x0Eu,
        0x00u, 0x0Du, 0x00u, 0x0Cu, 0x01u, 0x2Du, 0x00u, 0x9Fu, 0x00u, 0x6Au, 0x00u, 0x4Fu,
        0x00u, 0x40u, 0x00u, 0x35u, 0x00u, 0x2Eu, 0x00u, 0x28u, 0x00u, 0x24u, 0x00u, 0x20u,
        0x00u, 0x1Du, 0x00u, 0x1Bu, 0x00u, 0x19u, 0x00u, 0x17u, 0x00u, 0x15u, 0x00u, 0x14u,
        0x01u, 0xBCu, 0x00u, 0xEAu, 0x00u, 0x9Du, 0x00u, 0x76u, 0x00u, 0x5Fu, 0x00u, 0x4Fu,
        0x00u, 0x44u, 0x00u, 0x3Cu, 0x00u, 0x35u, 0x00u, 0x30u, 0x00u, 0x2Cu, 0x00u, 0x28u,
        0x00u, 0x25u, 0x00u, 0x22u, 0x00u, 0x20u, 0x00u, 0x1Eu, 0x02u, 0x2Du, 0x01u, 0x35u,
        0x00u, 0xD1u, 0x00u, 0x9Du, 0x00u, 0x7Eu, 0x00u, 0x69u, 0x00u, 0x5Au, 0x00u, 0x4Fu,
        0x00u, 0x47u, 0x00u, 0x40u, 0x00u, 0x3Au, 0x00u, 0x35u, 0x00u, 0x31u, 0x00u, 0x2Eu,
        0x00u, 0x2Bu, 0x00u, 0x28u, 0x02u, 0xA8u, 0x01u, 0xC0u, 0x01u, 0x2Eu, 0x00u, 0xE2u,
        0x00u, 0xB5u, 0x00u, 0x98u, 0x00u, 0x82u, 0x00u, 0x71u, 0x00u, 0x64u, 0x00u, 0x5Au,
        0x00u, 0x53u, 0x00u, 0x4Cu, 0x00u, 0x46u, 0x00u, 0x41u, 0x00u, 0x3Du, 0x00u, 0x39u,
        0x02u, 0xE5u, 0x02u, 0x2Fu, 0x01u, 0x8Bu, 0x01u, 0x28u, 0x00u, 0xEDu, 0x00u, 0xC6u,
        0x00u, 0xA9u, 0x00u, 0x92u, 0x00u, 0x81u, 0x00u, 0x75u, 0x00u, 0x6Cu, 0x00u, 0x63u,
        0x00u, 0x5Bu, 0x00u, 0x55u, 0x00u, 0x4Fu, 0x00u, 0x4Au, 0x03u, 0x1Fu, 0x02u, 0xB7u,
        0x02u, 0x37u, 0x01u, 0xBCu, 0x01u, 0x66u, 0x01u, 0x2Eu, 0x01u, 0x04u, 0x00u, 0xE4u,
        0x00u, 0xCBu, 0x00u, 0xB5u, 0x00u, 0xA3u, 0x00u, 0x94u, 0x00u, 0x88u, 0x00u, 0x7Eu,
        0x00u, 0x75u,
    0x01u, 0x7Eu, 254u, /* offset 382 */
        0x00u, 0x6Eu, 0x03u, 0x34u, 0x02u, 0xF6u, 0x02u, 0x9Fu, 0x02u, 0x42u, 0x01u, 0xECu,
        0x01u, 0xA7u, 0x01u, 0x71u, 0x01u, 0x45u, 0x01u, 0x22u, 0x01u, 0x04u, 0x00u, 0xEBu,
        0x00u, 0xD4u, 0x00u, 0xC0u, 0x00u, 0xB2u, 0x00u, 0xA6u, 0x00u, 0x9Cu, 0x03u, 0x41u,
        0x03u, 0x1Fu, 0x02u, 0xE9u, 0x02u, 0xACu, 0x02u, 0x63u, 0x02u, 0x1Du, 0x01u, 0xDFu,
        0x01u, 0xACu, 0x01u, 0x83u, 0x01u, 0x5Fu, 0x01u, 0x42u, 0x01u, 0x23u, 0x01u, 0x08u,
        0x00u, 0xF4u, 0x00u, 0xE4u, 0x00u, 0xD6u, 0x03u, 0x49u, 0x03u, 0x3Au, 0x03u, 0x1Eu,
        0x02u, 0xFFu, 0x02u, 0xCEu, 0x02u, 0x99u, 0x02u, 0x65u, 0x02u, 0x31u, 0x02u, 0x02u,
        0x01u, 0xD9u, 0x01u, 0xB5u, 0x01u, 0x8Du, 0x01u, 0x6Bu, 0x01u, 0x51u, 0x01u, 0x3Bu,
        0x01u, 0x27u, 0x03u, 0x4Du, 0x03u, 0x49u, 0x03u, 0x3Du, 0x03u, 0x33u, 0x03u, 0x1Cu,
        0x03u, 0x05u, 0x02u, 0xEEu, 0x02u, 0xCBu, 0x02u, 0xA6u, 0x02u, 0x80u, 0x02u, 0x54u,
        0x02u, 0x27u, 0x01u, 0xFDu, 0x01u, 0xDAu, 0x01u, 0xBBu, 0x01u, 0xA0u, 0x03u, 0x4Fu,
        0x03u, 0x4Eu, 0x03u, 0x48u, 0x03u, 0x46u, 0x03u, 0x39u, 0x03u, 0x2Eu, 0x03u, 0x24u,
        0x03u, 0x0Au, 0x02u, 0xF0u, 0x02u, 0xDCu, 0x02u, 0xC4u, 0x02u, 0x9Du, 0x02u, 0x78u,
        0x02u, 0x57u, 0x02u, 0x39u, 0x02u, 0x1Cu, 0x03u, 0x50u, 0x03u, 0x54u, 0x03u, 0x53u,
        0x03u, 0x59u, 0x03u, 0x58u, 0x03u, 0x5Cu, 0x03u, 0x64u, 0x03u, 0x5Bu, 0x03u, 0x53u,
        0x03u, 0x56u, 0x03u, 0x56u, 0x03u, 0x3Au, 0x03u, 0x1Eu, 0x03u, 0x08u, 0x02u, 0xF3u,
        0x02u, 0xDEu, 0x03u, 0x51u, 0x03u, 0x55u, 0x03u, 0x56u, 0x03u, 0x5Fu, 0x03u, 0x60u,
        0x03u, 0x68u, 0x03u, 0x75u, 0x03u, 0x71u, 0x03u, 0x6Fu, 0x03u, 0x7Bu, 0x03u, 0x83u,
        0x03u, 0x6Cu, 0x03u, 0x55u, 0x03u, 0x44u, 0x03u, 0x36u, 0x03u, 0x26u, 0x03u, 0x52u,
        0x03u, 0x58u, 0x03u, 0x5Au, 0x03u, 0x65u, 0x03u, 0x6Au, 0x03u, 0x78u, 0x03u, 0x8Du,
        0x03u, 0x90u, 0x03u, 0x97u, 0x03u, 0xAFu, 0x03u, 0xC7u, 0x03u, 0xB8u, 0x03u, 0xAAu,
        0x03u, 0xA4u,
    0x02u, 0x7Cu, 4u, /* offset 636 */
        0x03u, 0xA1u, 0x03u, 0x9Eu,
    0x04u, 0xD8u, 1u, /* offset 1240 */
        0x00u,
    0x0Au, 0x4Cu, 2u, /* offset 2636 */
        0x05u, 0xBEu,
    0x04u, 0xDAu, 4u, /* offset 1242 */
        0x14u, 0x00u, 0xB7u, 0x98u,
    0x05u, 0x2Au, 2u, /* offset 1322 */
        0x44u, 0xC0u,
    0x05u, 0x34u, 32u, /* offset 1332 */
        0x00u, 0x00u, 0x00u, 0x0Au, 0x00u, 0x32u, 0x00u, 0x46u, 0x00u, 0x8Cu, 0x02u, 0x8Au,
        0x02u, 0x94u, 0x03u, 0xE8u, 0x03u, 0x52u, 0x03u, 0x52u, 0x03u, 0x84u, 0x03u, 0xE8u,
        0x04u, 0xA6u, 0x04u, 0xB0u, 0x04u, 0xECu, 0x05u, 0x00u,
    0x0Au, 0x3Cu, 2u, /* offset 2620 */
        0x01u, 0x01u,
    0x00u, 0x48u, 1u, /* offset 72 */
        0x01u,
    0x0Au, 0x78u, 1u, /* offset 2680 */
        0x01u,
    0x09u, 0xECu, 2u, /* offset 2540 */
        0xFCu, 0xF4u,
    0x04u, 0xCCu, 8u, /* offset 1228 */
        0x00u, 0x96u, 0x03u, 0x51u, 0x00u, 0x4Bu, 0x01u, 0xA8u,
    0x04u, 0xC4u, 8u, /* offset 1220 */
        0x00u, 0x66u, 0x03u, 0xBAu, 0x03u, 0x97u, 0x00u, 0x47u,
    0x02u, 0xC0u, 64u, /* offset 704 */
        0x01u, 0xF4u, 0x03u, 0x20u, 0x03u, 0xE8u, 0x04u, 0xE2u, 0x05u, 0xDCu, 0x06u, 0xD6u,
        0x07u, 0xD0u, 0x09u, 0xC4u, 0x0Bu, 0xB8u, 0x0Du, 0xACu, 0x0Fu, 0xA0u, 0x11u, 0x94u,
        0x13u, 0x88u, 0x15u, 0x7Cu, 0x17u, 0x70u, 0x1Au, 0x90u, 0x00u, 0x00u, 0x00u, 0x0Au,
        0x00u, 0x14u, 0x00u, 0x1Eu, 0x00u, 0x28u, 0x00u, 0x37u, 0x00u, 0x46u, 0x00u, 0x64u,
        0x00u, 0x82u, 0x00u, 0xA0u, 0x00u, 0xC8u, 0x00u, 0xFAu, 0x01u, 0x2Cu, 0x01u, 0x90u,
        0x01u, 0xF4u, 0x03u, 0xE8u,
    0x0Cu, 0xEEu, 64u, /* offset 3310 */
        0x01u, 0xF4u, 0x03u, 0xB6u, 0x05u, 0x78u, 0x07u, 0x3Au, 0x08u, 0xFCu, 0x0Au, 0xBEu,
        0x0Cu, 0x80u, 0x0Eu, 0x42u, 0x10u, 0x04u, 0x11u, 0xC6u, 0x13u, 0x88u, 0x15u, 0x4Au,
        0x17u, 0x0Cu, 0x18u, 0xCEu, 0x1Au, 0x90u, 0x1Cu, 0x52u, 0x00u, 0x00u, 0x00u, 0x0Au,
        0x00u, 0x14u, 0x00u, 0x1Eu, 0x00u, 0x28u, 0x00u, 0x37u, 0x00u, 0x46u, 0x00u, 0x64u,
        0x00u, 0x82u, 0x00u, 0xA0u, 0x00u, 0xC8u, 0x00u, 0xFAu, 0x01u, 0x2Cu, 0x01u, 0x90u,
        0x01u, 0xF4u, 0x03u, 0xE8u,
    0x0Du, 0x3Eu, 16u, /* offset 3390 */
        0x00u, 0x00u, 0x00u, 0x32u, 0x00u, 0x64u, 0x00u, 0xC8u, 0x01u, 0x90u, 0x02u, 0x58u,
        0x03u, 0x20u, 0x03u, 0xE8u,
    0x0Du, 0x2Eu, 16u, /* offset 3374 */
        0x03u, 0x20u, 0x05u, 0xDCu, 0x07u, 0xD0u, 0x09u, 0xC4u, 0x0Bu, 0xB8u, 0x0Fu, 0xA0u,
        0x13u, 0x88u, 0x19u, 0x64u,
    0x0Du, 0x4Eu, 64u, /* offset 3406 */
        0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u,
        0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u,
        0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u,
        0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x64u, 0x69u, 0x73u, 0x7Du, 0x7Du, 0x78u, 0x73u,
        0x64u, 0x64u, 0x6Eu, 0x7Du, 0x8Cu, 0x8Cu, 0x87u, 0x7Du, 0x64u, 0x69u, 0x73u, 0x87u,
        0x96u, 0x96u, 0x91u, 0x87u,
    0x0Du, 0xA5u, 1u, /* offset 3493 */
        0x01u,
    0x0Du, 0xB2u, 8u, /* offset 3506 */
        0x0Au, 0x00u, 0x05u, 0x0Au, 0x0Au, 0x00u, 0x00u, 0x0Au,
    0x0Du, 0xACu, 2u, /* offset 3500 */
        0x02u, 0x28u,
    0x09u, 0x72u, 2u, /* offset 2418 */
        0x07u, 0xD0u,
    0x09u, 0x76u, 2u, /* offset 2422 */
        0x06u, 0x40u,
    0x09u, 0x74u, 2u, /* offset 2420 */
        0x00u, 0x14u,
    0x0Au, 0x6Eu, 2u, /* offset 2670 */
        0x2Bu, 0x8Eu,
    0x09u, 0x7Au, 1u, /* offset 2426 */
        0x01u,
    0x09u, 0xACu, 16u, /* offset 2476 */
        0x00u, 0x3Du, 0x00u, 0x38u, 0x00u, 0x33u, 0x00u, 0x2Eu, 0x00u, 0x29u, 0x00u, 0x24u,
        0x00u, 0x24u, 0x00u, 0x24u,
    0x09u, 0xC2u, 2u, /* offset 2498 */
        0x02u, 0x58u,
    0x0Eu, 0xFEu, 255u, /* offset 3838 */
        0x40u, 0x40u, 0x40u, 0x40u, 0x42u, 0x48u, 0x50u, 0x5Fu, 0x61u, 0x61u, 0x60u, 0x60u,
        0x64u, 0x6Bu, 0x72u, 0x78u, 0x40u, 0x40u, 0x40u, 0x40u, 0x42u, 0x48u, 0x50u, 0x5Fu,
        0x61u, 0x61u, 0x60u, 0x60u, 0x64u, 0x6Bu, 0x72u, 0x78u, 0x3Cu, 0x40u, 0x40u, 0x40u,
        0x42u, 0x48u, 0x50u, 0x5Fu, 0x61u, 0x61u, 0x60u, 0x60u, 0x64u, 0x6Bu, 0x72u, 0x78u,
        0x33u, 0x40u, 0x40u, 0x40u, 0x42u, 0x48u, 0x50u, 0x5Fu, 0x61u, 0x61u, 0x60u, 0x60u,
        0x64u, 0x6Bu, 0x72u, 0x78u, 0x2Du, 0x40u, 0x40u, 0x40u, 0x42u, 0x48u, 0x50u, 0x5Fu,
        0x61u, 0x61u, 0x60u, 0x60u, 0x64u, 0x6Bu, 0x72u, 0x78u, 0x28u, 0x40u, 0x40u, 0x42u,
        0x46u, 0x4Cu, 0x52u, 0x62u, 0x61u, 0x61u, 0x60u, 0x60u, 0x64u, 0x6Bu, 0x72u, 0x78u,
        0x28u, 0x3Cu, 0x44u, 0x48u, 0x4Eu, 0x56u, 0x5Cu, 0x74u, 0x6Bu, 0x61u, 0x60u, 0x60u,
        0x64u, 0x6Bu, 0x72u, 0x78u, 0x28u, 0x33u, 0x3Du, 0x4Bu, 0x53u, 0x5Cu, 0x62u, 0x6Eu,
        0x78u, 0x7Cu, 0x7Au, 0x69u, 0x65u, 0x6Bu, 0x72u, 0x78u, 0x28u, 0x31u, 0x38u, 0x44u,
        0x4Cu, 0x54u, 0x5Au, 0x67u, 0x71u, 0x76u, 0x7Au, 0x76u, 0x75u, 0x74u, 0x74u, 0x78u,
        0x28u, 0x2Fu, 0x35u, 0x40u, 0x47u, 0x4Eu, 0x53u, 0x62u, 0x6Au, 0x6Fu, 0x74u, 0x74u,
        0x71u, 0x72u, 0x76u, 0x7Au, 0x28u, 0x2Eu, 0x33u, 0x3Cu, 0x42u, 0x48u, 0x4Cu, 0x5Du,
        0x64u, 0x68u, 0x6Cu, 0x6Du, 0x6Cu, 0x6Eu, 0x74u, 0x79u, 0x28u, 0x2Eu, 0x32u, 0x3Au,
        0x40u, 0x45u, 0x48u, 0x58u, 0x5Du, 0x63u, 0x66u, 0x66u, 0x65u, 0x67u, 0x6Du, 0x74u,
        0x28u, 0x2Cu, 0x30u, 0x37u, 0x3Bu, 0x3Fu, 0x42u, 0x4Du, 0x52u, 0x59u, 0x5Bu, 0x5Cu,
        0x5Bu, 0x5Eu, 0x65u, 0x6Au, 0x28u, 0x2Au, 0x2Du, 0x31u, 0x35u, 0x38u, 0x3Au, 0x3Du,
        0x3Cu, 0x41u, 0x41u, 0x42u, 0x45u, 0x4Cu, 0x52u, 0x59u, 0x28u, 0x28u, 0x2Bu, 0x2Fu,
        0x2Eu, 0x2Fu, 0x30u, 0x33u, 0x30u, 0x36u, 0x39u, 0x3Au, 0x3Cu, 0x42u, 0x49u, 0x4Eu,
        0x28u, 0x28u, 0x2Bu, 0x2Fu, 0x2Eu, 0x2Fu, 0x30u, 0x33u, 0x30u, 0x36u, 0x39u, 0x3Au,
        0x3Cu, 0x42u, 0x49u,
    0x0Fu, 0xFDu, 1u, /* offset 4093 */
        0x4Eu,
    0x03u, 0x00u, 255u, /* offset 768 */
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u, 0x93u,
        0x93u, 0x93u, 0x93u, 0x93u, 0x8Cu, 0x8Cu, 0x8Cu, 0x8Cu, 0x81u, 0x81u, 0x79u, 0x79u,
        0x79u, 0x79u, 0x79u, 0x79u, 0x79u, 0x79u, 0x79u, 0x79u, 0x8Cu, 0x8Cu, 0x8Cu, 0x8Cu,
        0x81u, 0x81u, 0x79u, 0x79u, 0x79u, 0x79u, 0x79u, 0x79u, 0x79u, 0x79u, 0x79u, 0x79u,
        0x8Cu, 0x8Cu, 0x8Cu, 0x8Cu, 0x81u, 0x81u, 0x79u, 0x79u, 0x79u, 0x79u, 0x79u, 0x79u,
        0x79u, 0x79u, 0x79u,
    0x03u, 0xFFu, 49u, /* offset 1023 */
        0x79u, 0x25u, 0xE4u, 0x26u, 0x48u, 0x26u, 0xACu, 0x27u, 0x10u, 0x27u, 0x74u, 0x27u,
        0xD8u, 0x28u, 0x3Cu, 0x28u, 0xA0u, 0x29u, 0x04u, 0x29u, 0x68u, 0x29u, 0xCCu, 0x2Au,
        0x30u, 0x2Au, 0x94u, 0x2Au, 0xF8u, 0x2Bu, 0x5Cu, 0x2Bu, 0xC0u, 0xAAu, 0xA0u, 0x96u,
        0x8Cu, 0x83u, 0x7Au, 0x74u, 0x6Fu, 0x6Bu, 0x68u, 0x66u, 0x64u, 0x64u, 0x64u, 0x64u,
        0x64u,
    0x0Au, 0xACu, 1u, /* offset 2732 */
        0x01u,
    0x0Au, 0xB0u, 48u, /* offset 2736 */
        0x37u, 0x34u, 0x30u, 0x2Du, 0x2Au, 0x28u, 0x25u, 0x23u, 0x21u, 0x1Fu, 0x1Eu, 0x1Eu,
        0x1Eu, 0x1Eu, 0x1Eu, 0x1Eu, 0x64u, 0x55u, 0x46u, 0x3Cu, 0x32u, 0x28u, 0x20u, 0x1Au,
        0x16u, 0x13u, 0x11u, 0x0Fu, 0x0Fu, 0x0Fu, 0x0Fu, 0x0Fu, 0x3Cu, 0x32u, 0x2Au, 0x23u,
        0x1Cu, 0x16u, 0x12u, 0x0Eu, 0x0Bu, 0x09u, 0x07u, 0x05u, 0x04u, 0x04u, 0x04u, 0x04u,
    0x0Au, 0xAEu, 2u, /* offset 2734 */
        0x13u, 0x88u,
    0x0Au, 0xE0u, 65u, /* offset 2784 */
        0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u,
        0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u,
        0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x26u, 0x48u, 0x27u, 0x10u,
        0x27u, 0xD8u, 0x28u, 0xA0u, 0x29u, 0x68u, 0x2Au, 0x30u, 0x2Au, 0xF8u, 0x2Bu, 0xC0u,
        0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u,
        0x00u, 0x00u, 0x00u, 0x00u, 0x01u,
    0x0Bu, 0x22u, 14u, /* offset 2850 */
        0x00u, 0x64u, 0xFFu, 0x9Cu, 0x00u, 0x64u, 0x03u, 0xE8u, 0x00u, 0x00u, 0x03u, 0xE8u,
        0x07u, 0xD0u,
    0x0Au, 0x9Cu, 2u, /* offset 2716 */
        0x0Bu, 0xB8u,
    0x0Au, 0x20u, 1u, /* offset 2592 */
        0x25u,
    0x0Bu, 0x31u, 1u, /* offset 2865 */
        0x2Fu,
    0x0Bu, 0x30u, 1u, /* offset 2864 */
        0x01u,
    0x0Bu, 0x32u, 1u, /* offset 2866 */
        0x01u,
    0x0Bu, 0x34u, 4u, /* offset 2868 */
        0x0Bu, 0xB8u, 0x03u, 0xE8u,
    0x0Bu, 0xA0u, 2u, /* offset 2976 */
        0x00u, 0x00u,
    0x0Au, 0x22u, 1u, /* offset 2594 */
        0x73u,
    0x0Bu, 0xA4u, 2u, /* offset 2980 */
        0x00u, 0xFAu,
    0x0Bu, 0x38u, 1u, /* offset 2872 */
        0x01u,
    0x0Bu, 0x9Fu, 1u, /* offset 2975 */
        0x64u,
    0x0Bu, 0x9Eu, 1u, /* offset 2974 */
        0x3Cu,
    0x0Bu, 0x9Du, 1u, /* offset 2973 */
        0x48u,
    0x0Bu, 0x9Cu, 1u, /* offset 2972 */
        0x09u,
    0x0Bu, 0x9Bu, 1u, /* offset 2971 */
        0x00u,
    0x0Bu, 0x9Au, 1u, /* offset 2970 */
        0x14u,
    0x0Bu, 0x98u, 2u, /* offset 2968 */
        0x03u, 0xE8u,
    0x0Bu, 0x96u, 2u, /* offset 2966 */
        0x00u, 0x05u,
    0x0Bu, 0x94u, 2u, /* offset 2964 */
        0x05u, 0xDCu,
    0x0Bu, 0x92u, 2u, /* offset 2962 */
        0x03u, 0x20u,
    0x0Bu, 0x90u, 2u, /* offset 2960 */
        0x00u, 0xCCu,
    0x0Bu, 0x8Eu, 2u, /* offset 2958 */
        0x28u, 0x96u,
    0x0Bu, 0x8Cu, 2u, /* offset 2956 */
        0x01u, 0x90u,
    0x0Bu, 0x8Bu, 1u, /* offset 2955 */
        0x16u,
    0x0Bu, 0x8Au, 1u, /* offset 2954 */
        0x04u,
    0x0Bu, 0x89u, 1u, /* offset 2953 */
        0x10u,
    0x0Bu, 0x88u, 1u, /* offset 2952 */
        0x12u,
    0x0Bu, 0x82u, 6u, /* offset 2946 */
        0x2Bu, 0x2Bu, 0x2Au, 0x28u, 0x23u, 0x20u,
    0x0Bu, 0x76u, 12u, /* offset 2934 */
        0x03u, 0xE8u, 0x07u, 0xD0u, 0x0Bu, 0xB8u, 0x0Fu, 0xA0u, 0x13u, 0x88u, 0x17u, 0x70u,
    0x0Bu, 0x66u, 16u, /* offset 2918 */
        0x01u, 0x0Eu, 0x01u, 0x0Eu, 0x01u, 0x16u, 0x01u, 0x4Au, 0x01u, 0x68u, 0x01u, 0x8Eu,
        0x01u, 0x9Du, 0x01u, 0x9Du,
    0x0Bu, 0x56u, 16u, /* offset 2902 */
        0x00u, 0x78u, 0x00u, 0xC3u, 0x00u, 0xA5u, 0x00u, 0xACu, 0x00u, 0xC3u, 0x00u, 0xCAu,
        0x00u, 0xB4u, 0x00u, 0xB4u,
    0x0Bu, 0x46u, 16u, /* offset 2886 */
        0x03u, 0x20u, 0x06u, 0x40u, 0x09u, 0x60u, 0x0Cu, 0x80u, 0x0Fu, 0xA0u, 0x12u, 0xC0u,
        0x15u, 0xE0u, 0x19u, 0x00u,
    0x0Bu, 0x3Eu, 8u, /* offset 2878 */
        0x01u, 0x01u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u,
    0x0Bu, 0x3Au, 4u, /* offset 2874 */
        0x02u, 0x02u, 0x02u, 0x02u,
    0x0Bu, 0x39u, 1u, /* offset 2873 */
        0x07u,
    0x06u, 0x5Au, 64u, /* offset 1626 */
        0x01u, 0xF4u, 0x03u, 0xB6u, 0x05u, 0x78u, 0x07u, 0x3Au, 0x08u, 0xFCu, 0x0Au, 0xBEu,
        0x0Cu, 0x80u, 0x0Eu, 0x42u, 0x10u, 0x04u, 0x11u, 0xC6u, 0x13u, 0x88u, 0x15u, 0x4Au,
        0x17u, 0x0Cu, 0x18u, 0xCEu, 0x1Au, 0x90u, 0x1Cu, 0x52u, 0x00u, 0x00u, 0x00u, 0x32u,
        0x00u, 0x64u, 0x00u, 0x96u, 0x00u, 0xC8u, 0x00u, 0xFAu, 0x01u, 0x2Cu, 0x01u, 0x90u,
        0x01u, 0xF4u, 0x02u, 0x58u, 0x02u, 0xBCu, 0x03u, 0x20u, 0x03u, 0x52u, 0x03u, 0x84u,
        0x03u, 0xB6u, 0x03u, 0xE8u,
    0x05u, 0x5Au, 255u, /* offset 1370 */
        0x08u, 0x08u, 0x08u, 0x08u, 0x08u, 0x08u, 0x08u, 0x08u, 0x08u, 0x08u, 0x08u, 0x08u,
        0x08u, 0x08u, 0x08u, 0x08u, 0x0Cu, 0x0Cu, 0x0Cu, 0x0Cu, 0x0Cu, 0x0Cu, 0x0Cu, 0x0Cu,
        0x0Cu, 0x0Cu, 0x0Cu, 0x0Cu, 0x0Cu, 0x0Cu, 0x0Cu, 0x0Cu, 0x10u, 0x10u, 0x10u, 0x10u,
        0x10u, 0x10u, 0x10u, 0x10u, 0x10u, 0x10u, 0x10u, 0x10u, 0x10u, 0x10u, 0x10u, 0x10u,
        0x15u, 0x15u, 0x15u, 0x15u, 0x15u, 0x15u, 0x15u, 0x15u, 0x15u, 0x15u, 0x15u, 0x15u,
        0x15u, 0x15u, 0x15u, 0x15u, 0x1Bu, 0x1Bu, 0x1Bu, 0x1Bu, 0x1Bu, 0x1Bu, 0x1Bu, 0x1Bu,
        0x1Bu, 0x1Bu, 0x1Bu, 0x1Bu, 0x1Bu, 0x1Bu, 0x1Bu, 0x1Bu, 0x21u, 0x21u, 0x21u, 0x21u,
        0x21u, 0x21u, 0x21u, 0x21u, 0x21u, 0x21u, 0x21u, 0x21u, 0x21u, 0x21u, 0x21u, 0x21u,
        0x28u, 0x28u, 0x28u, 0x28u, 0x28u, 0x28u, 0x28u, 0x28u, 0x28u, 0x28u, 0x28u, 0x28u,
        0x28u, 0x28u, 0x28u, 0x28u, 0x38u, 0x38u, 0x38u, 0x38u, 0x38u, 0x38u, 0x38u, 0x38u,
        0x38u, 0x38u, 0x38u, 0x38u, 0x38u, 0x38u, 0x38u, 0x38u, 0x4Au, 0x4Au, 0x4Au, 0x4Au,
        0x4Au, 0x4Au, 0x4Au, 0x4Au, 0x4Au, 0x4Au, 0x4Au, 0x4Au, 0x4Au, 0x4Au, 0x4Au, 0x4Au,
        0x5Eu, 0x5Eu, 0x5Eu, 0x5Eu, 0x5Eu, 0x5Eu, 0x5Eu, 0x5Eu, 0x5Eu, 0x5Eu, 0x5Eu, 0x5Eu,
        0x5Eu, 0x5Eu, 0x5Eu, 0x5Eu, 0x74u, 0x74u, 0x74u, 0x74u, 0x74u, 0x74u, 0x74u, 0x74u,
        0x74u, 0x74u, 0x74u, 0x74u, 0x74u, 0x74u, 0x74u, 0x74u, 0x8Cu, 0x8Cu, 0x8Cu, 0x8Cu,
        0x8Cu, 0x8Cu, 0x8Cu, 0x8Cu, 0x8Cu, 0x8Cu, 0x8Cu, 0x8Cu, 0x8Cu, 0x8Cu, 0x8Cu, 0x8Cu,
        0x99u, 0x99u, 0x99u, 0x99u, 0x99u, 0x99u, 0x99u, 0x99u, 0x99u, 0x99u, 0x99u, 0x99u,
        0x99u, 0x99u, 0x99u, 0x99u, 0xA7u, 0xA7u, 0xA7u, 0xA7u, 0xA7u, 0xA7u, 0xA7u, 0xA7u,
        0xA7u, 0xA7u, 0xA7u, 0xA7u, 0xA7u, 0xA7u, 0xA7u, 0xA7u, 0xB7u, 0xB7u, 0xB7u, 0xB7u,
        0xB7u, 0xB7u, 0xB7u, 0xB7u, 0xB7u, 0xB7u, 0xB7u, 0xB7u, 0xB7u, 0xB7u, 0xB7u, 0xB7u,
        0xC8u, 0xC8u, 0xC8u, 0xC8u, 0xC8u, 0xC8u, 0xC8u, 0xC8u, 0xC8u, 0xC8u, 0xC8u, 0xC8u,
        0xC8u, 0xC8u, 0xC8u,
    0x06u, 0x59u, 1u, /* offset 1625 */
        0xC8u,
    0x0Au, 0x86u, 5u, /* offset 2694 */
        0x01u, 0x01u, 0x04u, 0xECu, 0x02u,
    0x0Au, 0x90u, 1u, /* offset 2704 */
        0x0Au,
    0x0Au, 0x8Cu, 2u, /* offset 2700 */
        0x03u, 0x00u,
    0x0Au, 0x7Cu, 2u, /* offset 2684 */
        0x03u, 0x20u,
    0x0Au, 0xA6u, 2u, /* offset 2726 */
        0x00u, 0x8Cu,
    0x0Eu, 0xA2u, 4u, /* offset 3746 */
        0x07u, 0xD0u, 0x00u, 0x50u,
    0x0Au, 0x80u, 2u, /* offset 2688 */
        0x00u, 0x02u,
    0x05u, 0x28u, 2u, /* offset 1320 */
        0x00u, 0x01u,
};

const hc_preset_t hc_engine_presets[] = {
    { 0u, 0, 0u, 0u, 0u, 0u }, /* Custom / user defined - populates nothing by design */
    { 1u, runs_vag_18t_me75_awt, 51u, 0x03C2u, 0u, 117u }, /* VAG 1.8T AWT (ME7.5 image only) */
    { 2u, runs_bosch_me711, 20u, 0x02F9u, 0u, 56u }, /* Porsche V8 donor - incomplete, refused */
    { 4u, runs_bosch_me711_board, 16u, 0x02F9u, 1u, 49u }, /* Board defaults - routing only, no engine - BOARD DEFAULT */
    { 3u, runs_vag_18t_me711, 1679u, 0x02F9u, 0u, 2701u }, /* VAG 1.8T DBW (AWT) */
};

const unsigned char hc_engine_preset_count = 5u;


unsigned char HC_COLD hc_preset_board_default_id(void)
{
    unsigned char i;

    for (i = 0u; i < hc_engine_preset_count; i++) {
        if (hc_engine_presets[i].board_default
            && hc_engine_presets[i].target_id == hc_pin_target_id) {
            return hc_engine_presets[i].id;
        }
    }
    return 0u;
}

static const hc_preset_t *preset_for(unsigned char id)
{
    unsigned char i;

    for (i = 0u; i < hc_engine_preset_count; i++) {
        if (hc_engine_presets[i].id == id) {
            return &hc_engine_presets[i];
        }
    }
    return 0;
}

unsigned char HC_COLD hc_preset_apply_engine_active(unsigned char id)
{
    unsigned int k;
    const hc_preset_t *p = preset_for(id);

    if (p == 0) {
        return 1u;
    }
    if (p->target_id != 0u && p->target_id != hc_pin_target_id) {
        return 2u;
    }
    for (k = 0u; k < p->n_bytes; ) {
        unsigned int off = ((unsigned int)p->runs[k] << 8) | p->runs[k + 1u];
        unsigned char n = p->runs[k + 2u];
        k += 3u;
        while (n--) {
            hc_cal_set_u8(off++, p->runs[k++]);
        }
    }
    hc_cal_set_u8(CFG_U_ENGINE_PRESET, id);
    return 0u;
}

unsigned char HC_COLD hc_preset_apply_engine(unsigned char id, unsigned int rpm)
{
    unsigned int k;
    const hc_preset_t *p = preset_for(id);

    if (p == 0) {
        return HC_PRESET_NO_SUCH;
    }
    if (p->target_id != 0u && p->target_id != hc_pin_target_id) {
        /* The preset names physical connector pins, and a connector pin means
           nothing until you say which ECU it is on. Applying an ME7.5 preset
           to a Bosch board would route injectors by number onto whatever
           those numbers happen to be over there. */
        return HC_PRESET_WRONG_BOARD;
    }
    if (rpm != 0u) {
        return HC_PRESET_NOT_STOPPED;
    }
    /* ONE TRANSACTION (V86). Every value is staged into DESIRED with its old
       byte logged; the WHOLE resulting page is validated; a refusal puts
       every staged byte back, so nothing - not DESIRED, not ACTIVE, not a
       LIVE calibration field - is left half-applied. Only a page that
       validates goes through the ordinary per-field apply policy. Never a
       Burn: that stays the tuner's own action. */
    hc_cfg_mgr_txn_begin();
    for (k = 0u; k < p->n_bytes; ) {
        unsigned int off = ((unsigned int)p->runs[k] << 8) | p->runs[k + 1u];
        unsigned char n = p->runs[k + 2u];
        k += 3u;
        while (n--) {
            hc_cfg_mgr_txn_put_u8(off++, p->runs[k++]);
        }
    }
    /* The preset id is itself a configuration field, so a page tells you what
       it was seeded from. Nothing reads it back except the user interface. */
    hc_cfg_mgr_txn_put_u8(CFG_U_ENGINE_PRESET, id);
    if (hc_cfg_mgr_txn_commit(rpm) != HC_VAL_OK) {
        return HC_PRESET_PAGE_INVALID;
    }
    return HC_PRESET_APPLIED;
}

