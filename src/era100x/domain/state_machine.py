from era100x.domain.enums import PositionState, StateEvent


class InvalidStateTransition(ValueError):
    pass


TRANSITIONS: dict[tuple[PositionState, StateEvent], PositionState] = {
    (PositionState.IDLE, StateEvent.CONTEXT_ALLOWED): PositionState.CONTEXT_OK,
    (PositionState.CONTEXT_OK, StateEvent.SETUP_DETECTED): PositionState.SETUP_FOUND,
    (PositionState.SETUP_FOUND, StateEvent.TRIGGER_CONFIRMED): PositionState.ARMED,
    (PositionState.ARMED, StateEvent.ENTRY_SUBMITTED): PositionState.ENTRY_PENDING,
    (PositionState.ENTRY_PENDING, StateEvent.ENTRY_FILLED): PositionState.POSITION_OPEN,
    (PositionState.POSITION_OPEN, StateEvent.STOP_CONFIRMED): PositionState.VALIDATING,
    (PositionState.VALIDATING, StateEvent.ACTIVATION_REACHED): PositionState.PROTECTED,
    (PositionState.PROTECTED, StateEvent.NEW_MFE): PositionState.EXPANDING,
    (PositionState.EXPANDING, StateEvent.NEW_MFE): PositionState.EXPANDING,
    (PositionState.PROTECTED, StateEvent.TARGET_REACHED): PositionState.TARGET_REACHED,
    (PositionState.EXPANDING, StateEvent.TARGET_REACHED): PositionState.TARGET_REACHED,
    (PositionState.TARGET_REACHED, StateEvent.NORMAL_EXIT): PositionState.CLOSED,
    (PositionState.CLOSED, StateEvent.NORMAL_EXIT): PositionState.COOLDOWN,
    (PositionState.COOLDOWN, StateEvent.COOLDOWN_EXPIRED): PositionState.IDLE,
    (PositionState.EMERGENCY_EXIT, StateEvent.EMERGENCY_FLAT): PositionState.CLOSED,
    (PositionState.EMERGENCY_EXIT, StateEvent.HALT): PositionState.HALTED,
}

_ACTIVE_STATES = {
    PositionState.CONTEXT_OK,
    PositionState.SETUP_FOUND,
    PositionState.ARMED,
    PositionState.ENTRY_PENDING,
    PositionState.POSITION_OPEN,
    PositionState.VALIDATING,
    PositionState.PROTECTED,
    PositionState.EXPANDING,
    PositionState.TARGET_REACHED,
}


def transition(current: PositionState, event: StateEvent) -> PositionState:
    if event is StateEvent.SAFETY_FAILURE and current in _ACTIVE_STATES:
        return PositionState.EMERGENCY_EXIT
    try:
        return TRANSITIONS[(current, event)]
    except KeyError as exc:
        raise InvalidStateTransition(f"illegal transition: {current} + {event}") from exc
