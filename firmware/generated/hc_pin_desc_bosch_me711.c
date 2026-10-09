/*
 * hc_pin_desc_bosch_me711.c - GENERATED. Do not edit.
 *
 * Bosch ME7.1.1 / V8 target
 * Connector: 121-pin SKE, Bosch 'Steckerbelegung ME7.1 mit 121 pol. SKE-Stecker'
 *
 * Derived by tools/config_source/hw_descriptors.py from the sources
 * named in that file. A pin this evidence does not describe has NO
 * capabilities and routable = 0; there is deliberately no
 * "spare I/O, digital in or low side" default.
 *
 * Machine-readable review copy:
 *   build/generated/hc_hw_descriptor_bosch_me711.csv
 */
#include "hc_pin_descriptor.h"

const unsigned int hc_pin_target_id = 0x02F9u;
const char hc_pin_target_name[] = "BOSCH_ME711";

const hc_pin_desc_t hc_pin_table[HC_PHYSICAL_PIN_COUNT] = {
    { 0x8000u, 0x8000u, 0u, 0xFFu }, /*   1 EL_MA */
    { 0x8000u, 0x8000u, 0u, 0xFFu }, /*   2 EL_MA */
    { 0x8000u, 0x8000u, 0u, 0xFFu }, /*   3 U_U_UBR */
    { 0x8000u, 0x0000u, 1u, 0xFFu }, /*   4 LS2VK_H|ZAS2_S */
    { 0x8000u, 0x0000u, 1u, 0xFFu }, /*   5 LS1VK_H|ZAS1_S */
    { 0x8001u, 0x0000u, 1u, 0x0Au }, /*   6 LS2HK_H */
    { 0x0100u, 0x0000u, 1u, 0xFFu }, /*   7 ZUE8 */
    { 0x0100u, 0x0000u, 1u, 0xFFu }, /*   8 ZUE7 */
    { 0x0060u, 0x0000u, 0u, 0xFFu }, /*   9 STST_S|ULVT_S */
    { 0x8001u, 0x0000u, 1u, 0x0Au }, /*  10 LS2HK_MA */
    { 0x8001u, 0x0000u, 1u, 0x0Au }, /*  11 LS2HK_S */
    { 0x8000u, 0x0000u, 1u, 0xFFu }, /*  12 LS2VK_MA */
    { 0x8000u, 0x0000u, 1u, 0xFFu }, /*  13 LS2VK_S */
    { 0x8000u, 0x0000u, 1u, 0xFFu }, /*  14 LS2VK_IA */
    { 0x8000u, 0x0000u, 1u, 0xFFu }, /*  15 LS2VK_IP */
    { 0x8001u, 0x0000u, 0u, 0xFFu }, /*  16 KS4_S|TVKAT2_S */
    { 0x0001u, 0x0000u, 0u, 0xFFu }, /*  17 PMOEL_S|TMOT2_S */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  18 TD_S */
    { 0x00A0u, 0x0000u, 1u, 0xFFu }, /*  19 TAUS_S */
    { 0x8000u, 0x8000u, 0u, 0xFFu }, /*  20 TAB2_S */
    { 0x8000u, 0x8000u, 1u, 0xFFu }, /*  21 U_U_KL15 */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  22 STST_S|ZAS1_S */
    { 0x0800u, 0x0800u, 1u, 0xFFu }, /*  23 A_S_HR */
    { 0x00A0u, 0x0000u, 1u, 0xFFu }, /*  24 EV7|LUES2_S */
    { 0x0002u, 0x0000u, 0u, 0xFFu }, /*  25 LDP_S */
    { 0x0001u, 0x0000u, 1u, 0xE1u }, /*  26 TAN_S|UBE_S */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  27 HFM_MA|SRDS_MA */
    { 0x0001u, 0x0000u, 0u, 0xFFu }, /*  28 DF_S */
    { 0x0005u, 0x0000u, 1u, 0x00u }, /*  29 SRD_S|HFM_S */
    { 0x0001u, 0x0000u, 0u, 0xFFu }, /*  30 FST_S */
    { 0x8001u, 0x0000u, 0u, 0xFFu }, /*  31 KS3_S|TVKAT1_S */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  32 SCH_SEN */
    { 0x8000u, 0x0000u, 1u, 0x09u }, /*  33 SP2_MA */
    { 0x0001u, 0x0000u, 1u, 0x09u }, /*  34 SP2_S */
    { 0x0001u, 0x0000u, 1u, 0x08u }, /*  35 SP1_S */
    { 0x8000u, 0x0000u, 1u, 0x08u }, /*  36 SP1_MA */
    { 0x0060u, 0x0000u, 1u, 0xFFu }, /*  37 TN_S */
    { 0x0002u, 0x0000u, 1u, 0xFFu }, /*  38 GRAEIN_S */
    { 0x0002u, 0x0000u, 1u, 0xFFu }, /*  39 KU_S */
    { 0x0002u, 0x0000u, 1u, 0xFFu }, /*  40 AC_S */
    { 0x0002u, 0x0000u, 0u, 0xFFu }, /*  41 KKOBI_S */
    { 0x8002u, 0x0000u, 0u, 0xFFu }, /*  42 KL 50 */
    { 0x8000u, 0x8000u, 1u, 0xFFu }, /*  43 DIAK_S */
    { 0x0060u, 0x0000u, 0u, 0xFFu }, /*  44 SLV_S */
    { 0x0060u, 0x0000u, 0u, 0xFFu }, /*  45 AAV_S|SRU2_S */
    { 0x0420u, 0x0000u, 0u, 0xFFu }, /*  46 SLP_S */
    { 0x0020u, 0x0000u, 1u, 0xFFu }, /*  47 MIL_S */
    { 0x0020u, 0x0000u, 0u, 0xFFu }, /*  48 EFLA_S */
    { 0x0000u, 0x0000u, 0u, 0xFFu }, /*  49 not assigned in the source document */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  50 SEN_MA */
    { 0x8000u, 0x0000u, 1u, 0xFFu }, /*  51 LS1VK_MA */
    { 0x8000u, 0x0000u, 1u, 0xFFu }, /*  52 LS1VK_IP */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  53 5V2 */
    { 0x0006u, 0x0000u, 0u, 0xFFu }, /*  54 VFZG_S */
    { 0x0002u, 0x0000u, 1u, 0xFFu }, /*  55 BTS_S */
    { 0x0002u, 0x0000u, 1u, 0xFFu }, /*  56 BLS_S */
    { 0x0002u, 0x0000u, 1u, 0xFFu }, /*  57 GRASV_S */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  58 CAN_L */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  59 CAN_SCH */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  60 CAN_H */
    { 0x0003u, 0x0000u, 0u, 0xFFu }, /*  61 ACD_S|TAB1_S */
    { 0x8000u, 0x8000u, 0u, 0xFFu }, /*  62 U_U_UBD */
    { 0x8001u, 0x0000u, 1u, 0x07u }, /*  63 LS1HK_H */
    { 0x0060u, 0x0000u, 0u, 0xFFu }, /*  64 TEV */
    { 0x0420u, 0x0000u, 1u, 0xFFu }, /*  65 EKPR */
    { 0x0420u, 0x0000u, 0u, 0xFFu }, /*  66 LUES1_S|STST_S */
    { 0x0006u, 0x0000u, 0u, 0xFFu }, /*  67 CRSH_S */
    { 0x8001u, 0x0000u, 1u, 0x07u }, /*  68 LS1HK_MA */
    { 0x8001u, 0x0000u, 1u, 0x07u }, /*  69 LS1HK_S */
    { 0x8000u, 0x0000u, 1u, 0xFFu }, /*  70 LS1VK_S */
    { 0x8000u, 0x0000u, 1u, 0xFFu }, /*  71 LS1VK_IA */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  72 5V2 */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  73 5V1 */
    { 0x0040u, 0x0000u, 0u, 0xFFu }, /*  74 MMS_S */
    { 0x0002u, 0x0000u, 1u, 0xFFu }, /*  75 GRAWA_S */
    { 0x0002u, 0x0000u, 1u, 0xFFu }, /*  76 GRAAUS_S */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  77 CAN_L */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  78 CAN_SCH */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  79 CAN_H */
    { 0x0002u, 0x0000u, 0u, 0xFFu }, /*  80 SLDP_S */
    { 0x0040u, 0x0000u, 1u, 0xFFu }, /*  81 KVA_S */
    { 0x800Cu, 0x0000u, 1u, 0xFFu }, /*  82 DZG+_S */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  83 5V1 */
    { 0x0001u, 0x0000u, 1u, 0x03u }, /*  84 IP2_S */
    { 0x0001u, 0x0000u, 0u, 0xFFu }, /*  85 E_A_DSBKV */
    { 0x0016u, 0x0000u, 1u, 0xFFu }, /*  86 PHA1_S */
    { 0x0016u, 0x0000u, 1u, 0xFFu }, /*  87 PHA2_S */
    { 0x00A0u, 0x0000u, 1u, 0xFFu }, /*  88 EV3 */
    { 0x00A0u, 0x0000u, 1u, 0xFFu }, /*  89 EV4 */
    { 0x8008u, 0x0000u, 0u, 0xFFu }, /*  90 DZG-_S|DZG_MA */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  91 IP_MA */
    { 0x0001u, 0x0000u, 1u, 0x01u }, /*  92 IP1_S */
    { 0x0001u, 0x0000u, 1u, 0xE0u }, /*  93 TMOT1_S */
    { 0x0100u, 0x0000u, 1u, 0xFFu }, /*  94 ZUE3 */
    { 0x0100u, 0x0000u, 1u, 0xFFu }, /*  95 ZUE4 */
    { 0x00A0u, 0x0000u, 1u, 0xFFu }, /*  96 EV1 */
    { 0x00A0u, 0x0000u, 1u, 0xFFu }, /*  97 EV2 */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  98 5V2 */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /*  99 KS_MA */
    { 0x0001u, 0x0000u, 0u, 0xFFu }, /* 100 AGRPOT_S */
    { 0x0001u, 0x0000u, 1u, 0x0Eu }, /* 101 SRD_S|TAGR_S */
    { 0x0100u, 0x0000u, 1u, 0xFFu }, /* 102 ZUE1 */
    { 0x0100u, 0x0000u, 1u, 0xFFu }, /* 103 ZUE2 */
    { 0x0060u, 0x0000u, 1u, 0xFFu }, /* 104 SRU1_S|LDR_S */
    { 0x0060u, 0x0000u, 0u, 0xFFu }, /* 105 LUV_S */
    { 0x8001u, 0x0000u, 0u, 0xFFu }, /* 106 KS1_S */
    { 0x8001u, 0x0000u, 0u, 0xFFu }, /* 107 KS2_S */
    { 0x8000u, 0x0000u, 0u, 0xFFu }, /* 108 SEN_SCH */
    { 0x0000u, 0x0000u, 0u, 0xFFu }, /* 109 not assigned in the source document */
    { 0x0100u, 0x0000u, 1u, 0xFFu }, /* 110 ZUE5 */
    { 0x0100u, 0x0000u, 1u, 0xFFu }, /* 111 ZUE6 */
    { 0x00A0u, 0x0000u, 1u, 0xFFu }, /* 112 EV5 */
    { 0x00A0u, 0x0000u, 1u, 0xFFu }, /* 113 EV6 */
    { 0x0060u, 0x0000u, 0u, 0xFFu }, /* 114 AGR_S */
    { 0x0060u, 0x0000u, 1u, 0xFFu }, /* 115 NWS_S */
    { 0x0060u, 0x0000u, 0u, 0xFFu }, /* 116 ETH_S */
    { 0x8200u, 0x0000u, 1u, 0xFFu }, /* 117 ESBM+ */
    { 0x8200u, 0x0000u, 1u, 0xFFu }, /* 118 ESBM- */
    { 0x0000u, 0x0000u, 0u, 0xFFu }, /* 119 not assigned in the source document */
    { 0x0060u, 0x0000u, 1u, 0xFFu }, /* 120 not assigned in the source document */
    { 0x0000u, 0x0000u, 0u, 0xFFu }, /* 121 not assigned in the source document */
};
