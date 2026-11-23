import time
import threading

class TriadicMutexController:
    """
    Enforces Strict Pairwise Communication across Prime Laws 1, 2, and 3.
    Invariant: Exactly two laws communicate at a time. The third must YIELD.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._active_channel = None  # Options: (1,2), (2,3), (3,1)

    def acquire_channel(self, law_a: int, law_b: int) -> bool:
        valid_channels = {(1, 2), (2, 1), (2, 3), (3, 2), (3, 1), (1, 3)}
        pair = (min(law_a, law_b), max(law_a, law_b))
        
        if pair not in {(1, 2), (2, 3), (1, 3)}:
            raise ValueError(f"Invalid channel request: {law_a} <-> {law_b}")

        with self._lock:
            if self._active_channel is not None:
                # Channel is currently occupied
                return False
            
            self._active_channel = pair
            yielding_law = ({1, 2, 3} - set(pair)).pop()
            print(f"[MUTEX ENGAGED] Channel ({pair[0]} <-> {pair[1]}) ACTIVE. Prime Law {yielding_law} YIELDS.")
            return True

    def release_channel(self):
        with self._lock:
            if self._active_channel is not None:
                print(f"[MUTEX RELEASED] Channel {self._active_channel} CLOSED.")
                self._active_channel = None

# Instantiate global triadic controller
triadic_switch = TriadicMutexController()

if __name__ == "__main__":
    print("=== Testing Triadic Mutex Commutator ===")
    
    # Step 1: 1 talks to 2
    if triadic_switch.acquire_channel(1, 2):
        time.sleep(0.1)
        triadic_switch.release_channel()

    # Step 2: 2 talks to 3
    if triadic_switch.acquire_channel(2, 3):
        time.sleep(0.1)
        triadic_switch.release_channel()

    # Step 3: 3 talks to 1
    if triadic_switch.acquire_channel(3, 1):
        time.sleep(0.1)
        triadic_switch.release_channel()
