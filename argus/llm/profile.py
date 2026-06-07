from __future__ import annotations

import json

from pydantic import BaseModel, Field

from argus.llm.provider_config import CONFIG_PATH as PROVIDER_CONFIG_PATH

PROFILE_PATH = PROVIDER_CONFIG_PATH.parent / "stage_profiles.json"


class StageAssignment(BaseModel):
    task_type: str
    provider_type: str
    model: str = ""


class StageProfile(BaseModel):
    assignments: list[StageAssignment] = Field(default_factory=list)

    def by_task_type(self, task_type: str) -> StageAssignment | None:
        for a in self.assignments:
            if a.task_type == task_type:
                return a
        return None

    def upsert(self, task_type: str, provider_type: str, model: str = "") -> None:
        for a in self.assignments:
            if a.task_type == task_type:
                a.provider_type = provider_type
                a.model = model
                return
        self.assignments.append(
            StageAssignment(task_type=task_type, provider_type=provider_type, model=model)
        )

    def remove(self, task_type: str) -> None:
        self.assignments = [a for a in self.assignments if a.task_type != task_type]


def load_profile() -> StageProfile:
    if PROFILE_PATH.exists():
        raw = json.loads(PROFILE_PATH.read_text("utf-8"))
        return StageProfile(**raw)
    return StageProfile()


def save_profile(profile: StageProfile) -> None:
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(profile.model_dump_json(indent=2), encoding="utf-8")


STAGE_LABELS: dict[str, str] = {
    "planning": "Planning — query decomposition & strategy",
    "scout": "Scout — web search & discovery",
    "deep_dive": "Deep-dive — scraping & extraction",
    "verification": "Verification — cross-check & conflict detection",
    "synthesis": "Synthesis — entity resolution & graph building",
    "conflict_resolution": "Conflict resolution — contradictory claim analysis",
}

ALL_STAGES = list(STAGE_LABELS.keys())


def provider_model_options() -> dict[str, list[str]]:
    """Return (provider_type → [known models]) from onboard config."""
    from argus.llm.provider_config import KNOWN_MODELS as KM
    result: dict[str, list[str]] = {}
    for ptype, mods in KM.items():
        if mods:
            result[ptype] = list(mods)
    return result
