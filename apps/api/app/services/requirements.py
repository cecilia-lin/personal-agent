"""Explicit supported shopping language; unknown requirements are never discarded."""
import re
from app.domain.models import Problem

FEATURES = {
    "replaceable_bulb": "replaceable bulb",
    "replaceable_light_module": "replaceable light module",
    "serviceable_components": "serviceable components",
}


def supported_requirement(goal, selected=None):
    text = goal.casefold().strip().rstrip(".!?")
    found = [key for key, phrase in FEATURES.items() if phrase in text]
    if len(found) > 1:
        raise Problem("Choose one supported required feature per shopping task.", 422)
    for phrase in FEATURES.values():
        text = text.replace(phrase, "")
    allowed = {"find", "choose", "consider", "buy", "get", "a", "an", "the", "me", "my", "i", "need", "want",
               "please", "affordable", "repairable", "desk", "task", "light", "lamp", "lights", "with", "that", "has", "is"}
    words = re.findall(r"[a-z]+|[^a-z\s]", text)
    if not words or not ({"light", "lamp", "lights"} & set(words)) or any(word not in allowed for word in words):
        raise Problem("This demo supports desk lights with repairability, a replaceable bulb, a replaceable light module, or serviceable components. Extra requirements cannot be interpreted. Use the requirement selector and the separate budget/urgency fields.", 422)
    inferred = found[0] if found else "repairability"
    if selected and found and selected != inferred:
        raise Problem("The selected feature conflicts with the feature in the shopping request.", 422)
    return selected or inferred


def claim_required(task, preferences):
    return bool(task.get("essential_requirement") or task.get("requirement", "repairability") != "repairability" or preferences["repairable"])
