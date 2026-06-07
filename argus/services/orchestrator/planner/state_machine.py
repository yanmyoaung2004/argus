from __future__ import annotations

from enum import StrEnum


class ResearchPhase(StrEnum):
    PLANNING = "planning"
    INVESTIGATING = "investigating"
    SYNTHESIZING = "synthesizing"
    REPORTING = "reporting"
    DONE = "done"


class ResearchStateMachine:
    TRANSITIONS: dict[ResearchPhase, list[ResearchPhase]] = {
        ResearchPhase.PLANNING: [ResearchPhase.INVESTIGATING],
        ResearchPhase.INVESTIGATING: [ResearchPhase.SYNTHESIZING],
        ResearchPhase.SYNTHESIZING: [ResearchPhase.REPORTING],
        ResearchPhase.REPORTING: [ResearchPhase.DONE],
        ResearchPhase.DONE: [],
    }

    def __init__(self) -> None:
        self._phase: ResearchPhase = ResearchPhase.PLANNING

    @property
    def phase(self) -> ResearchPhase:
        return self._phase

    def transition(self, target: ResearchPhase) -> None:
        allowed = self.TRANSITIONS.get(self._phase, [])
        if target not in allowed:
            valid = ", ".join(a.value for a in allowed)
            raise ValueError(
                f"Cannot transition from {self._phase.value} to {target.value}. "
                f"Allowed: [{valid}]"
            )
        self._phase = target
