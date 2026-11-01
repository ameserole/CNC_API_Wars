"""Unit tests for the integration harness's debug-log checks."""

from tests.integration.gamehost import KNOWN_ASSERTIONS, KNOWN_BASELINE_LEAKS, KNOWN_LEAKS_AFTER_MATCH, check_log


def leak_report(count: int) -> str:
    return ("Begin Simple Leak Report\n"
            "Leaked a block of size 64\n"
            f"ASSERTION FAILURE: There were {count} memory leaks. Please fix them.\n"
            "End Simple Leak Report\n")


def test_clean_log():
    assert check_log("ScriptApi: listening on 127.0.0.1:1\nLog closed\n") == []


def test_baseline_leak_report_is_tolerated():
    assert check_log("start\n" + leak_report(KNOWN_BASELINE_LEAKS)) == []


def test_extra_leaks_fail():
    problems = check_log(leak_report(KNOWN_BASELINE_LEAKS + 1))
    assert problems and "memory leaks" in problems[0]


def test_assertions_outside_leak_report_fail():
    text = "ASSERTION FAILURE: bad thing\n" + leak_report(KNOWN_BASELINE_LEAKS)
    assert check_log(text) == ["ASSERTION FAILURE: bad thing"]


def test_exception_dump_fails():
    assert check_log("********** EXCEPTION DUMP ****************") == ["EXCEPTION DUMP"]


def test_known_assertions_are_tolerated():
    text = f"ASSERTION FAILURE: {KNOWN_ASSERTIONS[0]} (case sensitive)\n"
    assert check_log(text) == []


def test_leak_baseline_can_be_raised():
    assert check_log(leak_report(KNOWN_BASELINE_LEAKS + 5), leak_baseline=KNOWN_BASELINE_LEAKS + 5) == []
    assert check_log(leak_report(KNOWN_BASELINE_LEAKS + 6), leak_baseline=KNOWN_BASELINE_LEAKS + 5)


def after_match_report(lines):
    return "Begin Simple Leak Report\n" + "".join(line + "\n" for line in lines) + "End Simple Leak Report\n"


SMALL = "Leaked a block of size 16, tagstring global operator new, from pool/dma dmaPool_16"
RENDER = "Leaked a block of size 3076, tagstring global operator new, from pool/dma (DMA)"
VECTOR = r"Leaked a block of size 64, tagstring W3A_C:\x\Vector.h, from pool/dma dmaPool_64"


def test_after_match_leaks_checked_by_kind():
    known = [SMALL] * 18 + [RENDER] * 9 + [VECTOR]
    assert check_log(after_match_report(known), KNOWN_LEAKS_AFTER_MATCH) == []

    assert check_log(after_match_report(known + [SMALL]), KNOWN_LEAKS_AFTER_MATCH)

    unexpected = "Leaked a block of size 40, tagstring ScriptApi.cpp, from pool/dma dmaPool_48"
    problems = check_log(after_match_report(known + [unexpected]), KNOWN_LEAKS_AFTER_MATCH)
    assert problems == [f"unexpected leak: {unexpected}"]


def test_desync_fails():
    problems = check_log("Latest frame for mismatch = 120 GameLogic frame = 125\n")
    assert problems and problems[0].startswith("desync")
