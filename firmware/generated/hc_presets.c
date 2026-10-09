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
static const hc_preset_item_t HC_PRESET_MEM items_vag_18t_me75_awt[] = {
    {    2u,     4u, 1u }, /* cylinders */
    {    3u,     4u, 1u }, /* strokes */
    {    4u,     0u, 2u }, /* tdcCylDegX10[0] */
    {    6u,  5400u, 2u }, /* tdcCylDegX10[1] */
    {    8u,  1800u, 2u }, /* tdcCylDegX10[2] */
    {   10u,  3600u, 2u }, /* tdcCylDegX10[3] */
    { 2516u,     1u, 1u }, /* cylBank[0] */
    { 2517u,     1u, 1u }, /* cylBank[1] */
    { 2518u,     1u, 1u }, /* cylBank[2] */
    { 2519u,     1u, 1u }, /* cylBank[3] */
    {   20u,    60u, 2u }, /* syTeeth */
    {   22u,     2u, 1u }, /* syGap */
    {   23u,     0u, 1u }, /* trigEdge */
    {   24u,    25u, 2u }, /* trigGapRatioX10 */
    {   26u,     6u, 1u }, /* trigMinTeeth */
    {   27u,   200u, 1u }, /* trigTimeoutMs */
    { 2539u,     1u, 1u }, /* trigDecoder */
    {   32u,     1u, 1u }, /* camEnable */
    {   28u,  7500u, 2u }, /* revMax */
    {   30u,    80u, 2u }, /* revMin */
    {   34u,     0u, 1u }, /* injChannel[0] */
    {   35u,     3u, 1u }, /* injChannel[1] */
    {   36u,     1u, 1u }, /* injChannel[2] */
    {   37u,     2u, 1u }, /* injChannel[3] */
    {   42u,     0u, 1u }, /* ignChannel[0] */
    {   43u,     3u, 1u }, /* ignChannel[1] */
    {   44u,     1u, 1u }, /* ignChannel[2] */
    {   45u,     2u, 1u }, /* ignChannel[3] */
    { 2551u,    96u, 1u }, /* injPin[0] */
    { 2552u,    89u, 1u }, /* injPin[1] */
    { 2553u,    97u, 1u }, /* injPin[2] */
    { 2554u,    88u, 1u }, /* injPin[3] */
    { 2563u,   102u, 1u }, /* ignPin[0] */
    { 2564u,    95u, 1u }, /* ignPin[1] */
    { 2565u,   103u, 1u }, /* ignPin[2] */
    { 2566u,    94u, 1u }, /* ignPin[3] */
    { 2548u,    82u, 1u }, /* pinCrank */
    { 2549u,    86u, 1u }, /* pinCam1 */
    { 2575u,   101u, 1u }, /* pinMap */
    { 2577u,    93u, 1u }, /* pinClt */
    { 2579u,    92u, 1u }, /* pinTps1 */
    { 2580u,    84u, 1u }, /* pinTps2 */
    { 2581u,    35u, 1u }, /* pinApp1 */
    { 2582u,    34u, 1u }, /* pinApp2 */
    { 2583u,    26u, 1u }, /* pinVbat */
    { 2591u,    65u, 1u }, /* pinFuelPump */
    { 2593u,   104u, 1u }, /* pinBoost */
    { 2587u,    29u, 1u }, /* pinMaf */
    { 2620u,     0u, 1u }, /* tpsCorrelation */
    { 2621u,     0u, 1u }, /* appCorrelation */
    { 2636u,  1470u, 2u }, /* stoichAfrX100 */
};

/* Porsche V8 donor - incomplete, refused */
static const hc_preset_item_t HC_PRESET_MEM items_bosch_me711[] = {
    {    2u,     8u, 1u }, /* cylinders */
    {    3u,     4u, 1u }, /* strokes */
    {   20u,    60u, 2u }, /* syTeeth */
    {   22u,     2u, 1u }, /* syGap */
    {   23u,     0u, 1u }, /* trigEdge */
    {   24u,    20u, 2u }, /* trigGapRatioX10 */
    { 2539u,     3u, 1u }, /* trigDecoder */
    {   32u,     1u, 1u }, /* camEnable */
    { 2538u,     1u, 1u }, /* syncMode */
    { 2548u,    82u, 1u }, /* pinCrank */
    { 2549u,    86u, 1u }, /* pinCam1 */
    { 2550u,    87u, 1u }, /* pinCam2 */
    { 2579u,    92u, 1u }, /* pinTps1 */
    { 2580u,    84u, 1u }, /* pinTps2 */
    { 2581u,    35u, 1u }, /* pinApp1 */
    { 2582u,    34u, 1u }, /* pinApp2 */
    { 2636u,  1470u, 2u }, /* stoichAfrX100 */
    { 2630u,     0u, 1u }, /* lambda1Source */
    { 2633u,     0u, 1u }, /* lambda2Source */
    { 2681u,     0u, 1u }, /* lambdaHeatPolicy */
};

/* Board defaults - routing only, no engine */
static const hc_preset_item_t HC_PRESET_MEM items_bosch_me711_board[] = {
    { 2548u,    82u, 1u }, /* pinCrank */
    { 2549u,    86u, 1u }, /* pinCam1 */
    { 2550u,    87u, 1u }, /* pinCam2 */
    { 2538u,     1u, 1u }, /* syncMode */
    { 2579u,    92u, 1u }, /* pinTps1 */
    { 2580u,    84u, 1u }, /* pinTps2 */
    { 2581u,    35u, 1u }, /* pinApp1 */
    { 2582u,    34u, 1u }, /* pinApp2 */
    { 2591u,    65u, 1u }, /* pinFuelPump */
    { 2678u,     4u, 1u }, /* s5500WindowBase */
    { 2865u,    47u, 1u }, /* pinMil */
    { 2864u,     0u, 1u }, /* celEnable */
    { 2866u,     1u, 1u }, /* celTestEnable */
    { 2868u,  3000u, 2u }, /* celTestOnMs */
    { 2870u,  1000u, 2u }, /* celTestGapMs */
    { 2980u,   250u, 2u }, /* vvtFreqHz */
};

/* VAG 1.8T DBW (AWT) */
static const hc_preset_item_t HC_PRESET_MEM items_vag_18t_me711[] = {
    {    2u,     4u, 1u }, /* cylinders */
    {    3u,     4u, 1u }, /* strokes */
    {    4u,     0u, 2u }, /* tdcCylDegX10[0] */
    {    6u,  5400u, 2u }, /* tdcCylDegX10[1] */
    {    8u,  1800u, 2u }, /* tdcCylDegX10[2] */
    {   10u,  3600u, 2u }, /* tdcCylDegX10[3] */
    { 3306u,     1u, 1u }, /* firingOrder */
    { 2516u,     1u, 1u }, /* cylBank[0] */
    { 2517u,     1u, 1u }, /* cylBank[1] */
    { 2518u,     1u, 1u }, /* cylBank[2] */
    { 2519u,     1u, 1u }, /* cylBank[3] */
    {   20u,    60u, 2u }, /* syTeeth */
    {   22u,     2u, 1u }, /* syGap */
    {   23u,     0u, 1u }, /* trigEdge */
    {   24u,    25u, 2u }, /* trigGapRatioX10 */
    {   26u,     6u, 1u }, /* trigMinTeeth */
    {   27u,   200u, 1u }, /* trigTimeoutMs */
    { 2539u,     1u, 1u }, /* trigDecoder */
    {   32u,     1u, 1u }, /* camEnable */
    { 2538u,     2u, 1u }, /* syncMode */
    {   28u,  7500u, 2u }, /* revMax */
    {   30u,    80u, 2u }, /* revMin */
    { 2551u,    96u, 1u }, /* injPin[0] */
    { 2552u,    89u, 1u }, /* injPin[1] */
    { 2553u,    97u, 1u }, /* injPin[2] */
    { 2554u,    88u, 1u }, /* injPin[3] */
    { 2555u,   255u, 1u }, /* injPin[4] */
    { 2556u,   255u, 1u }, /* injPin[5] */
    { 2557u,   255u, 1u }, /* injPin[6] */
    { 2558u,   255u, 1u }, /* injPin[7] */
    { 2559u,   255u, 1u }, /* injPin[8] */
    { 2560u,   255u, 1u }, /* injPin[9] */
    { 2561u,   255u, 1u }, /* injPin[10] */
    { 2562u,   255u, 1u }, /* injPin[11] */
    { 2563u,   102u, 1u }, /* ignPin[0] */
    { 2564u,    95u, 1u }, /* ignPin[1] */
    { 2565u,   103u, 1u }, /* ignPin[2] */
    { 2566u,    94u, 1u }, /* ignPin[3] */
    { 2567u,   255u, 1u }, /* ignPin[4] */
    { 2568u,   255u, 1u }, /* ignPin[5] */
    { 2569u,   255u, 1u }, /* ignPin[6] */
    { 2570u,   255u, 1u }, /* ignPin[7] */
    { 2571u,   255u, 1u }, /* ignPin[8] */
    { 2572u,   255u, 1u }, /* ignPin[9] */
    { 2573u,   255u, 1u }, /* ignPin[10] */
    { 2574u,   255u, 1u }, /* ignPin[11] */
    {   34u,     0u, 1u }, /* injChannel[0] */
    {   35u,     3u, 1u }, /* injChannel[1] */
    {   36u,     1u, 1u }, /* injChannel[2] */
    {   37u,     2u, 1u }, /* injChannel[3] */
    {   42u,     0u, 1u }, /* ignChannel[0] */
    {   43u,     3u, 1u }, /* ignChannel[1] */
    {   44u,     1u, 1u }, /* ignChannel[2] */
    {   45u,     2u, 1u }, /* ignChannel[3] */
    { 2548u,    82u, 1u }, /* pinCrank */
    { 2549u,    86u, 1u }, /* pinCam1 */
    { 2550u,   255u, 1u }, /* pinCam2 */
    { 2579u,    92u, 1u }, /* pinTps1 */
    { 2580u,    84u, 1u }, /* pinTps2 */
    { 2581u,    35u, 1u }, /* pinApp1 */
    { 2582u,    34u, 1u }, /* pinApp2 */
    { 2575u,   101u, 1u }, /* pinMap */
    { 2577u,    93u, 1u }, /* pinClt */
    { 2578u,    26u, 1u }, /* pinIat */
    { 2536u,     2u, 1u }, /* injStrategy */
    { 2537u,     2u, 1u }, /* ignStrategy */
    { 2730u,     1u, 1u }, /* injTimingMode */
    {   58u,  4400u, 2u }, /* injStartDegX10 */
    { 2630u,     1u, 1u }, /* lambda1Source */
    { 2681u,     1u, 1u }, /* lambdaHeatPolicy */
    { 2631u,     1u, 1u }, /* lambda1Bank */
    { 2626u,    15u, 2u }, /* lambda1CylMask */
    { 2633u,     0u, 1u }, /* lambda2Source */
    { 2591u,    65u, 1u }, /* pinFuelPump */
    { 1152u,   182u, 2u }, /* cltSensAx[0] */
    { 1154u,   238u, 2u }, /* cltSensAx[1] */
    { 1156u,   284u, 2u }, /* cltSensAx[2] */
    { 1158u,   337u, 2u }, /* cltSensAx[3] */
    { 1160u,   428u, 2u }, /* cltSensAx[4] */
    { 1162u,   533u, 2u }, /* cltSensAx[5] */
    { 1164u,   680u, 2u }, /* cltSensAx[6] */
    { 1166u,   751u, 2u }, /* cltSensAx[7] */
    { 1168u,   783u, 2u }, /* cltSensAx[8] */
    { 1170u,   812u, 2u }, /* cltSensAx[9] */
    { 1172u,   866u, 2u }, /* cltSensAx[10] */
    { 1174u,   908u, 2u }, /* cltSensAx[11] */
    { 1176u,   942u, 2u }, /* cltSensAx[12] */
    { 1178u,   967u, 2u }, /* cltSensAx[13] */
    { 1180u,   996u, 2u }, /* cltSensAx[14] */
    { 1182u,  1008u, 2u }, /* cltSensAx[15] */
    { 1184u, 11432u, 2u }, /* cltSensVal[0] */
    { 1186u, 11300u, 2u }, /* cltSensVal[1] */
    { 1188u, 11200u, 2u }, /* cltSensVal[2] */
    { 1190u, 11100u, 2u }, /* cltSensVal[3] */
    { 1192u, 10950u, 2u }, /* cltSensVal[4] */
    { 1194u, 10800u, 2u }, /* cltSensVal[5] */
    { 1196u, 10600u, 2u }, /* cltSensVal[6] */
    { 1198u, 10500u, 2u }, /* cltSensVal[7] */
    { 1200u, 10450u, 2u }, /* cltSensVal[8] */
    { 1202u, 10400u, 2u }, /* cltSensVal[9] */
    { 1204u, 10300u, 2u }, /* cltSensVal[10] */
    { 1206u, 10200u, 2u }, /* cltSensVal[11] */
    { 1208u, 10100u, 2u }, /* cltSensVal[12] */
    { 1210u, 10000u, 2u }, /* cltSensVal[13] */
    { 1212u,  9800u, 2u }, /* cltSensVal[14] */
    { 1214u,  9600u, 2u }, /* cltSensVal[15] */
    { 1254u,    28u, 2u }, /* iatSensAx[0] */
    { 1256u,    48u, 2u }, /* iatSensAx[1] */
    { 1258u,    64u, 2u }, /* iatSensAx[2] */
    { 1260u,    92u, 2u }, /* iatSensAx[3] */
    { 1262u,   116u, 2u }, /* iatSensAx[4] */
    { 1264u,   148u, 2u }, /* iatSensAx[5] */
    { 1266u,   192u, 2u }, /* iatSensAx[6] */
    { 1268u,   244u, 2u }, /* iatSensAx[7] */
    { 1270u,   308u, 2u }, /* iatSensAx[8] */
    { 1272u,   372u, 2u }, /* iatSensAx[9] */
    { 1274u,   432u, 2u }, /* iatSensAx[10] */
    { 1276u,   572u, 2u }, /* iatSensAx[11] */
    { 1278u,   664u, 2u }, /* iatSensAx[12] */
    { 1280u,   744u, 2u }, /* iatSensAx[13] */
    { 1282u,   864u, 2u }, /* iatSensAx[14] */
    { 1284u,   900u, 2u }, /* iatSensAx[15] */
    { 1286u, 11403u, 2u }, /* iatSensVal[0] */
    { 1288u, 11200u, 2u }, /* iatSensVal[1] */
    { 1290u, 11050u, 2u }, /* iatSensVal[2] */
    { 1292u, 10900u, 2u }, /* iatSensVal[3] */
    { 1294u, 10803u, 2u }, /* iatSensVal[4] */
    { 1296u, 10698u, 2u }, /* iatSensVal[5] */
    { 1298u, 10600u, 2u }, /* iatSensVal[6] */
    { 1300u, 10503u, 2u }, /* iatSensVal[7] */
    { 1302u, 10398u, 2u }, /* iatSensVal[8] */
    { 1304u, 10323u, 2u }, /* iatSensVal[9] */
    { 1306u, 10248u, 2u }, /* iatSensVal[10] */
    { 1308u, 10098u, 2u }, /* iatSensVal[11] */
    { 1310u, 10000u, 2u }, /* iatSensVal[12] */
    { 1312u,  9902u, 2u }, /* iatSensVal[13] */
    { 1314u,  9700u, 2u }, /* iatSensVal[14] */
    { 1316u,  9602u, 2u }, /* iatSensVal[15] */
    { 2593u,   104u, 1u }, /* pinBoost */
    { 2590u,    23u, 1u }, /* pinMainRelay */
    {   73u,     2u, 1u }, /* mainRelayModeCfg */
    { 2510u,  1781u, 2u }, /* displacementCc */
    { 2640u,   300u, 2u }, /* injRefPressureKpa */
    { 2642u,     0u, 2u }, /* crankingDwellMsX100 */
    { 1236u,     1u, 1u }, /* loadSource */
    {  640u,   500u, 2u }, /* fuelRpmAx[0] */
    {  642u,   950u, 2u }, /* fuelRpmAx[1] */
    {  644u,  1400u, 2u }, /* fuelRpmAx[2] */
    {  646u,  1850u, 2u }, /* fuelRpmAx[3] */
    {  648u,  2300u, 2u }, /* fuelRpmAx[4] */
    {  650u,  2750u, 2u }, /* fuelRpmAx[5] */
    {  652u,  3200u, 2u }, /* fuelRpmAx[6] */
    {  654u,  3650u, 2u }, /* fuelRpmAx[7] */
    {  656u,  4100u, 2u }, /* fuelRpmAx[8] */
    {  658u,  4550u, 2u }, /* fuelRpmAx[9] */
    {  660u,  5000u, 2u }, /* fuelRpmAx[10] */
    {  662u,  5450u, 2u }, /* fuelRpmAx[11] */
    {  664u,  5900u, 2u }, /* fuelRpmAx[12] */
    {  666u,  6350u, 2u }, /* fuelRpmAx[13] */
    {  668u,  6800u, 2u }, /* fuelRpmAx[14] */
    {  670u,  7250u, 2u }, /* fuelRpmAx[15] */
    {  672u,     0u, 2u }, /* fuelLoadAx[0] */
    {  674u,    10u, 2u }, /* fuelLoadAx[1] */
    {  676u,    20u, 2u }, /* fuelLoadAx[2] */
    {  678u,    30u, 2u }, /* fuelLoadAx[3] */
    {  680u,    40u, 2u }, /* fuelLoadAx[4] */
    {  682u,    55u, 2u }, /* fuelLoadAx[5] */
    {  684u,    70u, 2u }, /* fuelLoadAx[6] */
    {  686u,   100u, 2u }, /* fuelLoadAx[7] */
    {  688u,   130u, 2u }, /* fuelLoadAx[8] */
    {  690u,   160u, 2u }, /* fuelLoadAx[9] */
    {  692u,   200u, 2u }, /* fuelLoadAx[10] */
    {  694u,   250u, 2u }, /* fuelLoadAx[11] */
    {  696u,   300u, 2u }, /* fuelLoadAx[12] */
    {  698u,   400u, 2u }, /* fuelLoadAx[13] */
    {  700u,   500u, 2u }, /* fuelLoadAx[14] */
    {  702u,  1000u, 2u }, /* fuelLoadAx[15] */
    { 1240u,     0u, 1u }, /* dbwEnable */
    { 2636u,  1470u, 2u }, /* stoichAfrX100 */
    { 1242u,  5120u, 2u }, /* dbwKp */
    { 1244u, 47000u, 2u }, /* dbwKi */
    { 1322u, 17600u, 2u }, /* dbwKd */
    { 1332u,     0u, 2u }, /* dbwBiasAx[0] */
    { 1334u,    10u, 2u }, /* dbwBiasAx[1] */
    { 1336u,    50u, 2u }, /* dbwBiasAx[2] */
    { 1338u,    70u, 2u }, /* dbwBiasAx[3] */
    { 1340u,   140u, 2u }, /* dbwBiasAx[4] */
    { 1342u,   650u, 2u }, /* dbwBiasAx[5] */
    { 1344u,   660u, 2u }, /* dbwBiasAx[6] */
    { 1346u,  1000u, 2u }, /* dbwBiasAx[7] */
    { 1348u,   850u, 2u }, /* dbwBiasVal[0] */
    { 1350u,   850u, 2u }, /* dbwBiasVal[1] */
    { 1352u,   900u, 2u }, /* dbwBiasVal[2] */
    { 1354u,  1000u, 2u }, /* dbwBiasVal[3] */
    { 1356u,  1190u, 2u }, /* dbwBiasVal[4] */
    { 1358u,  1200u, 2u }, /* dbwBiasVal[5] */
    { 1360u,  1260u, 2u }, /* dbwBiasVal[6] */
    { 1362u,  1280u, 2u }, /* dbwBiasVal[7] */
    { 2620u,     1u, 1u }, /* tpsCorrelation */
    { 2621u,     1u, 1u }, /* appCorrelation */
    {   72u,     1u, 1u }, /* trigSource */
    { 2680u,     1u, 1u }, /* fuelPumpMode */
    { 2540u, 64756u, 2u }, /* trigAngleX10 = -780 */
    { 1228u,   150u, 2u }, /* pedal1Min */
    { 1230u,   849u, 2u }, /* pedal1Max */
    { 1232u,    75u, 2u }, /* pedal2Min */
    { 1234u,   424u, 2u }, /* pedal2Max */
    { 1220u,   102u, 2u }, /* tps1Min */
    { 1222u,   954u, 2u }, /* tps1Max */
    { 1224u,   919u, 2u }, /* tps2Min */
    { 1226u,    71u, 2u }, /* tps2Max */
    {  704u,   500u, 2u }, /* ignRpmAx[0] */
    {  706u,   950u, 2u }, /* ignRpmAx[1] */
    {  708u,  1400u, 2u }, /* ignRpmAx[2] */
    {  710u,  1850u, 2u }, /* ignRpmAx[3] */
    {  712u,  2300u, 2u }, /* ignRpmAx[4] */
    {  714u,  2750u, 2u }, /* ignRpmAx[5] */
    {  716u,  3200u, 2u }, /* ignRpmAx[6] */
    {  718u,  3650u, 2u }, /* ignRpmAx[7] */
    {  720u,  4100u, 2u }, /* ignRpmAx[8] */
    {  722u,  4550u, 2u }, /* ignRpmAx[9] */
    {  724u,  5000u, 2u }, /* ignRpmAx[10] */
    {  726u,  5450u, 2u }, /* ignRpmAx[11] */
    {  728u,  5900u, 2u }, /* ignRpmAx[12] */
    {  730u,  6350u, 2u }, /* ignRpmAx[13] */
    {  732u,  6800u, 2u }, /* ignRpmAx[14] */
    {  734u,  7250u, 2u }, /* ignRpmAx[15] */
    {  736u,     0u, 2u }, /* ignLoadAx[0] */
    {  738u,    10u, 2u }, /* ignLoadAx[1] */
    {  740u,    20u, 2u }, /* ignLoadAx[2] */
    {  742u,    30u, 2u }, /* ignLoadAx[3] */
    {  744u,    40u, 2u }, /* ignLoadAx[4] */
    {  746u,    55u, 2u }, /* ignLoadAx[5] */
    {  748u,    70u, 2u }, /* ignLoadAx[6] */
    {  750u,   100u, 2u }, /* ignLoadAx[7] */
    {  752u,   130u, 2u }, /* ignLoadAx[8] */
    {  754u,   160u, 2u }, /* ignLoadAx[9] */
    {  756u,   200u, 2u }, /* ignLoadAx[10] */
    {  758u,   250u, 2u }, /* ignLoadAx[11] */
    {  760u,   300u, 2u }, /* ignLoadAx[12] */
    {  762u,   400u, 2u }, /* ignLoadAx[13] */
    {  764u,   500u, 2u }, /* ignLoadAx[14] */
    {  766u,  1000u, 2u }, /* ignLoadAx[15] */
    { 3310u,   500u, 2u }, /* lambdaRpmAx[0] */
    { 3312u,   950u, 2u }, /* lambdaRpmAx[1] */
    { 3314u,  1400u, 2u }, /* lambdaRpmAx[2] */
    { 3316u,  1850u, 2u }, /* lambdaRpmAx[3] */
    { 3318u,  2300u, 2u }, /* lambdaRpmAx[4] */
    { 3320u,  2750u, 2u }, /* lambdaRpmAx[5] */
    { 3322u,  3200u, 2u }, /* lambdaRpmAx[6] */
    { 3324u,  3650u, 2u }, /* lambdaRpmAx[7] */
    { 3326u,  4100u, 2u }, /* lambdaRpmAx[8] */
    { 3328u,  4550u, 2u }, /* lambdaRpmAx[9] */
    { 3330u,  5000u, 2u }, /* lambdaRpmAx[10] */
    { 3332u,  5450u, 2u }, /* lambdaRpmAx[11] */
    { 3334u,  5900u, 2u }, /* lambdaRpmAx[12] */
    { 3336u,  6350u, 2u }, /* lambdaRpmAx[13] */
    { 3338u,  6800u, 2u }, /* lambdaRpmAx[14] */
    { 3340u,  7250u, 2u }, /* lambdaRpmAx[15] */
    { 3342u,     0u, 2u }, /* lambdaLoadAx[0] */
    { 3344u,    10u, 2u }, /* lambdaLoadAx[1] */
    { 3346u,    20u, 2u }, /* lambdaLoadAx[2] */
    { 3348u,    30u, 2u }, /* lambdaLoadAx[3] */
    { 3350u,    40u, 2u }, /* lambdaLoadAx[4] */
    { 3352u,    55u, 2u }, /* lambdaLoadAx[5] */
    { 3354u,    70u, 2u }, /* lambdaLoadAx[6] */
    { 3356u,   100u, 2u }, /* lambdaLoadAx[7] */
    { 3358u,   130u, 2u }, /* lambdaLoadAx[8] */
    { 3360u,   160u, 2u }, /* lambdaLoadAx[9] */
    { 3362u,   200u, 2u }, /* lambdaLoadAx[10] */
    { 3364u,   250u, 2u }, /* lambdaLoadAx[11] */
    { 3366u,   300u, 2u }, /* lambdaLoadAx[12] */
    { 3368u,   400u, 2u }, /* lambdaLoadAx[13] */
    { 3370u,   500u, 2u }, /* lambdaLoadAx[14] */
    { 3372u,  1000u, 2u }, /* lambdaLoadAx[15] */
    { 3406u,   100u, 1u }, /* mapEstimate[0] */
    { 3407u,   100u, 1u }, /* mapEstimate[1] */
    { 3408u,   100u, 1u }, /* mapEstimate[2] */
    { 3409u,   100u, 1u }, /* mapEstimate[3] */
    { 3410u,   100u, 1u }, /* mapEstimate[4] */
    { 3411u,   100u, 1u }, /* mapEstimate[5] */
    { 3412u,   100u, 1u }, /* mapEstimate[6] */
    { 3413u,   100u, 1u }, /* mapEstimate[7] */
    { 3414u,   100u, 1u }, /* mapEstimate[8] */
    { 3415u,   100u, 1u }, /* mapEstimate[9] */
    { 3416u,   100u, 1u }, /* mapEstimate[10] */
    { 3417u,   100u, 1u }, /* mapEstimate[11] */
    { 3418u,   100u, 1u }, /* mapEstimate[12] */
    { 3419u,   100u, 1u }, /* mapEstimate[13] */
    { 3420u,   100u, 1u }, /* mapEstimate[14] */
    { 3421u,   100u, 1u }, /* mapEstimate[15] */
    { 3422u,   100u, 1u }, /* mapEstimate[16] */
    { 3423u,   100u, 1u }, /* mapEstimate[17] */
    { 3424u,   100u, 1u }, /* mapEstimate[18] */
    { 3425u,   100u, 1u }, /* mapEstimate[19] */
    { 3426u,   100u, 1u }, /* mapEstimate[20] */
    { 3427u,   100u, 1u }, /* mapEstimate[21] */
    { 3428u,   100u, 1u }, /* mapEstimate[22] */
    { 3429u,   100u, 1u }, /* mapEstimate[23] */
    { 3430u,   100u, 1u }, /* mapEstimate[24] */
    { 3431u,   100u, 1u }, /* mapEstimate[25] */
    { 3432u,   100u, 1u }, /* mapEstimate[26] */
    { 3433u,   100u, 1u }, /* mapEstimate[27] */
    { 3434u,   100u, 1u }, /* mapEstimate[28] */
    { 3435u,   100u, 1u }, /* mapEstimate[29] */
    { 3436u,   100u, 1u }, /* mapEstimate[30] */
    { 3437u,   100u, 1u }, /* mapEstimate[31] */
    { 3438u,   100u, 1u }, /* mapEstimate[32] */
    { 3439u,   100u, 1u }, /* mapEstimate[33] */
    { 3440u,   100u, 1u }, /* mapEstimate[34] */
    { 3441u,   100u, 1u }, /* mapEstimate[35] */
    { 3442u,   100u, 1u }, /* mapEstimate[36] */
    { 3443u,   100u, 1u }, /* mapEstimate[37] */
    { 3444u,   100u, 1u }, /* mapEstimate[38] */
    { 3445u,   100u, 1u }, /* mapEstimate[39] */
    { 3446u,   100u, 1u }, /* mapEstimate[40] */
    { 3447u,   100u, 1u }, /* mapEstimate[41] */
    { 3448u,   100u, 1u }, /* mapEstimate[42] */
    { 3449u,   100u, 1u }, /* mapEstimate[43] */
    { 3450u,   100u, 1u }, /* mapEstimate[44] */
    { 3451u,   100u, 1u }, /* mapEstimate[45] */
    { 3452u,   100u, 1u }, /* mapEstimate[46] */
    { 3453u,   100u, 1u }, /* mapEstimate[47] */
    { 3454u,   100u, 1u }, /* mapEstimate[48] */
    { 3455u,   100u, 1u }, /* mapEstimate[49] */
    { 3456u,   100u, 1u }, /* mapEstimate[50] */
    { 3457u,   100u, 1u }, /* mapEstimate[51] */
    { 3458u,   100u, 1u }, /* mapEstimate[52] */
    { 3459u,   100u, 1u }, /* mapEstimate[53] */
    { 3460u,   100u, 1u }, /* mapEstimate[54] */
    { 3461u,   100u, 1u }, /* mapEstimate[55] */
    { 3462u,   100u, 1u }, /* mapEstimate[56] */
    { 3463u,   100u, 1u }, /* mapEstimate[57] */
    { 3464u,   100u, 1u }, /* mapEstimate[58] */
    { 3465u,   100u, 1u }, /* mapEstimate[59] */
    { 3466u,   100u, 1u }, /* mapEstimate[60] */
    { 3467u,   100u, 1u }, /* mapEstimate[61] */
    { 3468u,   100u, 1u }, /* mapEstimate[62] */
    { 3469u,   100u, 1u }, /* mapEstimate[63] */
    { 3493u,     1u, 1u }, /* stftEnable */
    { 3506u,    10u, 1u }, /* stftMaxAdd[0] */
    { 3507u,     0u, 1u }, /* stftMaxAdd[1] */
    { 3508u,     5u, 1u }, /* stftMaxAdd[2] */
    { 3509u,    10u, 1u }, /* stftMaxAdd[3] */
    { 3510u,    10u, 1u }, /* stftMaxRemove[0] */
    { 3511u,     0u, 1u }, /* stftMaxRemove[1] */
    { 3512u,     0u, 1u }, /* stftMaxRemove[2] */
    { 3513u,    10u, 1u }, /* stftMaxRemove[3] */
    { 3500u,     2u, 1u }, /* stftOverrunLoad */
    { 3501u,    40u, 1u }, /* stftPowerLoad */
    { 2418u,  1500u, 2u }, /* overrunRpm */
    { 2422u,  1300u, 2u }, /* overrunResume */
    { 2420u,    20u, 2u }, /* overrunTpsX10 */
    { 2670u, 11150u, 2u }, /* cltMaxDegX10 */
    { 2426u,     1u, 1u }, /* idleEnable */
    {  768u,   147u, 1u }, /* afrMap[0] */
    {  769u,   147u, 1u }, /* afrMap[1] */
    {  770u,   147u, 1u }, /* afrMap[2] */
    {  771u,   147u, 1u }, /* afrMap[3] */
    {  772u,   147u, 1u }, /* afrMap[4] */
    {  773u,   147u, 1u }, /* afrMap[5] */
    {  774u,   147u, 1u }, /* afrMap[6] */
    {  775u,   147u, 1u }, /* afrMap[7] */
    {  776u,   147u, 1u }, /* afrMap[8] */
    {  777u,   147u, 1u }, /* afrMap[9] */
    {  778u,   147u, 1u }, /* afrMap[10] */
    {  779u,   147u, 1u }, /* afrMap[11] */
    {  780u,   147u, 1u }, /* afrMap[12] */
    {  781u,   147u, 1u }, /* afrMap[13] */
    {  782u,   147u, 1u }, /* afrMap[14] */
    {  783u,   147u, 1u }, /* afrMap[15] */
    {  784u,   147u, 1u }, /* afrMap[16] */
    {  785u,   147u, 1u }, /* afrMap[17] */
    {  786u,   147u, 1u }, /* afrMap[18] */
    {  787u,   147u, 1u }, /* afrMap[19] */
    {  788u,   147u, 1u }, /* afrMap[20] */
    {  789u,   147u, 1u }, /* afrMap[21] */
    {  790u,   147u, 1u }, /* afrMap[22] */
    {  791u,   147u, 1u }, /* afrMap[23] */
    {  792u,   147u, 1u }, /* afrMap[24] */
    {  793u,   147u, 1u }, /* afrMap[25] */
    {  794u,   147u, 1u }, /* afrMap[26] */
    {  795u,   147u, 1u }, /* afrMap[27] */
    {  796u,   147u, 1u }, /* afrMap[28] */
    {  797u,   147u, 1u }, /* afrMap[29] */
    {  798u,   147u, 1u }, /* afrMap[30] */
    {  799u,   147u, 1u }, /* afrMap[31] */
    {  800u,   147u, 1u }, /* afrMap[32] */
    {  801u,   147u, 1u }, /* afrMap[33] */
    {  802u,   147u, 1u }, /* afrMap[34] */
    {  803u,   147u, 1u }, /* afrMap[35] */
    {  804u,   147u, 1u }, /* afrMap[36] */
    {  805u,   147u, 1u }, /* afrMap[37] */
    {  806u,   147u, 1u }, /* afrMap[38] */
    {  807u,   147u, 1u }, /* afrMap[39] */
    {  808u,   147u, 1u }, /* afrMap[40] */
    {  809u,   147u, 1u }, /* afrMap[41] */
    {  810u,   147u, 1u }, /* afrMap[42] */
    {  811u,   147u, 1u }, /* afrMap[43] */
    {  812u,   147u, 1u }, /* afrMap[44] */
    {  813u,   147u, 1u }, /* afrMap[45] */
    {  814u,   147u, 1u }, /* afrMap[46] */
    {  815u,   147u, 1u }, /* afrMap[47] */
    {  816u,   147u, 1u }, /* afrMap[48] */
    {  817u,   147u, 1u }, /* afrMap[49] */
    {  818u,   147u, 1u }, /* afrMap[50] */
    {  819u,   147u, 1u }, /* afrMap[51] */
    {  820u,   147u, 1u }, /* afrMap[52] */
    {  821u,   147u, 1u }, /* afrMap[53] */
    {  822u,   147u, 1u }, /* afrMap[54] */
    {  823u,   147u, 1u }, /* afrMap[55] */
    {  824u,   147u, 1u }, /* afrMap[56] */
    {  825u,   147u, 1u }, /* afrMap[57] */
    {  826u,   147u, 1u }, /* afrMap[58] */
    {  827u,   147u, 1u }, /* afrMap[59] */
    {  828u,   147u, 1u }, /* afrMap[60] */
    {  829u,   147u, 1u }, /* afrMap[61] */
    {  830u,   147u, 1u }, /* afrMap[62] */
    {  831u,   147u, 1u }, /* afrMap[63] */
    {  832u,   147u, 1u }, /* afrMap[64] */
    {  833u,   147u, 1u }, /* afrMap[65] */
    {  834u,   147u, 1u }, /* afrMap[66] */
    {  835u,   147u, 1u }, /* afrMap[67] */
    {  836u,   147u, 1u }, /* afrMap[68] */
    {  837u,   147u, 1u }, /* afrMap[69] */
    {  838u,   147u, 1u }, /* afrMap[70] */
    {  839u,   147u, 1u }, /* afrMap[71] */
    {  840u,   147u, 1u }, /* afrMap[72] */
    {  841u,   147u, 1u }, /* afrMap[73] */
    {  842u,   147u, 1u }, /* afrMap[74] */
    {  843u,   147u, 1u }, /* afrMap[75] */
    {  844u,   147u, 1u }, /* afrMap[76] */
    {  845u,   147u, 1u }, /* afrMap[77] */
    {  846u,   147u, 1u }, /* afrMap[78] */
    {  847u,   147u, 1u }, /* afrMap[79] */
    {  848u,   147u, 1u }, /* afrMap[80] */
    {  849u,   147u, 1u }, /* afrMap[81] */
    {  850u,   147u, 1u }, /* afrMap[82] */
    {  851u,   147u, 1u }, /* afrMap[83] */
    {  852u,   147u, 1u }, /* afrMap[84] */
    {  853u,   147u, 1u }, /* afrMap[85] */
    {  854u,   147u, 1u }, /* afrMap[86] */
    {  855u,   147u, 1u }, /* afrMap[87] */
    {  856u,   147u, 1u }, /* afrMap[88] */
    {  857u,   147u, 1u }, /* afrMap[89] */
    {  858u,   147u, 1u }, /* afrMap[90] */
    {  859u,   147u, 1u }, /* afrMap[91] */
    {  860u,   147u, 1u }, /* afrMap[92] */
    {  861u,   147u, 1u }, /* afrMap[93] */
    {  862u,   147u, 1u }, /* afrMap[94] */
    {  863u,   147u, 1u }, /* afrMap[95] */
    {  864u,   147u, 1u }, /* afrMap[96] */
    {  865u,   147u, 1u }, /* afrMap[97] */
    {  866u,   147u, 1u }, /* afrMap[98] */
    {  867u,   147u, 1u }, /* afrMap[99] */
    {  868u,   147u, 1u }, /* afrMap[100] */
    {  869u,   147u, 1u }, /* afrMap[101] */
    {  870u,   147u, 1u }, /* afrMap[102] */
    {  871u,   147u, 1u }, /* afrMap[103] */
    {  872u,   147u, 1u }, /* afrMap[104] */
    {  873u,   147u, 1u }, /* afrMap[105] */
    {  874u,   147u, 1u }, /* afrMap[106] */
    {  875u,   147u, 1u }, /* afrMap[107] */
    {  876u,   147u, 1u }, /* afrMap[108] */
    {  877u,   147u, 1u }, /* afrMap[109] */
    {  878u,   147u, 1u }, /* afrMap[110] */
    {  879u,   147u, 1u }, /* afrMap[111] */
    {  880u,   147u, 1u }, /* afrMap[112] */
    {  881u,   147u, 1u }, /* afrMap[113] */
    {  882u,   147u, 1u }, /* afrMap[114] */
    {  883u,   147u, 1u }, /* afrMap[115] */
    {  884u,   147u, 1u }, /* afrMap[116] */
    {  885u,   147u, 1u }, /* afrMap[117] */
    {  886u,   147u, 1u }, /* afrMap[118] */
    {  887u,   147u, 1u }, /* afrMap[119] */
    {  888u,   147u, 1u }, /* afrMap[120] */
    {  889u,   147u, 1u }, /* afrMap[121] */
    {  890u,   147u, 1u }, /* afrMap[122] */
    {  891u,   147u, 1u }, /* afrMap[123] */
    {  892u,   147u, 1u }, /* afrMap[124] */
    {  893u,   147u, 1u }, /* afrMap[125] */
    {  894u,   147u, 1u }, /* afrMap[126] */
    {  895u,   147u, 1u }, /* afrMap[127] */
    {  896u,   147u, 1u }, /* afrMap[128] */
    {  897u,   147u, 1u }, /* afrMap[129] */
    {  898u,   147u, 1u }, /* afrMap[130] */
    {  899u,   147u, 1u }, /* afrMap[131] */
    {  900u,   147u, 1u }, /* afrMap[132] */
    {  901u,   147u, 1u }, /* afrMap[133] */
    {  902u,   147u, 1u }, /* afrMap[134] */
    {  903u,   147u, 1u }, /* afrMap[135] */
    {  904u,   147u, 1u }, /* afrMap[136] */
    {  905u,   147u, 1u }, /* afrMap[137] */
    {  906u,   147u, 1u }, /* afrMap[138] */
    {  907u,   147u, 1u }, /* afrMap[139] */
    {  908u,   147u, 1u }, /* afrMap[140] */
    {  909u,   147u, 1u }, /* afrMap[141] */
    {  910u,   147u, 1u }, /* afrMap[142] */
    {  911u,   147u, 1u }, /* afrMap[143] */
    {  912u,   147u, 1u }, /* afrMap[144] */
    {  913u,   147u, 1u }, /* afrMap[145] */
    {  914u,   147u, 1u }, /* afrMap[146] */
    {  915u,   147u, 1u }, /* afrMap[147] */
    {  916u,   147u, 1u }, /* afrMap[148] */
    {  917u,   147u, 1u }, /* afrMap[149] */
    {  918u,   147u, 1u }, /* afrMap[150] */
    {  919u,   147u, 1u }, /* afrMap[151] */
    {  920u,   147u, 1u }, /* afrMap[152] */
    {  921u,   147u, 1u }, /* afrMap[153] */
    {  922u,   147u, 1u }, /* afrMap[154] */
    {  923u,   147u, 1u }, /* afrMap[155] */
    {  924u,   147u, 1u }, /* afrMap[156] */
    {  925u,   147u, 1u }, /* afrMap[157] */
    {  926u,   147u, 1u }, /* afrMap[158] */
    {  927u,   147u, 1u }, /* afrMap[159] */
    {  928u,   147u, 1u }, /* afrMap[160] */
    {  929u,   147u, 1u }, /* afrMap[161] */
    {  930u,   147u, 1u }, /* afrMap[162] */
    {  931u,   147u, 1u }, /* afrMap[163] */
    {  932u,   147u, 1u }, /* afrMap[164] */
    {  933u,   147u, 1u }, /* afrMap[165] */
    {  934u,   147u, 1u }, /* afrMap[166] */
    {  935u,   147u, 1u }, /* afrMap[167] */
    {  936u,   147u, 1u }, /* afrMap[168] */
    {  937u,   147u, 1u }, /* afrMap[169] */
    {  938u,   147u, 1u }, /* afrMap[170] */
    {  939u,   147u, 1u }, /* afrMap[171] */
    {  940u,   147u, 1u }, /* afrMap[172] */
    {  941u,   147u, 1u }, /* afrMap[173] */
    {  942u,   147u, 1u }, /* afrMap[174] */
    {  943u,   147u, 1u }, /* afrMap[175] */
    {  944u,   147u, 1u }, /* afrMap[176] */
    {  945u,   147u, 1u }, /* afrMap[177] */
    {  946u,   147u, 1u }, /* afrMap[178] */
    {  947u,   147u, 1u }, /* afrMap[179] */
    {  948u,   147u, 1u }, /* afrMap[180] */
    {  949u,   147u, 1u }, /* afrMap[181] */
    {  950u,   147u, 1u }, /* afrMap[182] */
    {  951u,   147u, 1u }, /* afrMap[183] */
    {  952u,   147u, 1u }, /* afrMap[184] */
    {  953u,   147u, 1u }, /* afrMap[185] */
    {  954u,   147u, 1u }, /* afrMap[186] */
    {  955u,   147u, 1u }, /* afrMap[187] */
    {  956u,   147u, 1u }, /* afrMap[188] */
    {  957u,   147u, 1u }, /* afrMap[189] */
    {  958u,   147u, 1u }, /* afrMap[190] */
    {  959u,   147u, 1u }, /* afrMap[191] */
    {  960u,   147u, 1u }, /* afrMap[192] */
    {  961u,   147u, 1u }, /* afrMap[193] */
    {  962u,   147u, 1u }, /* afrMap[194] */
    {  963u,   147u, 1u }, /* afrMap[195] */
    {  964u,   147u, 1u }, /* afrMap[196] */
    {  965u,   147u, 1u }, /* afrMap[197] */
    {  966u,   147u, 1u }, /* afrMap[198] */
    {  967u,   147u, 1u }, /* afrMap[199] */
    {  968u,   147u, 1u }, /* afrMap[200] */
    {  969u,   147u, 1u }, /* afrMap[201] */
    {  970u,   147u, 1u }, /* afrMap[202] */
    {  971u,   147u, 1u }, /* afrMap[203] */
    {  972u,   147u, 1u }, /* afrMap[204] */
    {  973u,   147u, 1u }, /* afrMap[205] */
    {  974u,   147u, 1u }, /* afrMap[206] */
    {  975u,   147u, 1u }, /* afrMap[207] */
    {  976u,   140u, 1u }, /* afrMap[208] */
    {  977u,   140u, 1u }, /* afrMap[209] */
    {  978u,   140u, 1u }, /* afrMap[210] */
    {  979u,   140u, 1u }, /* afrMap[211] */
    {  980u,   129u, 1u }, /* afrMap[212] */
    {  981u,   129u, 1u }, /* afrMap[213] */
    {  982u,   121u, 1u }, /* afrMap[214] */
    {  983u,   121u, 1u }, /* afrMap[215] */
    {  984u,   121u, 1u }, /* afrMap[216] */
    {  985u,   121u, 1u }, /* afrMap[217] */
    {  986u,   121u, 1u }, /* afrMap[218] */
    {  987u,   121u, 1u }, /* afrMap[219] */
    {  988u,   121u, 1u }, /* afrMap[220] */
    {  989u,   121u, 1u }, /* afrMap[221] */
    {  990u,   121u, 1u }, /* afrMap[222] */
    {  991u,   121u, 1u }, /* afrMap[223] */
    {  992u,   140u, 1u }, /* afrMap[224] */
    {  993u,   140u, 1u }, /* afrMap[225] */
    {  994u,   140u, 1u }, /* afrMap[226] */
    {  995u,   140u, 1u }, /* afrMap[227] */
    {  996u,   129u, 1u }, /* afrMap[228] */
    {  997u,   129u, 1u }, /* afrMap[229] */
    {  998u,   121u, 1u }, /* afrMap[230] */
    {  999u,   121u, 1u }, /* afrMap[231] */
    { 1000u,   121u, 1u }, /* afrMap[232] */
    { 1001u,   121u, 1u }, /* afrMap[233] */
    { 1002u,   121u, 1u }, /* afrMap[234] */
    { 1003u,   121u, 1u }, /* afrMap[235] */
    { 1004u,   121u, 1u }, /* afrMap[236] */
    { 1005u,   121u, 1u }, /* afrMap[237] */
    { 1006u,   121u, 1u }, /* afrMap[238] */
    { 1007u,   121u, 1u }, /* afrMap[239] */
    { 1008u,   140u, 1u }, /* afrMap[240] */
    { 1009u,   140u, 1u }, /* afrMap[241] */
    { 1010u,   140u, 1u }, /* afrMap[242] */
    { 1011u,   140u, 1u }, /* afrMap[243] */
    { 1012u,   129u, 1u }, /* afrMap[244] */
    { 1013u,   129u, 1u }, /* afrMap[245] */
    { 1014u,   121u, 1u }, /* afrMap[246] */
    { 1015u,   121u, 1u }, /* afrMap[247] */
    { 1016u,   121u, 1u }, /* afrMap[248] */
    { 1017u,   121u, 1u }, /* afrMap[249] */
    { 1018u,   121u, 1u }, /* afrMap[250] */
    { 1019u,   121u, 1u }, /* afrMap[251] */
    { 1020u,   121u, 1u }, /* afrMap[252] */
    { 1021u,   121u, 1u }, /* afrMap[253] */
    { 1022u,   121u, 1u }, /* afrMap[254] */
    { 1023u,   121u, 1u }, /* afrMap[255] */
    { 1024u,  9700u, 2u }, /* cltEnrAx[0] */
    { 1026u,  9800u, 2u }, /* cltEnrAx[1] */
    { 1028u,  9900u, 2u }, /* cltEnrAx[2] */
    { 1030u, 10000u, 2u }, /* cltEnrAx[3] */
    { 1032u, 10100u, 2u }, /* cltEnrAx[4] */
    { 1034u, 10200u, 2u }, /* cltEnrAx[5] */
    { 1036u, 10300u, 2u }, /* cltEnrAx[6] */
    { 1038u, 10400u, 2u }, /* cltEnrAx[7] */
    { 1040u, 10500u, 2u }, /* cltEnrAx[8] */
    { 1042u, 10600u, 2u }, /* cltEnrAx[9] */
    { 1044u, 10700u, 2u }, /* cltEnrAx[10] */
    { 1046u, 10800u, 2u }, /* cltEnrAx[11] */
    { 1048u, 10900u, 2u }, /* cltEnrAx[12] */
    { 1050u, 11000u, 2u }, /* cltEnrAx[13] */
    { 1052u, 11100u, 2u }, /* cltEnrAx[14] */
    { 1054u, 11200u, 2u }, /* cltEnrAx[15] */
    { 1056u,   170u, 1u }, /* cltEnrVal[0] */
    { 1057u,   160u, 1u }, /* cltEnrVal[1] */
    { 1058u,   150u, 1u }, /* cltEnrVal[2] */
    { 1059u,   140u, 1u }, /* cltEnrVal[3] */
    { 1060u,   131u, 1u }, /* cltEnrVal[4] */
    { 1061u,   122u, 1u }, /* cltEnrVal[5] */
    { 1062u,   116u, 1u }, /* cltEnrVal[6] */
    { 1063u,   111u, 1u }, /* cltEnrVal[7] */
    { 1064u,   107u, 1u }, /* cltEnrVal[8] */
    { 1065u,   104u, 1u }, /* cltEnrVal[9] */
    { 1066u,   102u, 1u }, /* cltEnrVal[10] */
    { 1067u,   100u, 1u }, /* cltEnrVal[11] */
    { 1068u,   100u, 1u }, /* cltEnrVal[12] */
    { 1069u,   100u, 1u }, /* cltEnrVal[13] */
    { 1070u,   100u, 1u }, /* cltEnrVal[14] */
    { 1071u,   100u, 1u }, /* cltEnrVal[15] */
    { 2732u,     1u, 1u }, /* transEnable */
    { 2736u,    55u, 1u }, /* wwXPct[0] */
    { 2737u,    52u, 1u }, /* wwXPct[1] */
    { 2738u,    48u, 1u }, /* wwXPct[2] */
    { 2739u,    45u, 1u }, /* wwXPct[3] */
    { 2740u,    42u, 1u }, /* wwXPct[4] */
    { 2741u,    40u, 1u }, /* wwXPct[5] */
    { 2742u,    37u, 1u }, /* wwXPct[6] */
    { 2743u,    35u, 1u }, /* wwXPct[7] */
    { 2744u,    33u, 1u }, /* wwXPct[8] */
    { 2745u,    31u, 1u }, /* wwXPct[9] */
    { 2746u,    30u, 1u }, /* wwXPct[10] */
    { 2747u,    30u, 1u }, /* wwXPct[11] */
    { 2748u,    30u, 1u }, /* wwXPct[12] */
    { 2749u,    30u, 1u }, /* wwXPct[13] */
    { 2750u,    30u, 1u }, /* wwXPct[14] */
    { 2751u,    30u, 1u }, /* wwXPct[15] */
    { 2752u,   100u, 1u }, /* wwTau[0] */
    { 2753u,    85u, 1u }, /* wwTau[1] */
    { 2754u,    70u, 1u }, /* wwTau[2] */
    { 2755u,    60u, 1u }, /* wwTau[3] */
    { 2756u,    50u, 1u }, /* wwTau[4] */
    { 2757u,    40u, 1u }, /* wwTau[5] */
    { 2758u,    32u, 1u }, /* wwTau[6] */
    { 2759u,    26u, 1u }, /* wwTau[7] */
    { 2760u,    22u, 1u }, /* wwTau[8] */
    { 2761u,    19u, 1u }, /* wwTau[9] */
    { 2762u,    17u, 1u }, /* wwTau[10] */
    { 2763u,    15u, 1u }, /* wwTau[11] */
    { 2764u,    15u, 1u }, /* wwTau[12] */
    { 2765u,    15u, 1u }, /* wwTau[13] */
    { 2766u,    15u, 1u }, /* wwTau[14] */
    { 2767u,    15u, 1u }, /* wwTau[15] */
    { 2768u,    60u, 1u }, /* asPct[0] */
    { 2769u,    50u, 1u }, /* asPct[1] */
    { 2770u,    42u, 1u }, /* asPct[2] */
    { 2771u,    35u, 1u }, /* asPct[3] */
    { 2772u,    28u, 1u }, /* asPct[4] */
    { 2773u,    22u, 1u }, /* asPct[5] */
    { 2774u,    18u, 1u }, /* asPct[6] */
    { 2775u,    14u, 1u }, /* asPct[7] */
    { 2776u,    11u, 1u }, /* asPct[8] */
    { 2777u,     9u, 1u }, /* asPct[9] */
    { 2778u,     7u, 1u }, /* asPct[10] */
    { 2779u,     5u, 1u }, /* asPct[11] */
    { 2780u,     4u, 1u }, /* asPct[12] */
    { 2781u,     4u, 1u }, /* asPct[13] */
    { 2782u,     4u, 1u }, /* asPct[14] */
    { 2783u,     4u, 1u }, /* asPct[15] */
    { 2734u,  5000u, 2u }, /* asDecayMs */
    { 2784u,     0u, 2u }, /* ignCltCorr[0] */
    { 2786u,     0u, 2u }, /* ignCltCorr[1] */
    { 2788u,     0u, 2u }, /* ignCltCorr[2] */
    { 2790u,     0u, 2u }, /* ignCltCorr[3] */
    { 2792u,     0u, 2u }, /* ignCltCorr[4] */
    { 2794u,     0u, 2u }, /* ignCltCorr[5] */
    { 2796u,     0u, 2u }, /* ignCltCorr[6] */
    { 2798u,     0u, 2u }, /* ignCltCorr[7] */
    { 2800u,     0u, 2u }, /* ignCltCorr[8] */
    { 2802u,     0u, 2u }, /* ignCltCorr[9] */
    { 2804u,     0u, 2u }, /* ignCltCorr[10] */
    { 2806u,     0u, 2u }, /* ignCltCorr[11] */
    { 2808u,     0u, 2u }, /* ignCltCorr[12] */
    { 2810u,     0u, 2u }, /* ignCltCorr[13] */
    { 2812u,     0u, 2u }, /* ignCltCorr[14] */
    { 2814u,     0u, 2u }, /* ignCltCorr[15] */
    { 2816u,  9800u, 2u }, /* ignIatAx[0] */
    { 2818u, 10000u, 2u }, /* ignIatAx[1] */
    { 2820u, 10200u, 2u }, /* ignIatAx[2] */
    { 2822u, 10400u, 2u }, /* ignIatAx[3] */
    { 2824u, 10600u, 2u }, /* ignIatAx[4] */
    { 2826u, 10800u, 2u }, /* ignIatAx[5] */
    { 2828u, 11000u, 2u }, /* ignIatAx[6] */
    { 2830u, 11200u, 2u }, /* ignIatAx[7] */
    { 2832u,     0u, 2u }, /* ignIatCorr[0] */
    { 2834u,     0u, 2u }, /* ignIatCorr[1] */
    { 2836u,     0u, 2u }, /* ignIatCorr[2] */
    { 2838u,     0u, 2u }, /* ignIatCorr[3] */
    { 2840u,     0u, 2u }, /* ignIatCorr[4] */
    { 2842u,     0u, 2u }, /* ignIatCorr[5] */
    { 2844u,     0u, 2u }, /* ignIatCorr[6] */
    { 2846u,     0u, 2u }, /* ignIatCorr[7] */
    { 2848u,     0u, 1u }, /* idleTimingEnable */
    { 2850u,   100u, 2u }, /* idleTimingKp */
    { 2852u, 65436u, 2u }, /* idleTimingMinX10 = -100 */
    { 2854u,   100u, 2u }, /* idleTimingMaxX10 */
    { 2856u,  1000u, 2u }, /* idleTimingSoftMs */
    { 2858u,     0u, 2u }, /* idleDashX10 */
    { 2860u,  1000u, 2u }, /* idleDashHoldMs */
    { 2862u,  2000u, 2u }, /* idleDashDecayMs */
    { 2865u,    47u, 1u }, /* pinMil */
    { 2864u,     1u, 1u }, /* celEnable */
    { 2866u,     1u, 1u }, /* celTestEnable */
    { 2868u,  3000u, 2u }, /* celTestOnMs */
    { 2870u,  1000u, 2u }, /* celTestGapMs */
    { 2976u,     0u, 1u }, /* vvtMode[0] */
    { 2977u,     0u, 1u }, /* vvtMode[1] */
    { 2594u,   115u, 1u }, /* pinCam1Sol */
    { 2980u,   250u, 2u }, /* vvtFreqHz */
    { 2872u,     0u, 1u }, /* knockMode */
    { 1626u,   500u, 2u }, /* pedalRpmAx[0] */
    { 1628u,   950u, 2u }, /* pedalRpmAx[1] */
    { 1630u,  1400u, 2u }, /* pedalRpmAx[2] */
    { 1632u,  1850u, 2u }, /* pedalRpmAx[3] */
    { 1634u,  2300u, 2u }, /* pedalRpmAx[4] */
    { 1636u,  2750u, 2u }, /* pedalRpmAx[5] */
    { 1638u,  3200u, 2u }, /* pedalRpmAx[6] */
    { 1640u,  3650u, 2u }, /* pedalRpmAx[7] */
    { 1642u,  4100u, 2u }, /* pedalRpmAx[8] */
    { 1644u,  4550u, 2u }, /* pedalRpmAx[9] */
    { 1646u,  5000u, 2u }, /* pedalRpmAx[10] */
    { 1648u,  5450u, 2u }, /* pedalRpmAx[11] */
    { 1650u,  5900u, 2u }, /* pedalRpmAx[12] */
    { 1652u,  6350u, 2u }, /* pedalRpmAx[13] */
    { 1654u,  6800u, 2u }, /* pedalRpmAx[14] */
    { 1656u,  7250u, 2u }, /* pedalRpmAx[15] */
    { 1658u,     0u, 2u }, /* pedalAx[0] */
    { 1660u,    50u, 2u }, /* pedalAx[1] */
    { 1662u,   100u, 2u }, /* pedalAx[2] */
    { 1664u,   150u, 2u }, /* pedalAx[3] */
    { 1666u,   200u, 2u }, /* pedalAx[4] */
    { 1668u,   250u, 2u }, /* pedalAx[5] */
    { 1670u,   300u, 2u }, /* pedalAx[6] */
    { 1672u,   400u, 2u }, /* pedalAx[7] */
    { 1674u,   500u, 2u }, /* pedalAx[8] */
    { 1676u,   600u, 2u }, /* pedalAx[9] */
    { 1678u,   700u, 2u }, /* pedalAx[10] */
    { 1680u,   800u, 2u }, /* pedalAx[11] */
    { 1682u,   850u, 2u }, /* pedalAx[12] */
    { 1684u,   900u, 2u }, /* pedalAx[13] */
    { 1686u,   950u, 2u }, /* pedalAx[14] */
    { 1688u,  1000u, 2u }, /* pedalAx[15] */
    { 1370u,     8u, 1u }, /* pedalMap[0] */
    { 1371u,     8u, 1u }, /* pedalMap[1] */
    { 1372u,     8u, 1u }, /* pedalMap[2] */
    { 1373u,     8u, 1u }, /* pedalMap[3] */
    { 1374u,     8u, 1u }, /* pedalMap[4] */
    { 1375u,     8u, 1u }, /* pedalMap[5] */
    { 1376u,     8u, 1u }, /* pedalMap[6] */
    { 1377u,     8u, 1u }, /* pedalMap[7] */
    { 1378u,     8u, 1u }, /* pedalMap[8] */
    { 1379u,     8u, 1u }, /* pedalMap[9] */
    { 1380u,     8u, 1u }, /* pedalMap[10] */
    { 1381u,     8u, 1u }, /* pedalMap[11] */
    { 1382u,     8u, 1u }, /* pedalMap[12] */
    { 1383u,     8u, 1u }, /* pedalMap[13] */
    { 1384u,     8u, 1u }, /* pedalMap[14] */
    { 1385u,     8u, 1u }, /* pedalMap[15] */
    { 1386u,    12u, 1u }, /* pedalMap[16] */
    { 1387u,    12u, 1u }, /* pedalMap[17] */
    { 1388u,    12u, 1u }, /* pedalMap[18] */
    { 1389u,    12u, 1u }, /* pedalMap[19] */
    { 1390u,    12u, 1u }, /* pedalMap[20] */
    { 1391u,    12u, 1u }, /* pedalMap[21] */
    { 1392u,    12u, 1u }, /* pedalMap[22] */
    { 1393u,    12u, 1u }, /* pedalMap[23] */
    { 1394u,    12u, 1u }, /* pedalMap[24] */
    { 1395u,    12u, 1u }, /* pedalMap[25] */
    { 1396u,    12u, 1u }, /* pedalMap[26] */
    { 1397u,    12u, 1u }, /* pedalMap[27] */
    { 1398u,    12u, 1u }, /* pedalMap[28] */
    { 1399u,    12u, 1u }, /* pedalMap[29] */
    { 1400u,    12u, 1u }, /* pedalMap[30] */
    { 1401u,    12u, 1u }, /* pedalMap[31] */
    { 1402u,    16u, 1u }, /* pedalMap[32] */
    { 1403u,    16u, 1u }, /* pedalMap[33] */
    { 1404u,    16u, 1u }, /* pedalMap[34] */
    { 1405u,    16u, 1u }, /* pedalMap[35] */
    { 1406u,    16u, 1u }, /* pedalMap[36] */
    { 1407u,    16u, 1u }, /* pedalMap[37] */
    { 1408u,    16u, 1u }, /* pedalMap[38] */
    { 1409u,    16u, 1u }, /* pedalMap[39] */
    { 1410u,    16u, 1u }, /* pedalMap[40] */
    { 1411u,    16u, 1u }, /* pedalMap[41] */
    { 1412u,    16u, 1u }, /* pedalMap[42] */
    { 1413u,    16u, 1u }, /* pedalMap[43] */
    { 1414u,    16u, 1u }, /* pedalMap[44] */
    { 1415u,    16u, 1u }, /* pedalMap[45] */
    { 1416u,    16u, 1u }, /* pedalMap[46] */
    { 1417u,    16u, 1u }, /* pedalMap[47] */
    { 1418u,    21u, 1u }, /* pedalMap[48] */
    { 1419u,    21u, 1u }, /* pedalMap[49] */
    { 1420u,    21u, 1u }, /* pedalMap[50] */
    { 1421u,    21u, 1u }, /* pedalMap[51] */
    { 1422u,    21u, 1u }, /* pedalMap[52] */
    { 1423u,    21u, 1u }, /* pedalMap[53] */
    { 1424u,    21u, 1u }, /* pedalMap[54] */
    { 1425u,    21u, 1u }, /* pedalMap[55] */
    { 1426u,    21u, 1u }, /* pedalMap[56] */
    { 1427u,    21u, 1u }, /* pedalMap[57] */
    { 1428u,    21u, 1u }, /* pedalMap[58] */
    { 1429u,    21u, 1u }, /* pedalMap[59] */
    { 1430u,    21u, 1u }, /* pedalMap[60] */
    { 1431u,    21u, 1u }, /* pedalMap[61] */
    { 1432u,    21u, 1u }, /* pedalMap[62] */
    { 1433u,    21u, 1u }, /* pedalMap[63] */
    { 1434u,    27u, 1u }, /* pedalMap[64] */
    { 1435u,    27u, 1u }, /* pedalMap[65] */
    { 1436u,    27u, 1u }, /* pedalMap[66] */
    { 1437u,    27u, 1u }, /* pedalMap[67] */
    { 1438u,    27u, 1u }, /* pedalMap[68] */
    { 1439u,    27u, 1u }, /* pedalMap[69] */
    { 1440u,    27u, 1u }, /* pedalMap[70] */
    { 1441u,    27u, 1u }, /* pedalMap[71] */
    { 1442u,    27u, 1u }, /* pedalMap[72] */
    { 1443u,    27u, 1u }, /* pedalMap[73] */
    { 1444u,    27u, 1u }, /* pedalMap[74] */
    { 1445u,    27u, 1u }, /* pedalMap[75] */
    { 1446u,    27u, 1u }, /* pedalMap[76] */
    { 1447u,    27u, 1u }, /* pedalMap[77] */
    { 1448u,    27u, 1u }, /* pedalMap[78] */
    { 1449u,    27u, 1u }, /* pedalMap[79] */
    { 1450u,    33u, 1u }, /* pedalMap[80] */
    { 1451u,    33u, 1u }, /* pedalMap[81] */
    { 1452u,    33u, 1u }, /* pedalMap[82] */
    { 1453u,    33u, 1u }, /* pedalMap[83] */
    { 1454u,    33u, 1u }, /* pedalMap[84] */
    { 1455u,    33u, 1u }, /* pedalMap[85] */
    { 1456u,    33u, 1u }, /* pedalMap[86] */
    { 1457u,    33u, 1u }, /* pedalMap[87] */
    { 1458u,    33u, 1u }, /* pedalMap[88] */
    { 1459u,    33u, 1u }, /* pedalMap[89] */
    { 1460u,    33u, 1u }, /* pedalMap[90] */
    { 1461u,    33u, 1u }, /* pedalMap[91] */
    { 1462u,    33u, 1u }, /* pedalMap[92] */
    { 1463u,    33u, 1u }, /* pedalMap[93] */
    { 1464u,    33u, 1u }, /* pedalMap[94] */
    { 1465u,    33u, 1u }, /* pedalMap[95] */
    { 1466u,    40u, 1u }, /* pedalMap[96] */
    { 1467u,    40u, 1u }, /* pedalMap[97] */
    { 1468u,    40u, 1u }, /* pedalMap[98] */
    { 1469u,    40u, 1u }, /* pedalMap[99] */
    { 1470u,    40u, 1u }, /* pedalMap[100] */
    { 1471u,    40u, 1u }, /* pedalMap[101] */
    { 1472u,    40u, 1u }, /* pedalMap[102] */
    { 1473u,    40u, 1u }, /* pedalMap[103] */
    { 1474u,    40u, 1u }, /* pedalMap[104] */
    { 1475u,    40u, 1u }, /* pedalMap[105] */
    { 1476u,    40u, 1u }, /* pedalMap[106] */
    { 1477u,    40u, 1u }, /* pedalMap[107] */
    { 1478u,    40u, 1u }, /* pedalMap[108] */
    { 1479u,    40u, 1u }, /* pedalMap[109] */
    { 1480u,    40u, 1u }, /* pedalMap[110] */
    { 1481u,    40u, 1u }, /* pedalMap[111] */
    { 1482u,    56u, 1u }, /* pedalMap[112] */
    { 1483u,    56u, 1u }, /* pedalMap[113] */
    { 1484u,    56u, 1u }, /* pedalMap[114] */
    { 1485u,    56u, 1u }, /* pedalMap[115] */
    { 1486u,    56u, 1u }, /* pedalMap[116] */
    { 1487u,    56u, 1u }, /* pedalMap[117] */
    { 1488u,    56u, 1u }, /* pedalMap[118] */
    { 1489u,    56u, 1u }, /* pedalMap[119] */
    { 1490u,    56u, 1u }, /* pedalMap[120] */
    { 1491u,    56u, 1u }, /* pedalMap[121] */
    { 1492u,    56u, 1u }, /* pedalMap[122] */
    { 1493u,    56u, 1u }, /* pedalMap[123] */
    { 1494u,    56u, 1u }, /* pedalMap[124] */
    { 1495u,    56u, 1u }, /* pedalMap[125] */
    { 1496u,    56u, 1u }, /* pedalMap[126] */
    { 1497u,    56u, 1u }, /* pedalMap[127] */
    { 1498u,    74u, 1u }, /* pedalMap[128] */
    { 1499u,    74u, 1u }, /* pedalMap[129] */
    { 1500u,    74u, 1u }, /* pedalMap[130] */
    { 1501u,    74u, 1u }, /* pedalMap[131] */
    { 1502u,    74u, 1u }, /* pedalMap[132] */
    { 1503u,    74u, 1u }, /* pedalMap[133] */
    { 1504u,    74u, 1u }, /* pedalMap[134] */
    { 1505u,    74u, 1u }, /* pedalMap[135] */
    { 1506u,    74u, 1u }, /* pedalMap[136] */
    { 1507u,    74u, 1u }, /* pedalMap[137] */
    { 1508u,    74u, 1u }, /* pedalMap[138] */
    { 1509u,    74u, 1u }, /* pedalMap[139] */
    { 1510u,    74u, 1u }, /* pedalMap[140] */
    { 1511u,    74u, 1u }, /* pedalMap[141] */
    { 1512u,    74u, 1u }, /* pedalMap[142] */
    { 1513u,    74u, 1u }, /* pedalMap[143] */
    { 1514u,    94u, 1u }, /* pedalMap[144] */
    { 1515u,    94u, 1u }, /* pedalMap[145] */
    { 1516u,    94u, 1u }, /* pedalMap[146] */
    { 1517u,    94u, 1u }, /* pedalMap[147] */
    { 1518u,    94u, 1u }, /* pedalMap[148] */
    { 1519u,    94u, 1u }, /* pedalMap[149] */
    { 1520u,    94u, 1u }, /* pedalMap[150] */
    { 1521u,    94u, 1u }, /* pedalMap[151] */
    { 1522u,    94u, 1u }, /* pedalMap[152] */
    { 1523u,    94u, 1u }, /* pedalMap[153] */
    { 1524u,    94u, 1u }, /* pedalMap[154] */
    { 1525u,    94u, 1u }, /* pedalMap[155] */
    { 1526u,    94u, 1u }, /* pedalMap[156] */
    { 1527u,    94u, 1u }, /* pedalMap[157] */
    { 1528u,    94u, 1u }, /* pedalMap[158] */
    { 1529u,    94u, 1u }, /* pedalMap[159] */
    { 1530u,   116u, 1u }, /* pedalMap[160] */
    { 1531u,   116u, 1u }, /* pedalMap[161] */
    { 1532u,   116u, 1u }, /* pedalMap[162] */
    { 1533u,   116u, 1u }, /* pedalMap[163] */
    { 1534u,   116u, 1u }, /* pedalMap[164] */
    { 1535u,   116u, 1u }, /* pedalMap[165] */
    { 1536u,   116u, 1u }, /* pedalMap[166] */
    { 1537u,   116u, 1u }, /* pedalMap[167] */
    { 1538u,   116u, 1u }, /* pedalMap[168] */
    { 1539u,   116u, 1u }, /* pedalMap[169] */
    { 1540u,   116u, 1u }, /* pedalMap[170] */
    { 1541u,   116u, 1u }, /* pedalMap[171] */
    { 1542u,   116u, 1u }, /* pedalMap[172] */
    { 1543u,   116u, 1u }, /* pedalMap[173] */
    { 1544u,   116u, 1u }, /* pedalMap[174] */
    { 1545u,   116u, 1u }, /* pedalMap[175] */
    { 1546u,   140u, 1u }, /* pedalMap[176] */
    { 1547u,   140u, 1u }, /* pedalMap[177] */
    { 1548u,   140u, 1u }, /* pedalMap[178] */
    { 1549u,   140u, 1u }, /* pedalMap[179] */
    { 1550u,   140u, 1u }, /* pedalMap[180] */
    { 1551u,   140u, 1u }, /* pedalMap[181] */
    { 1552u,   140u, 1u }, /* pedalMap[182] */
    { 1553u,   140u, 1u }, /* pedalMap[183] */
    { 1554u,   140u, 1u }, /* pedalMap[184] */
    { 1555u,   140u, 1u }, /* pedalMap[185] */
    { 1556u,   140u, 1u }, /* pedalMap[186] */
    { 1557u,   140u, 1u }, /* pedalMap[187] */
    { 1558u,   140u, 1u }, /* pedalMap[188] */
    { 1559u,   140u, 1u }, /* pedalMap[189] */
    { 1560u,   140u, 1u }, /* pedalMap[190] */
    { 1561u,   140u, 1u }, /* pedalMap[191] */
    { 1562u,   153u, 1u }, /* pedalMap[192] */
    { 1563u,   153u, 1u }, /* pedalMap[193] */
    { 1564u,   153u, 1u }, /* pedalMap[194] */
    { 1565u,   153u, 1u }, /* pedalMap[195] */
    { 1566u,   153u, 1u }, /* pedalMap[196] */
    { 1567u,   153u, 1u }, /* pedalMap[197] */
    { 1568u,   153u, 1u }, /* pedalMap[198] */
    { 1569u,   153u, 1u }, /* pedalMap[199] */
    { 1570u,   153u, 1u }, /* pedalMap[200] */
    { 1571u,   153u, 1u }, /* pedalMap[201] */
    { 1572u,   153u, 1u }, /* pedalMap[202] */
    { 1573u,   153u, 1u }, /* pedalMap[203] */
    { 1574u,   153u, 1u }, /* pedalMap[204] */
    { 1575u,   153u, 1u }, /* pedalMap[205] */
    { 1576u,   153u, 1u }, /* pedalMap[206] */
    { 1577u,   153u, 1u }, /* pedalMap[207] */
    { 1578u,   167u, 1u }, /* pedalMap[208] */
    { 1579u,   167u, 1u }, /* pedalMap[209] */
    { 1580u,   167u, 1u }, /* pedalMap[210] */
    { 1581u,   167u, 1u }, /* pedalMap[211] */
    { 1582u,   167u, 1u }, /* pedalMap[212] */
    { 1583u,   167u, 1u }, /* pedalMap[213] */
    { 1584u,   167u, 1u }, /* pedalMap[214] */
    { 1585u,   167u, 1u }, /* pedalMap[215] */
    { 1586u,   167u, 1u }, /* pedalMap[216] */
    { 1587u,   167u, 1u }, /* pedalMap[217] */
    { 1588u,   167u, 1u }, /* pedalMap[218] */
    { 1589u,   167u, 1u }, /* pedalMap[219] */
    { 1590u,   167u, 1u }, /* pedalMap[220] */
    { 1591u,   167u, 1u }, /* pedalMap[221] */
    { 1592u,   167u, 1u }, /* pedalMap[222] */
    { 1593u,   167u, 1u }, /* pedalMap[223] */
    { 1594u,   183u, 1u }, /* pedalMap[224] */
    { 1595u,   183u, 1u }, /* pedalMap[225] */
    { 1596u,   183u, 1u }, /* pedalMap[226] */
    { 1597u,   183u, 1u }, /* pedalMap[227] */
    { 1598u,   183u, 1u }, /* pedalMap[228] */
    { 1599u,   183u, 1u }, /* pedalMap[229] */
    { 1600u,   183u, 1u }, /* pedalMap[230] */
    { 1601u,   183u, 1u }, /* pedalMap[231] */
    { 1602u,   183u, 1u }, /* pedalMap[232] */
    { 1603u,   183u, 1u }, /* pedalMap[233] */
    { 1604u,   183u, 1u }, /* pedalMap[234] */
    { 1605u,   183u, 1u }, /* pedalMap[235] */
    { 1606u,   183u, 1u }, /* pedalMap[236] */
    { 1607u,   183u, 1u }, /* pedalMap[237] */
    { 1608u,   183u, 1u }, /* pedalMap[238] */
    { 1609u,   183u, 1u }, /* pedalMap[239] */
    { 1610u,   200u, 1u }, /* pedalMap[240] */
    { 1611u,   200u, 1u }, /* pedalMap[241] */
    { 1612u,   200u, 1u }, /* pedalMap[242] */
    { 1613u,   200u, 1u }, /* pedalMap[243] */
    { 1614u,   200u, 1u }, /* pedalMap[244] */
    { 1615u,   200u, 1u }, /* pedalMap[245] */
    { 1616u,   200u, 1u }, /* pedalMap[246] */
    { 1617u,   200u, 1u }, /* pedalMap[247] */
    { 1618u,   200u, 1u }, /* pedalMap[248] */
    { 1619u,   200u, 1u }, /* pedalMap[249] */
    { 1620u,   200u, 1u }, /* pedalMap[250] */
    { 1621u,   200u, 1u }, /* pedalMap[251] */
    { 1622u,   200u, 1u }, /* pedalMap[252] */
    { 1623u,   200u, 1u }, /* pedalMap[253] */
    { 1624u,   200u, 1u }, /* pedalMap[254] */
    { 1625u,   200u, 1u }, /* pedalMap[255] */
    { 2694u,     1u, 1u }, /* camPhaseMode */
    { 2695u,     0u, 1u }, /* camPhaseLevel */
    { 2696u,  1260u, 2u }, /* camPhaseAngleX10 */
    { 2698u,     2u, 1u }, /* camPhaseConfirm */
    { 2704u,    10u, 1u }, /* camToothTol */
    { 2700u,     3u, 1u }, /* cam1Pattern */
    { 2701u,     0u, 1u }, /* cam2Pattern */
    { 2684u,   800u, 2u }, /* dbwMaxDutyX10 */
    { 3746u,  2000u, 2u }, /* dbwPwmHz */
    { 3748u,    80u, 2u }, /* dbwFrictionX10 */
    { 2688u,     2u, 2u }, /* dbwDeadbandX10 */
    { 1320u,     1u, 2u }, /* dbwSfMode */
};

const hc_preset_t hc_engine_presets[] = {
    { 0u, 0, 0u, 0u, 0u }, /* Custom / user defined - populates nothing by design */
    { 1u, items_vag_18t_me75_awt, 51u, 0x03C2u, 0u }, /* VAG 1.8T AWT (ME7.5 image only) */
    { 2u, items_bosch_me711, 20u, 0x02F9u, 0u }, /* Porsche V8 donor - incomplete, refused */
    { 4u, items_bosch_me711_board, 16u, 0x02F9u, 1u }, /* Board defaults - routing only, no engine - BOARD DEFAULT */
    { 3u, items_vag_18t_me711, 1043u, 0x02F9u, 0u }, /* VAG 1.8T DBW (AWT) */
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
    for (k = 0u; k < p->n_items; k++) {
        if (p->items[k].width == 2u) {
            hc_cal_set_u16(p->items[k].offset, p->items[k].value);
        } else {
            hc_cal_set_u8(p->items[k].offset,
                          (unsigned char)p->items[k].value);
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
    for (k = 0u; k < p->n_items; k++) {
        if (p->items[k].width == 2u) {
            hc_cfg_mgr_txn_put_u8(p->items[k].offset,
                                  (unsigned char)(p->items[k].value >> 8));
            hc_cfg_mgr_txn_put_u8((unsigned int)(p->items[k].offset + 1u),
                                  (unsigned char)(p->items[k].value & 0xFFu));
        } else {
            hc_cfg_mgr_txn_put_u8(p->items[k].offset,
                                  (unsigned char)p->items[k].value);
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

