import json
from pathlib import Path

import pytest

from scripts.review86_ltx_controls import (
    apply_ltx_control_projection, derive_ltx_processing_geometry,
    ltx_duration_info, reviewed_ltx_controls, reviewed_ltx_config, SOURCE_HASHES, LONG_SIDE_FIELDS,
)


ROOT = Path(__file__).resolve().parents[1]


def graph(number):
    return json.loads((ROOT / f"workflows/api/local-card-{number}.api.json").read_text("utf-8"))


def spec(number):
    workflow_id = f"local-card-{number}"
    return {"id": workflow_id, "source_hash": SOURCE_HASHES[workflow_id]}


@pytest.mark.parametrize("number", [49, 51])
def test_default_zero_pair_keeps_source_graph_exactly(number):
    original = graph(number)
    result = apply_ltx_control_projection(original, spec(number), {})
    assert result == original
    assert result is not original


def test_card49_custom_uses_real_loader_fields_and_disables_second_resize():
    original = graph(49)
    result = apply_ltx_control_projection(original, spec(49),
                                          {"363:custom_width": 640, "363:custom_height": 0, "467:value": 0.5})
    assert result["363"]["inputs"]["custom_width"] == 640
    assert result["453"]["inputs"]["resize_type"] == "scale dimensions"
    assert result["453"]["inputs"]["resize_type.width"] == 0
    assert "resize_type.longer_size" not in result["453"]["inputs"]
    assert result["467"]["inputs"]["value"] == 0.5
    assert result["448"]["inputs"]["scale_by"] == ["467", 0]
    assert set(result) == set(original)
    assert original["363"]["inputs"]["custom_width"] == 0


def test_card51_custom_preserves_rounding_links_and_tracking_chain():
    original = graph(51)
    result = apply_ltx_control_projection(original, spec(51),
                                          {"1084:custom_width": 640, "1084:custom_height": 480})
    assert result["1064"]["inputs"]["scale_to_side"] == "None"
    assert result["1064"]["inputs"]["round_to_multiple"] == "32"
    assert result["1058"] == original["1058"]
    assert result["1095"] == original["1095"]
    assert set(result) == set(original)
    restored = apply_ltx_control_projection(result, spec(51),
                                            {"1084:custom_width": 0, "1084:custom_height": 0})
    assert restored == original


@pytest.mark.parametrize("values", [{"363:custom_width": -1}, {"363:custom_width": 8193},
                                     {"363:custom_height": 1.5}, {"467:value": 0},
                                     {"467:value": True}, {"467:value": float("nan")}])
def test_invalid_native_inputs_fail_before_gpu(values):
    with pytest.raises(ValueError):
        apply_ltx_control_projection(graph(49), spec(49), values)


def test_changed_route_is_not_silently_reinterpreted():
    original = graph(51)
    original["1064"]["inputs"]["image"] = ["other", 0]
    with pytest.raises(ValueError):
        apply_ltx_control_projection(original, spec(51), {})


def test_card51_default_math_matches_existing_picker_path():
    result = derive_ltx_processing_geometry(spec(51), {}, 638, 360)
    assert result["source"] == {"width": 640, "height": 360}
    assert result["layerTarget"] == {"width": 1280, "height": 736}
    assert result["target"] == {"width": 640, "height": 368}
    assert result["custom"] is False


def test_card51_one_zero_edge_uses_ratio_then_alignment_and_half_space():
    values = {"1084:custom_width": 0, "1084:custom_height": 480}
    result = derive_ltx_processing_geometry(spec(51), values, 1920, 1080)
    assert result["source"] == {"width": 856, "height": 480}
    assert result["layerTarget"] == {"width": 864, "height": 480}
    assert result["target"] == {"width": 432, "height": 240}
    assert result["crop"]["x"] == pytest.approx(0)
    assert result["crop"]["y"] > 0
    assert result["crop"]["height"] == pytest.approx(1066.6666666666667)


def test_changed_ratio_is_center_crop_not_stretch():
    result = derive_ltx_processing_geometry(spec(51),
                                            {"1084:custom_width": 640, "1084:custom_height": 640}, 1920, 1080)
    assert result["crop"] == {"x": 420, "y": 0, "width": 1080, "height": 1080}
    assert result["target"] == {"width": 320, "height": 320}
    center_x = result["crop"]["x"] + 0.5 * result["crop"]["width"]
    center_y = result["crop"]["y"] + 0.5 * result["crop"]["height"]
    assert (center_x, center_y) == (960, 540)


def test_card49_scale_is_applied_after_vhs_custom_size():
    result = derive_ltx_processing_geometry(spec(49),
                                            {"363:custom_width": 640, "363:custom_height": 0,
                                             "467:value": 0.5}, 1920, 1080)
    assert result["source"] == {"width": 640, "height": 352}
    assert result["target"] == {"width": 320, "height": 176}


def test_native_frame_grid_distinguishes_requested_and_encoded_time():
    result = ltx_duration_info(2)
    assert result["requestedFrames"] == 51
    assert result["gridFrames"] == 49
    assert result["gridDurationSeconds"] == 1.96
    assert result["frameFormula"] == "25*a+1"


def test_reviewed_field_defaults_targets_and_help_are_source_based():
    fields = reviewed_ltx_controls("local-card-51")
    assert len(fields) == 2
    assert all(field["value"] == 0 and field["max"] == 8192 for field in fields)
    assert all(field["dimensionGroup"] == "video-size" for field in fields)
    assert all(len(field["help"]) <= 12 for field in fields)
    assert all(field["targets"][0]["node"] == "1084" for field in fields)


def test_wrong_source_hash_cannot_enable_projection_or_config():
    wrong = {"id": "local-card-49", "source_hash": "0" * 64}
    with pytest.raises(ValueError):
        apply_ltx_control_projection(graph(49), wrong, {})
    with pytest.raises(ValueError):
        reviewed_ltx_config("local-card-49", {"sourceHash": "0" * 64, "controls": []})


def test_config_adds_native_fields_without_replacing_defaults():
    cfg = {"sourceHash": SOURCE_HASHES["local-card-49"], "controls":
           [{"id": "404:value", "value": 1280, "targets": [{"node": "404", "input": "value"}]}]}
    result = reviewed_ltx_config("local-card-49", cfg, graph(49))
    assert result["controls"][0]["value"] == 1280
    assert result["controls"][0]["min"] == 1
    assert len(result["controls"]) == 4
    assert cfg["controls"][0].get("min") is None
    assert reviewed_ltx_config("local-card-49", result, graph(49)) == result


def test_points_config_adds_geometry_control_ids():
    cfg = {"sourceHash": SOURCE_HASHES["local-card-51"], "controls":
           [{"id": "1095:points", "value": "{}", "previewRecipe": {"longSide": 1280}},
            {"id": "1105:value", "value": 1280, "targets": [{"node": "1064", "input": "scale_to_length"}]}],
           "pointsRecipe": {"node": "1095", "longSide": 1280}}
    result = reviewed_ltx_config("local-card-51", cfg, graph(51))
    assert result["pointsRecipe"]["postScale"] == 0.5
    assert result["controls"][0]["previewRecipe"]["customWidthControlId"] == "1084:custom_width"
    assert result["pointsRecipe"]["longSide"] == 1280


def test_duration_config_keeps_value_and_targets():
    cfg = {"sourceHash": SOURCE_HASHES["local-card-125"], "controls":
           [{"id": "208:value", "value": 5, "targets": [{"node": "233", "input": "values.a"}]}]}
    result = reviewed_ltx_config("local-card-125", cfg, graph(125))
    duration = result["controls"][0]
    assert duration["value"] == 5
    assert duration["targets"] == cfg["controls"][0]["targets"]
    assert duration["effectiveDuration"]["stepFrames"] == 8
    assert duration["frameFormula"]["fps"] == 25


@pytest.mark.parametrize("workflow_id", sorted(LONG_SIDE_FIELDS))
def test_all_reviewed_long_side_bounds_keep_defaults_and_bindings(workflow_id):
    number = int(workflow_id.rsplit("-", 1)[1])
    field_id, targets, minimum, maximum = LONG_SIDE_FIELDS[workflow_id]
    field = {"id": field_id, "value": 1280, "min": 0, "step": 1,
             "targets": [{"node": node, "input": name} for node, name in targets]}
    cfg = {"sourceHash": SOURCE_HASHES[workflow_id], "controls": [field]}
    result = reviewed_ltx_config(workflow_id, cfg, graph(number))
    output = result["controls"][0]
    assert output["min"] == minimum
    assert output["max"] == maximum
    assert output["value"] == 1280
    assert output["targets"] == field["targets"]
    assert cfg["controls"][0]["min"] == 0


def test_stricter_existing_custom_limits_are_not_relaxed():
    cfg = {"sourceHash": SOURCE_HASHES["local-card-41"], "controls": [
        {"id": "434:scale_to_length", "value": 1024, "min": 1, "max": 4096,
         "targets": [{"node": "434", "input": "scale_to_length"}],
         "customRange": {"min": 512, "max": 2048, "step": 64}}]}
    result = reviewed_ltx_config("local-card-41", cfg, graph(41))["controls"][0]
    assert (result["min"], result["max"], result["step"]) == (512, 2048, 64)
    assert result["customRange"] == {"min": 512, "max": 2048, "step": 64}


def test_native_long_side_target_change_is_rejected():
    cfg = {"sourceHash": SOURCE_HASHES["local-card-40"], "controls": [
        {"id": "37:value", "value": 1024, "targets": [{"node": "other", "input": "scale_to_length"}]}]}
    with pytest.raises(ValueError):
        reviewed_ltx_config("local-card-40", cfg, graph(40))


def test_tightening_min_keeps_existing_step_grid_valid():
    cfg = {"sourceHash": SOURCE_HASHES["local-card-40"], "controls": [
        {"id": "37:value", "value": 1280, "min": 0, "step": 64,
         "targets": [{"node": "38", "input": "scale_to_length"}]}]}
    field = reviewed_ltx_config("local-card-40", cfg, graph(40))["controls"][0]
    assert field["min"] == 64
    assert (field["value"] - field["min"]) % field["step"] == 0
