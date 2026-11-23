"""
Test to verify that idle unloading does not deadlock and RLock allows safe re-entry.
"""
import sys
import os
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from router import ModelManager, IDLE_TIMEOUT_SECONDS

def test_rlock_and_idle_unloading():
    print("Running test_rlock_and_idle_unloading...")
    mgr = ModelManager()

    # 1. Test RLock reentrancy on self.lock
    with mgr.lock:
        with mgr.lock:
            # Reentrant acquire should succeed immediately
            pass

    # 2. Test RLock reentrancy on self.transition_lock
    with mgr.transition_lock:
        with mgr.transition_lock:
            pass

    # 3. Simulate an active model pointer without a real process
    class DummyProc:
        def __init__(self):
            self.pid = 999999
        def poll(self):
            return None
        def kill(self):
            pass

    mgr.current_process = DummyProc()
    mgr.current_model_key = "test-model"

    # 4. Verify stop_current_model does not deadlock even if called with self.lock or self.transition_lock held
    with mgr.lock:
        mgr.stop_current_model()

    assert mgr.current_process is None, "current_process was not cleared"
    assert mgr.current_model_key is None, "current_model_key was not cleared"
    print("PASS: stop_current_model under self.lock succeeded without deadlock!")

    # 5. Verify idle_checker logic:
    mgr.current_process = DummyProc()
    mgr.current_model_key = "test-model"
    mgr.last_activity = time.time() - (IDLE_TIMEOUT_SECONDS + 10)

    # Trigger idle check
    should_stop = False
    with mgr.lock:
        if mgr.current_process and mgr.current_process.poll() is None:
            if not mgr.has_active_requests():
                idle_time = time.time() - mgr.last_activity
                if idle_time > IDLE_TIMEOUT_SECONDS:
                    should_stop = True

    assert should_stop is True, "should_stop should have triggered"
    if should_stop:
        mgr.stop_current_model()

    assert mgr.current_process is None
    print("PASS: Idle checker discharge logic executed cleanly!")

if __name__ == "__main__":
    test_rlock_and_idle_unloading()
    print("ALL TESTS PASSED!")
