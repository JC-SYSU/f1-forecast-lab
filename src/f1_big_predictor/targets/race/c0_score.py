"""C0 scoring function for Top-10 race prediction evaluation.

C0 score components:
- 45% exact position match (P1-P10)
- 35% Top-10 membership
- 20% internal order within Top-10
"""


def c0_score(predicted: list[str], actual: list[str]) -> float:
    """Calculate C0 score for Top-10 prediction.

    Args:
        predicted: Predicted driver order (full list)
        actual: Actual finish order (full list)

    Returns:
        C0 score in [0, 1]
    """
    C0_EXACT = 0.45
    C0_MEMBERSHIP = 0.35
    C0_INTERNAL_ORDER = 0.20

    predicted_set = set(predicted[:10])
    actual_set = set(actual[:10])

    # Exact position match
    exact = sum(
        1
        for i in range(10)
        if i < len(predicted) and i < len(actual) and predicted[i] == actual[i]
    )
    exact_score = (exact / 10) * C0_EXACT

    # Membership
    membership = len(predicted_set & actual_set)
    membership_score = (membership / 10) * C0_MEMBERSHIP

    # Internal order
    common = predicted_set & actual_set
    if len(common) >= 2:
        pred_order = {d: i for i, d in enumerate(predicted[:10]) if d in common}
        actual_order = {d: i for i, d in enumerate(actual[:10]) if d in common}
        pairs = [(d1, d2) for d1 in common for d2 in common if d1 != d2]
        concordant = sum(
            1
            for d1, d2 in pairs
            if (pred_order[d1] < pred_order[d2]) == (actual_order[d1] < actual_order[d2])
        )
        order_score = (
            (concordant / len(pairs)) * C0_INTERNAL_ORDER if pairs else 0.0
        )
    else:
        order_score = 0.0

    return exact_score + membership_score + order_score
