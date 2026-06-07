"""Metrics for evaluating research quality.

All functions are pure and operate on simple dict/list structures so they
can be unit-tested without running the full pipeline.
"""

from __future__ import annotations

from typing import Any


def entity_recall(
    ground_truth_entities: list[str],
    discovered_entities: list[str],
) -> float:
    """Fraction of ground truth entities found in output."""
    if not ground_truth_entities:
        return 1.0
    gt_lower = {e.lower() for e in ground_truth_entities}
    found_lower = {e.lower() for e in discovered_entities}
    hits = sum(1 for e in gt_lower if e in found_lower)
    return hits / len(gt_lower)


def entity_precision(
    ground_truth_entities: list[str],
    discovered_entities: list[str],
) -> float:
    """Fraction of discovered entities that match ground truth."""
    if not discovered_entities:
        return 0.0
    gt_lower = {e.lower() for e in ground_truth_entities}
    found_lower = {e.lower() for e in discovered_entities}
    hits = sum(1 for e in found_lower if e in gt_lower)
    return hits / len(found_lower)


def claim_recall(
    ground_truth_claims: list[dict[str, str]],
    discovered_claims: list[dict[str, str]],
) -> float:
    """Fraction of ground truth claims semantically present in output.

    A claim matches if any output claim contains a significant subset of its
    key terms (entity, attribute, numeric value).
    """
    if not ground_truth_claims:
        return 1.0
    hits = 0
    for gt in ground_truth_claims:
        gt_text = gt.get("text", "").lower()
        gt_tokens = set(gt_text.split())
        for dc in discovered_claims:
            dc_text = dc.get("statement", dc.get("text", "")).lower()
            dc_tokens = set(dc_text.split())
            intersection = gt_tokens & dc_tokens
            jaccard = len(intersection) / max(len(gt_tokens | dc_tokens), 1)
            if jaccard >= 0.4:
                hits += 1
                break
    return hits / len(ground_truth_claims)


def claim_precision(
    ground_truth_claims: list[dict[str, str]],
    discovered_claims: list[dict[str, str]],
) -> float:
    """Fraction of discovered claims that match ground truth.

    A claim is hallucinated if it has no close match in ground truth.
    """
    if not discovered_claims:
        return 1.0
    hits = 0
    for dc in discovered_claims:
        dc_text = dc.get("statement", dc.get("text", "")).lower()
        dc_tokens = set(dc_text.split())
        for gt in ground_truth_claims:
            gt_text = gt.get("text", "").lower()
            gt_tokens = set(gt_text.split())
            intersection = gt_tokens & dc_tokens
            jaccard = len(intersection) / max(len(gt_tokens | dc_tokens), 1)
            if jaccard >= 0.4:
                hits += 1
                break
    return hits / len(discovered_claims)


def hallucination_rate(
    ground_truth_claims: list[dict[str, str]],
    discovered_claims: list[dict[str, str]],
) -> float:
    """1 - claim_precision."""
    return 1.0 - claim_precision(ground_truth_claims, discovered_claims)


def source_coverage(
    ground_truth_sources: list[str],
    discovered_sources: list[str],
) -> float:
    """Fraction of ground truth source URLs cited in output."""
    if not ground_truth_sources:
        return 1.0
    gt_urls = {u.rstrip("/").lower() for u in ground_truth_sources}
    found_urls = {u.rstrip("/").lower() for u in discovered_sources}
    hits = sum(1 for u in gt_urls if u in found_urls)
    return hits / len(gt_urls)


def source_precision(
    ground_truth_sources: list[str],
    discovered_sources: list[str],
) -> float:
    """Fraction of cited source URLs that appear in ground truth."""
    if not discovered_sources:
        return 1.0
    gt_urls = {u.rstrip("/").lower() for u in ground_truth_sources}
    found_urls = {u.rstrip("/").lower() for u in discovered_sources}
    hits = sum(1 for u in found_urls if u in gt_urls)
    return hits / len(found_urls)


def confidence_calibration_error(
    claims: list[dict[str, Any]],
    ground_truth_texts: set[str],
) -> float:
    """Mean absolute error between confidence and correctness.

    Each claim has a 'confidence' (0-1) and is compared against ground_truth_texts
    via token overlap. Lower is better (0.0 = perfect calibration).
    """
    if not claims:
        return 0.0
    total_error = 0.0
    count = 0
    gt_lower = {t.lower() for t in ground_truth_texts}
    for claim in claims:
        text = claim.get("statement", claim.get("text", "")).lower()
        confidence = claim.get("confidence", 0.5)
        text_tokens = set(text.split())
        is_correct = any(
            len(text_tokens & set(gt.lower().split()))
            / max(len(text_tokens | set(gt.lower().split())), 1)
            >= 0.4
            for gt in gt_lower
        )
        expected = 1.0 if is_correct else 0.0
        total_error += abs(confidence - expected)
        count += 1
    return total_error / count if count else 0.0


def f1_score(precision: float, recall: float) -> float:
    """Harmonic mean of precision and recall."""
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def all_metrics(
    ground_truth: dict[str, Any],
    discovered_entities: list[str],
    discovered_claims: list[dict[str, str]],
    discovered_sources: list[str],
    research_time_seconds: float = 0.0,
    total_cost: float = 0.0,
    budget_limit: float = 0.50,
) -> dict[str, float]:
    """Compute all evaluation metrics in one call."""
    gt_entities: list[str] = ground_truth.get("entities", [])
    gt_claims: list[dict[str, str]] = ground_truth.get("claims", [])
    gt_all_sources: list[str] = []
    for c in gt_claims:
        gt_all_sources.extend(c.get("sources", []))
    gt_texts: set[str] = {c["text"] for c in gt_claims if "text" in c}

    ent_recall = entity_recall(gt_entities, discovered_entities)
    ent_prec = entity_precision(gt_entities, discovered_entities)
    cl_recall = claim_recall(gt_claims, discovered_claims)
    cl_prec = claim_precision(gt_claims, discovered_claims)
    hall = hallucination_rate(gt_claims, discovered_claims)
    src_cov = source_coverage(gt_all_sources, discovered_sources)
    src_prec = source_precision(gt_all_sources, discovered_sources)
    calib = confidence_calibration_error(
        discovered_claims,
        gt_texts,
    )

    return {
        "entity_recall": ent_recall,
        "entity_precision": ent_prec,
        "entity_f1": f1_score(ent_prec, ent_recall),
        "claim_recall": cl_recall,
        "claim_precision": cl_prec,
        "claim_f1": f1_score(cl_prec, cl_recall),
        "hallucination_rate": hall,
        "source_coverage": src_cov,
        "source_precision": src_prec,
        "source_f1": f1_score(src_prec, src_cov),
        "confidence_calibration_error": calib,
        "research_time_seconds": research_time_seconds,
        "total_cost": total_cost,
        "cost_vs_budget": total_cost / budget_limit if budget_limit > 0 else 1.0,
    }
