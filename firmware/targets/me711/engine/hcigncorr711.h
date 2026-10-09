/* hcigncorr711.h - ignition timing corrections (coolant, intake air). V97. */
#ifndef HCIGNCORR711_H
#define HCIGNCORR711_H

/* The correction in 0.1 deg (+ = advance), coolant + intake air + the
   closed-loop idle timing term (hcidle711.c), each bounded to +/-30.0 deg. clt_dc / iat_dc in the page's 10*C + 10000. */
int far hc_ign_corr_x10(unsigned int clt_dc, unsigned int iat_dc);

#endif
