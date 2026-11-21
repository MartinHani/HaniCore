/*
 * hcnvm_rt711.c - the relocated flash routines (store writer, eraser, staging
 * writer) as FAR code. They are only ever copied into the battery SRAM
 * (TGT_RAM_FLASHRT) and run there, so linking them into FCODE instead of the
 * one 64 KiB NCODE group is free (2026-11-04: 1860 B of NCODE). Same source as
 * the rest of the store: hcnvm.c, compiled a second time with HCNV_RT_ONLY.
 * MOD167 MEDIUM (build_me711.bat).
 */
#define HCNV_RT_ONLY 1
#include "hcnvm.c"
