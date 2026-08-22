import time

class HvacStateMachine:
    def __init__(self):
        self.current_state = "OFF"
        self.last_state_change = time.time()
        self.in_rest_period = False
        self.rest_start_time = 0.0

    def compute_required_state(self, current_temp: float, t_min: float, t_max: float) -> tuple[str, bool]:
        now = time.time()
        
        if self.in_rest_period:
            if now - self.rest_start_time >= 300:
                self.in_rest_period = False
            else:
                return "OFF", False

        if self.current_state in ["HEATING", "COOLING"]:
            if now - self.last_state_change >= 600:
                self.in_rest_period = True
                self.rest_start_time = now
                self.current_state = "OFF"
                self.last_state_change = now
                return "OFF", False

        target_state = "OFF"
        request_blind_close = False

        if current_temp < t_min:
            target_state = "HEATING"
            if current_temp >= (t_min - 1.0):
                request_blind_close = True
        elif current_temp > t_max:
            target_state = "COOLING"
            if current_temp <= (t_max + 1.0):
                request_blind_close = True

        if target_state != self.current_state and not self.in_rest_period:
            self.current_state = target_state
            self.last_state_change = now

        return self.current_state, request_blind_close
