import json
import math
from pathlib import Path

from build_dashboard import OUTPUT, ROOT as BUILD_ROOT, TEMPLATE, render_page


ROOT = Path(__file__).resolve().parents[1]
MODEL = json.loads((ROOT / "docs/model_bundle.json").read_text())


def predict(scenario):
    vector = [float(scenario.get(name, 0)) for name in MODEL["feature_columns"]]
    total = MODEL["baseline_prediction"]
    for tree in MODEL["trees"]:
        index = 0
        while True:
            feature, value, left, right, missing_left = tree[index]
            if feature == -1:
                total += value
                break
            observed = vector[feature]
            if math.isnan(observed):
                index = left if missing_left else right
            else:
                index = left if observed <= value else right
    return 1 / (1 + math.exp(-total))


def scenario(line, apply_profile):
    result = dict(MODEL["reference"])
    for candidate in MODEL["lines"]:
        result[f"line_{candidate}"] = 0
    result[f"line_{line}"] = 1
    if apply_profile:
        result.update(MODEL["line_profile"][line])

    # Mirror the correlated-window updates in the browser inference path.
    result["line_positive_rate_prior_7d"] = result["line_positive_rate_prior_30d"]
    result["line_event_starts_prior_1h"] = min(result["line_event_starts_prior_3h"], 2)
    result["line_event_starts_prior_6h"] = result["line_event_starts_prior_3h"] * 1.6
    result["system_event_line_starts_prior_1h"] = result["system_event_line_starts_prior_3h"] / 3
    result["system_event_line_starts_prior_6h"] = result["system_event_line_starts_prior_3h"] * 1.7
    return result


def test_published_threshold_reproduces_held_out_metrics():
    scores = MODEL["test_scores"]
    index = round(0.58 * scores["bins"])
    tp = sum(scores["positives"][index:])
    fp = sum(scores["negatives"][index:])
    precision = tp / (tp + fp)
    recall = tp / scores["n_pos"]
    f1 = 2 * precision * recall / (precision + recall)
    base_rate = scores["n_pos"] / (scores["n_pos"] + scores["n_neg"])

    assert round(precision, 4) == 0.2381
    assert round(recall, 4) == 0.6284
    assert round(f1, 4) == 0.3454
    assert f"{precision / base_rate:.2f}×" == "1.65×"


def test_identity_and_profile_switch_scores_use_exported_tree_traversal():
    with_profile = [predict(scenario(line, True)) for line in ("A", "GS")]
    frozen_profile = [predict(scenario(line, False)) for line in ("A", "GS")]

    assert [round(value, 3) for value in with_profile] == [0.637, 0.011]
    assert [round(value, 3) for value in frozen_profile] == [0.393, 0.260]
    assert with_profile[0] - with_profile[1] > 2 * (
        frozen_profile[0] - frozen_profile[1]
    )


def test_template_build_replaces_every_placeholder():
    template = (ROOT / "docs/dashboard_template.html").read_text()
    data = json.loads((ROOT / "docs/dashboard_data.json").read_text())
    page = render_page(template, data, MODEL)

    assert "const DATA = __DATA__" not in page
    assert "const MODEL = __MODEL__" not in page
    assert "__SNAP_START__" not in page
    assert "__SNAP_END__" not in page
    assert "__ROWS__" not in page
    assert "<meta name=\"viewport\"" in page
    assert 'id="route-index"' in page


def test_dashboard_build_paths_are_anchored_to_the_repository():
    assert BUILD_ROOT == ROOT
    assert TEMPLATE == ROOT / "docs/dashboard_template.html"
    assert OUTPUT == ROOT / "docs/dashboard.html"
