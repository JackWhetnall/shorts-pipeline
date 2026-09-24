"""
Animated scenes: the prop library's clean-up, the page the renderer
builds, and (slow) the real engine in headless Chrome.

The slow tests drive the installed Chrome, so they skip themselves on a
machine without it rather than failing the checkout.
"""

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from core.errors import PipelineError
from pipeline.scenes import props, render

EXAMPLES = Path(render.HERE) / "examples"


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _prop_with_artifacts() -> bytes:
    """An object in the middle, faint haze everywhere, and a hairline
    frame round the canvas edge: what the image model sometimes returns."""
    image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 10))          # stray alpha
    for x in range(1024):                                           # the frame
        image.putpixel((x, 0), (30, 30, 50, 80))
        image.putpixel((x, 1023), (30, 30, 50, 80))
    for y in range(1024):
        image.putpixel((0, y), (30, 30, 50, 80))
        image.putpixel((1023, y), (30, 30, 50, 80))
    image.paste(Image.new("RGBA", (400, 300), (255, 107, 74, 255)), (300, 350))
    return _png(image)


# --- the prop library -----------------------------------------------------------

def test_clean_removes_the_edge_frame_and_haze_and_trims_to_the_object():
    # Regression: a hairline frame at alpha ~80 survived the alpha floor,
    # kept the trim box at the full canvas, and showed as a faint box
    # round the piggy bank in the render.
    cleaned = Image.open(io.BytesIO(props.clean(_prop_with_artifacts())))
    alpha = cleaned.getchannel("A")
    # Trimmed to the 400x300 object plus padding, not the 1024 canvas.
    assert cleaned.size == (400 + 16, 300 + 16)
    assert alpha.getbbox() == (8, 8, 408, 308)
    # The padding round it is fully transparent: no haze.
    assert max(alpha.crop((0, 0, cleaned.width, 8)).getdata()) == 0


def test_clean_downsizes_large_props():
    image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    image.paste(Image.new("RGBA", (1000, 1000), (255, 0, 0, 255)), (12, 12))
    cleaned = Image.open(io.BytesIO(props.clean(_png(image))))
    assert max(cleaned.size) == props.MAX_SIDE


def test_clean_survives_an_empty_or_tiny_image():
    props.clean(_png(Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))))
    props.clean(_png(Image.new("RGBA", (6, 6), (255, 0, 0, 255))))


def test_get_uses_the_library_copy_without_generating(tmp_path, monkeypatch):
    (tmp_path / "piggy_bank.png").write_bytes(b"already drawn")
    monkeypatch.setattr(props, "_generate", lambda prompt: pytest.fail("generated again"))
    assert props.get(tmp_path, "Piggy bank", "flat") == tmp_path / "piggy_bank.png"


def test_get_generates_cleans_and_saves_a_new_prop(tmp_path, monkeypatch):
    prompts = []
    monkeypatch.setattr(props, "_generate", lambda prompt: prompts.append(prompt) or _prop_with_artifacts())
    path = props.get(tmp_path / "lib", "gold coin", "flat vector", detail="plain face")
    assert path.name == "gold_coin.png"
    assert Image.open(path).size == (416, 316)             # cleaned on the way in
    assert "gold coin, plain face" in prompts[0] and "flat vector" in prompts[0]
    assert "transparent background" in prompts[0]


def test_prop_names_become_safe_file_names():
    assert props.slug("Gold coin (UK)") == "gold_coin_uk"
    assert props.slug("../../etc") == "etc"
    assert props.slug("") == "prop"


# --- the page ---------------------------------------------------------------------

def test_page_is_self_contained_and_a_label_cannot_end_the_script(tmp_path):
    asset = tmp_path / "coin.png"
    asset.write_bytes(_png(Image.new("RGBA", (4, 4), (255, 0, 0, 255))))
    scene = {"duration": 1, "elements": [
        {"id": "t", "type": "label", "text": "</script><script>alert(1)</script>", "x": 1, "y": 1}],
        "actions": []}
    html = render.build_html(scene, render.load_style("clean_flat"), {"coin": asset})
    assert html.count("</script>") == 2                     # only the two real ones
    assert "data:image/png;base64," in html
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")


def test_unknown_style_is_a_readable_error():
    with pytest.raises(PipelineError) as err:
        render.load_style("no_such_style")
    assert "no_such_style" in err.value.user_message


def test_example_scenes_only_use_what_the_engine_knows():
    elements = {"shape", "label", "prop", "counter", "chart"}
    actions = {"appear", "draw", "write", "count", "move", "highlight", "wiggle", "stack", "exit"}
    for path in EXAMPLES.glob("*.json"):
        scene = json.loads(path.read_text(encoding="utf-8"))
        ids = {e["id"] for e in scene["elements"]}
        assert {e["type"] for e in scene["elements"]} <= elements, path.name
        for a in scene["actions"]:
            assert a["do"] in actions and a["target"] in ids, (path.name, a)
            assert a["at"] + a.get("dur", 0) <= scene["duration"], (path.name, a)


# --- the engine, in real Chrome (slow) -------------------------------------------

def _example(name):
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def _assets(scene, tmp_path):
    """Placeholder art: the engine's behaviour doesn't depend on the drawing."""
    out = {}
    for key in scene.get("props", {}):
        path = tmp_path / f"{key}.png"
        path.write_bytes(_png(Image.new("RGBA", (200, 200), (255, 182, 39, 255))))
        out[key] = path
    return out


def _open(scene, assets):
    try:
        return render._Page(scene, render.load_style("clean_flat"), assets).__enter__()
    except PipelineError as exc:
        if "Chrome" in exc.user_message:
            pytest.skip("Chrome isn't installed")
        raise


def _box(page, element_id):
    return page.page.evaluate(
        "id => { const r = document.querySelector(`[data-id='${id}']`).getBoundingClientRect();"
        " return [r.left, r.top, r.right, r.bottom]; }", element_id)


@pytest.mark.slow
def test_labels_land_on_the_star_points_they_name(tmp_path):
    scene = _example("pentagram")
    page = _open(scene, {})
    try:
        page.frame(scene["duration"])
        cx, cy, r = 540, 790, 330
        spirit = _box(page, "spirit")                      # vertex 0: the top point
        assert spirit[3] < cy - r + 10 and spirit[0] < cx < spirit[2]
        # Vertices run clockwise from the top: 1 upper right, 2 lower right,
        # 3 lower left, 4 upper left.
        water, fire, earth, air = (_box(page, k) for k in ("water", "fire", "earth", "air"))
        assert water[0] > cx and fire[0] > cx and earth[2] < cx and air[2] < cx
        assert fire[1] > cy and earth[1] > cy and water[3] < cy and air[3] < cy
    finally:
        page.__exit__(None, None, None)


@pytest.mark.slow
def test_a_stack_template_is_never_drawn_and_the_counter_ends_on_its_value(tmp_path):
    scene = _example("compound_interest")
    page = _open(scene, _assets(scene, tmp_path))
    try:
        page.frame(scene["duration"])
        assert page.page.evaluate(
            "document.querySelector(\"[data-id='coin']\").getAttribute('opacity')") == "0"
        text = page.page.evaluate("document.querySelector(\"[data-id='counter']\").textContent")
        assert "4,322" in text
    finally:
        page.__exit__(None, None, None)


@pytest.mark.slow
def test_render_encodes_a_video_of_the_scene_length(tmp_path):
    import subprocess

    import imageio_ffmpeg

    scene = dict(_example("pentagram"), duration=1.0)
    scene["actions"] = [a for a in scene["actions"] if a["at"] < 1.0]
    try:
        out = render.render(scene, render.load_style("clean_flat"), {}, tmp_path / "s.mp4", fps=10)
    except PipelineError as exc:
        if "Chrome" in exc.user_message:
            pytest.skip("Chrome isn't installed")
        raise
    probe = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(out)],
                           capture_output=True, text=True).stderr
    assert "1080x1920" in probe and "Duration: 00:00:01.00" in probe
