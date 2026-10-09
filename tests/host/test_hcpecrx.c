/*
 * test_hcpecrx.c - host test for the PEC6 RX ring arithmetic (hcpecrx_me711.c).
 *
 * Defining HC_PECRX_HOST_TEST includes only the SFR-free ring functions. This
 * proves the producer/consumer index maths - the part that must be exactly right
 * for the interrupt-free receive path - without any C167 hardware.
 */
#define HC_PECRX_HOST_TEST 1
#include "hcpecrx_me711.c"

#include <assert.h>
#include <stdio.h>

#define SZ 256u
static unsigned char backing[SZ];

/* Simulate PEC delivering the next `n` bytes `val`, `val+1`, ... into the ring
   (write where PEC would, then advance head). Returns the next value to use. */
static unsigned char produce_seq(hc_pecrx_t *r, unsigned int n, unsigned char val)
{
    unsigned int i;
    for (i = 0u; i < n; i++) {
        r->buf[(r->head + i) & r->mask] = val++;
    }
    hc_pecrx_produced(r, n);
    return val;
}

static void test_basic_fifo(void)
{
    hc_pecrx_t r; unsigned char b; unsigned int i;
    hc_pecrx_ring_init(&r, backing, SZ);
    (void)produce_seq(&r, 10u, 100u);
    assert(hc_pecrx_available(&r) == 10u);
    for (i = 0u; i < 10u; i++) {
        assert(hc_pecrx_pop(&r, &b) == 1u);
        assert(b == (unsigned char)(100u + i));
    }
    assert(hc_pecrx_pop(&r, &b) == 0u);
    assert(r.overflow == 0u);
    printf("  basic FIFO order + available: OK\n");
}

static void test_fill_exact(void)
{
    hc_pecrx_t r; unsigned char b; unsigned int i;
    hc_pecrx_ring_init(&r, backing, SZ);
    (void)produce_seq(&r, SZ, 0u);
    assert(hc_pecrx_available(&r) == SZ);
    assert(r.overflow == 0u);
    for (i = 0u; i < SZ; i++) {
        assert(hc_pecrx_pop(&r, &b) == 1u && b == (unsigned char)i);
    }
    printf("  fill exactly to size, no overflow: OK\n");
}

static void test_overflow(void)
{
    hc_pecrx_t r; unsigned char b; unsigned int i;
    hc_pecrx_ring_init(&r, backing, SZ);
    /* deliver size+5 with no consumer: the oldest 5 are lost */
    (void)produce_seq(&r, SZ + 5u, 0u);
    assert(r.overflow == 1u);
    assert(hc_pecrx_available(&r) == SZ);
    /* the newest `size` bytes remain, i.e. values 5..(size+4) */
    for (i = 0u; i < SZ; i++) {
        assert(hc_pecrx_pop(&r, &b) == 1u);
        assert(b == (unsigned char)(5u + i));
    }
    printf("  overflow: oldest dropped, newest %u intact, counted: OK\n", SZ);
}

static void test_stream(void)
{
    hc_pecrx_t r; unsigned char b; unsigned char expect = 0u; unsigned char nextv = 0u;
    unsigned long produced = 0u, consumed = 0u; int round;
    hc_pecrx_ring_init(&r, backing, SZ);
    /* Interleave bursts and drains over far more than the ring size, always
       keeping the producer within `size` of the consumer so nothing is lost. */
    for (round = 0; round < 100000; round++) {
        unsigned int burst = 1u + (unsigned int)((round * 37u) % 120u);
        unsigned int room = SZ - hc_pecrx_available(&r);
        unsigned int drainn;
        if (burst > room) burst = room;
        nextv = produce_seq(&r, burst, nextv);
        produced += burst;
        drainn = 1u + (unsigned int)((round * 53u) % 110u);
        while (drainn-- && hc_pecrx_pop(&r, &b)) {
            assert(b == expect);
            expect++;
            consumed++;
        }
        assert(r.overflow == 0u);
    }
    printf("  streamed %lu bytes in/%lu out, in order, no overflow: OK\n",
           produced, consumed);
}

int main(void)
{
    printf("hcpecrx host tests\n");
    test_basic_fifo();
    test_fill_exact();
    test_overflow();
    test_stream();
    printf("PASS: all hcpecrx host tests\n");
    return 0;
}
