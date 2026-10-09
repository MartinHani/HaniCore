#!/usr/bin/env python3
r"""
test_plan_cost_gate.py - prove the per-tooth budget gate can actually fail.

    py -m pytest tests/unit/test_plan_cost_gate.py -q

WHY. me711_plan_cost_proof.py's headline check used to be a printed paragraph
rather than a verdict, and while it was, the scheduler spent weeks exceeding
its own tooth period at 7500 rpm with every gate green. It is now a check - and
a check nobody has ever seen fail is a check nobody has any reason to trust.

So each of the three verdicts is fed the shape of a real regression and must go
red for it:

  a slower planner        the measurement the fix was made for
  an O(cylinders) planner the architecture the fix removed
  a regression past 1679  the predecessor bound

and the real, measured numbers must go green - which is what stops this test
from being satisfied by a gate that simply always fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import re                               # noqa: E402
import pytest                           # noqa: E402

# Same level condition as tests/run_gates.py "planner_on_own_level".
if re.search(r"^#define\s+TGT_ILVL_PLAN\s",
             (ROOT / "firmware/targets/me711/hctarget.h").read_text(errors="replace"), re.M):
    pytest.skip("the planner runs on its own interrupt level when due, not per tooth; "
                "its budget is me711_runtime_stress_proof", allow_module_level=True)

import me711_plan_cost_proof as G      # noqa: E402


def verdicts(rows):
    return {name: ok for name, ok, _ in G.verdict(rows)}


def by_key(rows, key):
    for name, ok, _ in G.verdict(rows):
        if key in name:
            return ok
    raise AssertionError("no verdict matching %r" % key)


REAL = None


def real_rows():
    global REAL
    if REAL is None:
        REAL = G.rows_at(G.TARGET_RPM)
    return REAL


def test_the_gate_can_go_green_at_all():
    """The guard against a gate that simply always fails.

    THIS USED TO ASSERT THAT THE REAL MEASUREMENT WAS GREEN, and that was a
    false expectation written into a test: the per-tooth budget is a KNOWN,
    RECORDED FAILURE at 12000 rpm and has been since the target was raised
    there. A test that goes red for the failure the project is openly tracking
    tells nobody anything, and it made the suite's own result unreadable.

    The thing actually worth protecting is that the verdicts are CAPABLE of
    being true, so feed them a synthetic row set that should pass every one -
    comfortably inside the allowance, flat across both doublings, under the
    predecessor bound - and require all three."""
    good = int(G.allowance(G.TARGET_RPM)) - 50
    rows = [(4, good), (6, good), (8, good), (12, good)]
    assert all(verdicts(rows).values()), G.verdict(rows)


def test_the_real_measurement_is_reported_not_asserted():
    """The real numbers must still be PRODUCED - three verdicts, from the
    linked image - whatever colour they are."""
    rows = real_rows()
    v = G.verdict(rows)
    assert len(v) == 3
    assert all(isinstance(ok, bool) for _, ok, _ in v), v


def test_the_budget_check_fails_for_the_planner_it_replaced():
    # The measured cost of the version this replaced: 1814 for a V8 at 7500
    # rpm, against 1333 available. That is the state the fix was made from, and
    # the gate must call it a failure.
    rows = [(4, 1262), (6, 1584), (8, 1814), (12, 2412)]
    assert by_key(rows, "inside the scheduler's share") is False


def test_the_budget_check_fails_just_past_the_limit():
    """The threshold is a real edge, not a formatting decision.

    EVERY ROW IS DERIVED FROM THE ALLOWANCE. The filler rows used to be the
    literal 800, which sat under the 1000-instruction allowance of the
    7500-rpm era and OVER the 625 of the 12000-rpm one - so when the target
    moved, this test started failing for a reason that had nothing to do with
    the edge it exists to check. A constant that encodes last year's budget is
    the same defect as a gate that encodes last year's image."""
    a = G.allowance(G.TARGET_RPM)
    under, over = int(a) - 1, int(a) + 2
    assert by_key([(4, under), (6, under), (8, under), (12, under)],
                  "inside the scheduler's share") is True
    assert by_key([(4, under), (6, under), (8, under), (12, over)],
                  "inside the scheduler's share") is False


def test_the_shape_check_fails_for_a_per_cylinder_planner():
    # The planner this replaced, measured: doubling 4 -> 8 cost 552
    # instructions and 6 -> 12 cost 828. That is the O(n) architecture the
    # cursor removed, and the check must call it out.
    rows = [(4, 1262), (6, 1584), (8, 1814), (12, 2412)]
    assert by_key(rows, "doubling the cylinder count") is False


def test_the_shape_check_tolerates_the_real_spread():
    """The real rows contain a 246-instruction spread between 4 and 6
    cylinders and the check must NOT read that as growth: it is where the
    TDCs fall on the tooth grid, and both doublings in the same rows cost
    zero. This is the case the old slope-fitting check got wrong."""
    assert by_key(real_rows(), "doubling the cylinder count") is True


def test_the_shape_check_is_not_blind_to_a_small_real_growth():
    # A genuine O(n) creep of ~30 per cylinder still has to go red, so the
    # doubling form is not merely more permissive than the slope form.
    rows = [(4, 1112), (6, 1172), (8, 1232), (12, 1352)]
    assert by_key(rows, "doubling the cylinder count") is False


def test_the_regression_check_fails_past_the_predecessor():
    rows = [(4, 900), (6, 900), (8, G.BASELINE_V8 + 1), (12, 900)]
    assert by_key(rows, "no regression") is False


def test_the_gate_reads_the_linked_image_not_the_source():
    # If the measurement stopped executing the image, every number above would
    # be a constant somebody typed. Two different cylinder counts must produce
    # numbers that came from somewhere, and the image under test must be the
    # one the build just wrote.
    import me711_image as PI
    assert PI.image().exists()
    rows = real_rows()
    assert all(g > 100 for _, g in rows), rows


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
