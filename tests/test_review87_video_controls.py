import copy
import json
from pathlib import Path

import pytest
from public_fixtures import historical_path

from scripts.review87_video_controls import (
    POLICIES, SOURCE_HASHES, WAN_FIELDS, OUTPUT_LOOP_POLICIES,
    reviewed_video_controls, reviewed_video_config, apply_video_control_projection,
    derive_video_processing_geometry, finalize_video_schema,
)

ROOT = Path(__file__).resolve().parents[1]


def graph(wid):
    return json.loads((ROOT/"workflows/api"/(wid+".api.json")).read_text("utf-8"))


def spec(wid):
    return {"id": wid, "source_hash": SOURCE_HASHES[wid]}


def cfg(wid):
    return json.loads((ROOT/"public/workflow-interfaces.json").read_text("utf-8"))["workflows"][wid]


@pytest.mark.parametrize("wid", sorted(POLICIES))
def test_zero_pair_preserves_authored_graph_and_original_bytes(wid):
    original = graph(wid)
    result = apply_video_control_projection(original, spec(wid), {})
    assert result == original
    assert result is not original
    assert cfg(wid)["sourceHash"] == SOURCE_HASHES[wid]


@pytest.mark.parametrize("wid", sorted(POLICIES))
def test_custom_size_reaches_conditions_reference_and_background_without_new_nodes(wid):
    p, original = POLICIES[wid], graph(wid)
    result = apply_video_control_projection(original, spec(wid), {p["widthId"]:640, p["heightId"]:480})
    assert set(result) == set(original)
    assert result[p["loader"]]["inputs"]["custom_width"] == 640
    assert result[p["loader"]]["inputs"]["custom_height"] == 480
    assert result[p["layer"]]["inputs"]["scale_to_side"] == "None"
    assert result[p["layer"]]["inputs"]["round_to_multiple"] == str(p["customMultiple"])
    assert result[p["model"]] == original[p["model"]]
    assert all(result[n] == original[n] for n in p["reference"])
    restored = apply_video_control_projection(result, spec(wid), {p["widthId"]:0, p["heightId"]:0})
    assert restored == original


@pytest.mark.parametrize("wid", sorted(POLICIES))
def test_interface_additions_keep_existing_values_keys_targets_and_text_defaults(wid):
    original = cfg(wid)
    result = reviewed_video_config(wid, original, graph(wid))
    before = {f["id"]: f for f in original["controls"]}
    after = {f["id"]: f for f in result["controls"]}
    for id, f in before.items():
        for key in ("value", "key", "targets", "derived", "members", "options"):
            assert after[id].get(key) == f.get(key)
    assert all(f["value"] == 0 for f in reviewed_video_controls(wid))
    assert original == cfg(wid)
    assert reviewed_video_config(wid, result, graph(wid)) == result
    if wid == "local-card-5":
        assert after["415:scale_to_length"]["hidden"] is True


@pytest.mark.parametrize("wid", sorted(WAN_FIELDS))
def test_fractional_pose_and_face_inputs_survive_compiler_intersection(wid):
    config = reviewed_video_config(wid, cfg(wid), graph(wid))
    for f in config["controls"]:
        if f["id"] in (WAN_FIELDS[wid]["pose"], WAN_FIELDS[wid]["face"]):
            f["step"] = 1
    final = finalize_video_schema({**spec(wid), "controls":config["controls"]}, template=graph(wid))
    for f in final["controls"]:
        if f["id"] in (WAN_FIELDS[wid]["pose"], WAN_FIELDS[wid]["face"]):
            assert (f["min"], f["max"], f["step"]) == (0,10,0.001)
    # Scalar binding changes only the exact reachable embed inputs.
    g = graph(wid)
    model = WAN_FIELDS[wid]["model"]
    g[model]["inputs"]["pose_strength"] = 0.85
    g[model]["inputs"]["face_strength"] = 0.6
    result = apply_video_control_projection(g, spec(wid), {})
    assert result[model]["inputs"]["pose_strength"] == 0.85
    assert result[model]["inputs"]["face_strength"] == 0.6


def test_segmentation_text_explains_target_on_video_not_generation_description():
    for wid in ("local-card-24", "local-card-25", "local-card-27", "local-card-116"):
        fields = WAN_FIELDS[wid]
        config = reviewed_video_config(wid, cfg(wid), graph(wid))
        text = next(t for t in config["texts"] if t["id"] == fields["segment"])
        assert text["label"].startswith("定位")
        assert "原视频" in text["help"]
        node = graph(wid)[fields["segmentation"]]
        assert node["inputs"]["prompt"] == [fields["prompt"],0]


def test_loop_changes_only_real_video_output_not_samplers_and_preserves_audio():
    wid, original = "local-card-5", graph("local-card-5")
    result = apply_video_control_projection(original, spec(wid), {"395:loop_count":2})
    assert result["395"]["inputs"]["loop_count"] == 2
    assert result["395"]["inputs"]["audio"] == ["399",2]
    assert result["407"] == original["407"]
    assert result["386"] == original["386"]
    assert OUTPUT_LOOP_POLICIES[wid]["playsFormula"] == "loop_count+1"
    conflicting = copy.deepcopy(original)
    conflicting["395"]["inputs"]["trim_to_audio"] = True
    with pytest.raises(ValueError, match="音频"):
        apply_video_control_projection(conflicting, spec(wid), {"395:loop_count":1})


@pytest.mark.parametrize("value", [-1, 8097, 1.5, True, float("nan")])
def test_bad_dimensions_reject_before_submission(value):
    with pytest.raises(ValueError):
        apply_video_control_projection(graph("local-card-24"), spec("local-card-24"), {"3751:custom_width":value})


@pytest.mark.parametrize("value", [-1, 101, 0.5, True])
def test_bad_output_loop_rejects(value):
    with pytest.raises(ValueError):
        apply_video_control_projection(graph("local-card-5"), spec("local-card-5"), {"395:loop_count":value})


def test_source_or_route_drift_cannot_silently_enable_projected_dimensions():
    with pytest.raises(ValueError):
        apply_video_control_projection(graph("local-card-24"), {"id":"local-card-24", "source_hash":"0"*64}, {})
    changed = graph("local-card-24")
    changed["3689"]["inputs"]["width"] = 100
    with pytest.raises(ValueError, match="参考"):
        apply_video_control_projection(changed, spec("local-card-24"), {})


@pytest.mark.parametrize("wid", sorted(POLICIES))
def test_custom_one_zero_side_and_native_model_alignment(wid):
    p = POLICIES[wid]
    ratio = derive_video_processing_geometry(spec(wid), {p["widthId"]:640, p["heightId"]:0},1920,1080)
    assert ratio["loader"] == {"width":640,"height":360}
    assert ratio["target"]["width"] == 640
    assert ratio["target"]["height"] % p["customMultiple"] == 0
    square = derive_video_processing_geometry(spec(wid), {p["widthId"]:640,p["heightId"]:640},1920,1080)
    assert square["crop"] == dict(x=420,y=0,width=1080,height=1080)
    assert square["target"] == dict(width=640,height=640)


@pytest.mark.parametrize("values", [{"3751:custom_width":1,"3751:custom_height":1},
                                     {"3751:custom_height":8096}, {"3750:value":100000}])
def test_effective_size_overflow_or_too_small_is_rejected_before_queue(values):
    with pytest.raises(ValueError):
        derive_video_processing_geometry(spec("local-card-24"),values,1920,1080)


def test_historical_native_inputs_agree_with_reviewed_widgets():
    native = json.loads(historical_path('workflow-controls-review87/native-VHS_LoadVideo.json').read_text("utf-8"))["VHS_LoadVideo"]["input"]["required"]
    assert native["custom_width"][1] == native["custom_height"][1]
    assert native["custom_width"][1]["default"] == 0
    for wid, p in POLICIES.items():
        for field in reviewed_video_controls(wid)[:2]:
            assert field["max"] <= native[field["key"]][1]["max"]
    native = json.loads(historical_path('workflow-controls-review87/native-WanVideoAnimateEmbeds.json').read_text("utf-8"))["WanVideoAnimateEmbeds"]["input"]["required"]
    assert native["pose_strength"][1]["step"] == 0.001
    assert native["face_strength"][1]["max"] == 10


@pytest.mark.parametrize("wid", sorted(POLICIES))
def test_new_fields_target_exact_reachable_inputs_in_published_graph(wid):
    import schema_adapters as runtime
    compiled = graph(wid)
    published = runtime.manifest(wid)
    reachable = runtime.prune(copy.deepcopy(compiled), published['outputs'])
    new_ids = {f['id'] for f in reviewed_video_controls(wid)}
    configuration = reviewed_video_config(wid, cfg(wid), compiled)
    for field in configuration['controls']:
        if field['id'] in new_ids:
            for target in field['targets']:
                assert target['node'] in reachable
                assert target['input'] in reachable[target['node']]['inputs']
                assert next(f for f in published['controls'] if f['id'] == field['id'])['targets'] == field['targets']
