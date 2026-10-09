package com.hanicore.tunerstudio;

/**
 * Which TunerStudio commands the transport may safely re-send after a timeout or
 * transport error, and which it must not.
 *
 * THE RULE THAT MATTERS: a Burn ('B') must NEVER be blindly resent. A Burn is an
 * append-only flash commit on the ECU; a transport timeout does not mean it did
 * not happen. Resending can turn one timeout into a duplicate commit. After a
 * Burn timeout the transport must instead read the ECU's NVM state/status
 * (nvmState / nvmSource) to learn whether the commit occurred, then decide -
 * never resend on reflex. See hcts.c / hcnvm.c and the HaniCore persistence rules.
 *
 * Reads and status requests are idempotent and may be retried. A page value
 * write ('W') writes an absolute value at an offset, so a repeat is harmless.
 */
public final class RetryPolicy {

    private RetryPolicy() {}

    public static boolean mayRetry(char cmd) {
        switch (cmd) {
            case 'O':   /* output-channel block   */
            case 'A':   /* output-channel block   */
            case 'R':   /* read page              */
            case 'p':   /* read page              */
            case 'S':   /* signature              */
            case 'Q':   /* signature (scan)       */
            case 'V':   /* version                */
            case 'F':   /* protocol               */
            case 'C':   /* test comms             */
            case 'I':   /* info                   */
            case 'f':   /* capabilities           */
            case 'P':   /* page select            */
            case 'W':   /* absolute page value write - idempotent */
                return true;
            case 'B':   /* BURN - never blindly resend */
                return false;
            default:
                return false;  /* unknown / one-off ('!') actions: do not retry */
        }
    }
}
