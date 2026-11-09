WK = "src/ainerzero/v9/experiments/s2/worker.py"
MUTS = {
 "W12-M1_ticker_never_started": (WK, "        ticker = _ActiveTimeTicker(ledger, run_id, reservation_chunk_seconds).start()\n", "        ticker = _ActiveTimeTicker(ledger, run_id, reservation_chunk_seconds)\n"),
 "W12-M2_completion_double_counts": (WK, "            remainder = max(0.0, float(active_seconds) - already)\n", "            remainder = max(0.0, float(active_seconds))\n"),
 "W12-M3_overrun_ignored": (WK, "        overrun = self._overruns.get(run_id)\n", "        overrun = None\n"),
 "W12-M4_ticker_not_stopped": (WK, "    finally:\n        if ticker is not None:\n            ticker.stop()\n", "    finally:\n        pass\n"),
 "W12-M5_catch_up_does_not_advance": (WK, "                self._ledger.store.consume(self._run_id, active_seconds=amount)\n                self._last = now\n", "                self._ledger.store.consume(self._run_id, active_seconds=amount)\n"),
}
TESTS = ["tests/v9/experiments/test_s2_active_ticker.py"]
