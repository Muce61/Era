from enum import StrEnum


class PositionState(StrEnum):
    IDLE = "idle"
    CONTEXT_OK = "context_ok"
    SETUP_FOUND = "setup_found"
    ARMED = "armed"
    ENTRY_PENDING = "entry_pending"
    POSITION_OPEN = "position_open"
    VALIDATING = "validating"
    PROTECTED = "protected"
    EXPANDING = "expanding"
    TARGET_REACHED = "target_reached"
    CLOSED = "closed"
    COOLDOWN = "cooldown"
    EMERGENCY_EXIT = "emergency_exit"
    HALTED = "halted"


class StateEvent(StrEnum):
    CONTEXT_ALLOWED = "context_allowed"
    SETUP_DETECTED = "setup_detected"
    TRIGGER_CONFIRMED = "trigger_confirmed"
    ENTRY_SUBMITTED = "entry_submitted"
    ENTRY_FILLED = "entry_filled"
    STOP_CONFIRMED = "stop_confirmed"
    ACTIVATION_REACHED = "activation_reached"
    NEW_MFE = "new_mfe"
    TARGET_REACHED = "target_reached"
    NORMAL_EXIT = "normal_exit"
    COOLDOWN_EXPIRED = "cooldown_expired"
    SAFETY_FAILURE = "safety_failure"
    EMERGENCY_FLAT = "emergency_flat"
    HALT = "halt"
