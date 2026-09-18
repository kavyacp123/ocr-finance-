import pytest
from app.investigations.schemas import InvestigationState
from app.investigations.state_machine import InvestigationStateMachine, MAX_INVESTIGATION_STEPS


def test_valid_transitions():
    assert InvestigationStateMachine.can_transition(
        InvestigationState.CREATED, InvestigationState.PLANNING
    )
    assert InvestigationStateMachine.can_transition(
        InvestigationState.PLANNING, InvestigationState.COLLECTING_BASELINE
    )
    assert InvestigationStateMachine.can_transition(
        InvestigationState.COLLECTING_BASELINE, InvestigationState.COLLECTING_TARGET_PERIOD
    )
    assert InvestigationStateMachine.can_transition(
        InvestigationState.COMPARING, InvestigationState.CHECKING_LINE_ITEMS
    )
    assert InvestigationStateMachine.can_transition(
        InvestigationState.GENERATING_FINDINGS, InvestigationState.COMPLETED
    )


def test_illegal_transition_rejection():
    # Cannot jump directly from CREATED to COMPLETED
    assert not InvestigationStateMachine.can_transition(
        InvestigationState.CREATED, InvestigationState.COMPLETED
    )

    with pytest.raises(ValueError, match="Illegal state transition"):
        InvestigationStateMachine.transition(
            InvestigationState.CREATED, InvestigationState.COMPLETED, step_count=1
        )


def test_max_steps_stop_condition():
    # If step_count exceeds MAX_INVESTIGATION_STEPS, it forces termination to PARTIAL
    res = InvestigationStateMachine.transition(
        InvestigationState.CHECKING_RULES, InvestigationState.CHECKING_ANOMALIES, step_count=MAX_INVESTIGATION_STEPS
    )
    assert res == InvestigationState.PARTIAL
