"""
Investigation State Machine
===========================

WHY:   An autonomous agent must never loop infinitely.
       The investigation must progress through explicit, pre-defined states.
       Every transition is strictly validated against a valid transition table.
       MAX_INVESTIGATION_STEPS = 25 is enforced.

WHERE: Controlled by the InvestigationEngine during pipeline execution.
"""

from typing import Dict, Set
from app.investigations.schemas import InvestigationState

MAX_INVESTIGATION_STEPS = 25


class InvestigationStateMachine:
    """
    Finite state machine enforcing valid progression through an investigation lifecycle.
    """

    _VALID_TRANSITIONS: Dict[InvestigationState, Set[InvestigationState]] = {
        InvestigationState.CREATED: {InvestigationState.PLANNING, InvestigationState.FAILED},
        InvestigationState.PLANNING: {InvestigationState.COLLECTING_BASELINE, InvestigationState.FAILED},
        InvestigationState.COLLECTING_BASELINE: {InvestigationState.COLLECTING_TARGET_PERIOD, InvestigationState.FAILED},
        InvestigationState.COLLECTING_TARGET_PERIOD: {InvestigationState.COMPARING, InvestigationState.FAILED},
        InvestigationState.COMPARING: {InvestigationState.CHECKING_LINE_ITEMS, InvestigationState.CHECKING_RULES, InvestigationState.FAILED},
        InvestigationState.CHECKING_LINE_ITEMS: {InvestigationState.CHECKING_PRICE_CHANGE, InvestigationState.CHECKING_QUANTITY_CHANGE, InvestigationState.FAILED},
        InvestigationState.CHECKING_PRICE_CHANGE: {InvestigationState.CHECKING_QUANTITY_CHANGE, InvestigationState.CHECKING_DUPLICATES, InvestigationState.FAILED},
        InvestigationState.CHECKING_QUANTITY_CHANGE: {InvestigationState.CHECKING_DUPLICATES, InvestigationState.CHECKING_RULES, InvestigationState.FAILED},
        InvestigationState.CHECKING_DUPLICATES: {InvestigationState.CHECKING_RULES, InvestigationState.CHECKING_ANOMALIES, InvestigationState.FAILED},
        InvestigationState.CHECKING_RULES: {InvestigationState.CHECKING_ANOMALIES, InvestigationState.CHECKING_RELATIONSHIPS, InvestigationState.FAILED},
        InvestigationState.CHECKING_ANOMALIES: {InvestigationState.CHECKING_RELATIONSHIPS, InvestigationState.COLLECTING_EVIDENCE, InvestigationState.FAILED},
        InvestigationState.CHECKING_RELATIONSHIPS: {InvestigationState.COLLECTING_EVIDENCE, InvestigationState.GENERATING_FINDINGS, InvestigationState.FAILED},
        InvestigationState.COLLECTING_EVIDENCE: {InvestigationState.GENERATING_FINDINGS, InvestigationState.FAILED},
        InvestigationState.GENERATING_FINDINGS: {InvestigationState.COMPLETED, InvestigationState.PARTIAL, InvestigationState.FAILED},
        InvestigationState.COMPLETED: set(),
        InvestigationState.PARTIAL: set(),
        InvestigationState.FAILED: set(),
    }

    @classmethod
    def can_transition(cls, from_state: InvestigationState, to_state: InvestigationState) -> bool:
        allowed = cls._VALID_TRANSITIONS.get(from_state, set())
        return to_state in allowed

    @classmethod
    def transition(
        cls,
        from_state: InvestigationState,
        to_state: InvestigationState,
        step_count: int,
    ) -> InvestigationState:
        if step_count >= MAX_INVESTIGATION_STEPS:
            # Force termination to PARTIAL or FAILED
            return InvestigationState.PARTIAL

        if not cls.can_transition(from_state, to_state):
            raise ValueError(f"Illegal state transition from {from_state.value} to {to_state.value}")

        return to_state
