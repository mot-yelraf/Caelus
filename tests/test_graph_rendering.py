"""Exercise the canvas renderer and station-local tick labels in JavaScript."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is needed for canvas renderer tests")
SCRIPT = (Path(__file__).resolve().parents[1] / "static/dashboard.js").read_text()
HELPERS = SCRIPT[SCRIPT.index("  function metricDate("):SCRIPT.index("  function metricValue(")]
RENDERER = SCRIPT[SCRIPT.index("  function fullGraphValue("):SCRIPT.index("  async function renderSelectedFullGraph(")]
ZONES = SCRIPT[SCRIPT.index("  function gaugeConfig("):SCRIPT.index("  function drawMetricGauge(")]


def run_graph_script(code):
    result = subprocess.run(
        [NODE], input=HELPERS + RENDERER + ZONES + code, text=True,
        capture_output=True, check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("metric_count, expected_lines", [(1, 5), (2, 0), (4, 0)])
def test_horizontal_grid_only_with_one_metric(metric_count, expected_lines):
    result = run_graph_script("""
const window = {devicePixelRatio: 1};
const graphRangeLabels = new Map();
let path = [];
const strokes = [];
const labels = [];
const context = new Proxy({
  beginPath: () => { path = []; },
  moveTo: (x, y) => path.push([x, y]),
  lineTo: (x, y) => path.push([x, y]),
  stroke: () => strokes.push(path.slice()),
  fillText: (text) => labels.push(text),
  measureText: () => ({width: 100}),
}, {get: (target, key) => target[key] ?? (() => {})});
const canvas = {clientWidth: 1200, clientHeight: 650,
  getContext: () => context, setAttribute: () => {}};
const metric = {label: 'Temperature', decimals: 1, unit: '°F', current: 70,
  series: [{timestamp: '2026-09-09T06:00:00Z', value: 60},
           {timestamp: '2026-09-10T06:00:00Z', value: 70}]};
drawFullScreenGraph(canvas, Array.from({length: METRIC_COUNT}, () => metric),
  {hours: 24, generated_at: '2026-09-10T06:00:00Z', timezone: 'America/Denver'});
const horizontal = strokes.filter(p => p.length === 2 && p[0][1] === p[1][1]
  && p[1][0] - p[0][0] > 100);
console.log(JSON.stringify({gridLines: horizontal.length, labels}));
""".replace("METRIC_COUNT", str(metric_count)))
    assert result["gridLines"] == expected_lines
    assert "09Sep" in result["labels"]
    assert "10Sep" in result["labels"]


@pytest.mark.parametrize("time, timezone, hours, expected", [
    ("2026-09-09T06:00:00Z", "America/Denver", 24, "09Sep"),
    ("2026-01-01T07:00:00Z", "America/Denver", 6, "01Jan"),
    ("2026-09-08T18:30:00Z", "Asia/Kolkata", 12, "09Sep"),
    ("2026-09-09T06:45:00Z", "America/Denver", 24, "09Sep"),
])
def test_midnight_tick_uses_station_date(time, timezone, hours, expected):
    payload = json.dumps({"hours": hours, "timezone": timezone})
    assert run_graph_script(
        f"console.log(JSON.stringify(fullGraphTimeLabel({json.dumps(time)}, {payload})));"
    ) == expected


def test_short_range_retains_minutes_after_midnight_and_noon_is_not_a_date():
    result = run_graph_script("""
console.log(JSON.stringify([
 fullGraphTimeLabel('2026-09-09T06:30:00Z', {hours: 6, timezone: 'America/Denver'}),
 fullGraphTimeLabel('2026-09-09T18:00:00Z', {hours: 24, timezone: 'America/Denver'}),
]));
""")
    assert ":30" in result[0]
    assert "Sep" not in result[0]
    assert "Sep" not in result[1]


@pytest.mark.parametrize("start, end, timezone, expected", [
    ("2026-09-09T12:47:00Z", "2026-09-10T12:47:00Z", "America/Denver",
     ["2026-09-10T06:00:00.000Z"]),
    ("2026-09-09T05:47:00Z", "2026-09-09T06:47:00Z", "America/Denver",
     ["2026-09-09T06:00:00.000Z"]),
    ("2026-03-08T07:00:00Z", "2026-03-10T06:00:00Z", "America/Denver",
     ["2026-03-08T07:00:00.000Z", "2026-03-09T06:00:00.000Z", "2026-03-10T06:00:00.000Z"]),
    ("2026-11-01T06:00:00Z", "2026-11-03T07:00:00Z", "America/Denver",
     ["2026-11-01T06:00:00.000Z", "2026-11-02T07:00:00.000Z", "2026-11-03T07:00:00.000Z"]),
    ("2026-09-09T17:47:00Z", "2026-09-09T19:47:00Z", "Asia/Kolkata",
     ["2026-09-09T18:30:00.000Z"]),
])
def test_day_ticks_include_exact_local_boundaries(start, end, timezone, expected):
    result = run_graph_script(f"""
console.log(JSON.stringify(fullGraphDayTicks(Date.parse({json.dumps(start)}),
 Date.parse({json.dumps(end)}), {json.dumps(timezone)}).map(t => new Date(t).toISOString())));
""")
    assert result == expected


def test_long_ranges_keep_every_day_boundary_and_ddmmm_label():
    result = run_graph_script("""
const ticks = fullGraphDayTicks(Date.parse('2026-09-01T12:47:00Z'),
 Date.parse('2026-09-30T12:47:00Z'), 'America/Denver');
console.log(JSON.stringify(ticks.map(t => fullGraphTimeLabel(t,
 {hours: 696, timezone: 'America/Denver'}, true))));
""")
    assert result == [f"{day:02d}Sep" for day in range(2, 31)]


@pytest.mark.parametrize("key, metric_unit, imperial_unit, factor, offset", [
    ("temperature", "°C", "°F", 1.8, 32),
    ("indoor_temperature", "°C", "°F", 1.8, 32),
    ("dew_point", "°C", "°F", 1.8, 32),
    ("pressure", "hPa", "inHg", 1 / 33.8638866667, 0),
    ("absolute_pressure", "hPa", "inHg", 1 / 33.8638866667, 0),
    ("wind_speed", "mph", "km/h", 1.609344, 0),
    ("rain_total", "mm", "in", 1 / 25.4, 0),
])
def test_zone_thresholds_represent_the_same_values_after_unit_conversion(
    key, metric_unit, imperial_unit, factor, offset,
):
    configs = run_graph_script(f"""
console.log(JSON.stringify({json.dumps([metric_unit, imperial_unit])}.map(unit =>
  gaugeConfig({{key: {json.dumps(key)}, unit, series: []}}))));
""")
    original, converted = configs
    assert converted[0] == pytest.approx(original[0] * factor + offset)
    assert converted[1] == pytest.approx(original[1] * factor + offset)
    assert converted[2] == original[2]
    assert converted[3] == pytest.approx(original[3])


@pytest.mark.parametrize("key", ["humidity", "indoor_humidity"])
def test_humidity_uses_sensorius_thresholds_instead_of_equal_slices(key):
    config = run_graph_script(f"console.log(JSON.stringify(gaugeConfig({{key: '{key}', unit: '%'}})));")
    assert config == [0, 100, ["#bf9000", "#ffcc00", "#add8e6", "#66b2ff", "#0033cc"],
                      [0, 0.2, 0.3, 0.7, 0.8, 1]]


def test_vpd_uses_sensorius_kpa_zones_for_graphs_and_gauges():
    config = run_graph_script("console.log(JSON.stringify(gaugeConfig({key: 'vpd', unit: 'kPa'})));")
    assert config[:3] == [0, 5, ["#0033cc", "#66cc66", "#03a603", "#3e803e", "#bf9000"]]
    assert config[3] == pytest.approx([0, 0.08, 0.16, 0.24, 0.32, 1])


@pytest.mark.parametrize("low, high, expected_colors", [
    (5, 35, ["#3399ff", "#66cc66", "#ffcc00"]),
    (18, 25, ["#66cc66"]),
    (-40, -25, ["#0000ff"]),
    (65, 80, ["#ff0000"]),
])
def test_background_bands_cover_plot_and_clip_to_visible_value_range(low, high, expected_colors):
    result = run_graph_script(f"""
const rectangles = [];
const context = {{fillRect(x, y, width, height) {{
  rectangles.push({{color: this.fillStyle, x, y, width, height}});
}}}};
drawMetricZones(context, {{key: 'temperature', unit: '°C'}}, {low}, {high}, 50, 10, 350, 210);
console.log(JSON.stringify(rectangles));
""")
    assert [rectangle["color"] for rectangle in result] == expected_colors
    assert sum(rectangle["height"] for rectangle in result) == pytest.approx(200)
    for rectangle in result:
        assert rectangle["x"] == 50
        assert rectangle["width"] == 300
        assert rectangle["y"] >= 10 - 1e-8
        assert rectangle["y"] + rectangle["height"] <= 210 + 1e-8


def test_card_graph_renders_white_trace_and_average_over_zone_background():
    card_renderer = SCRIPT[SCRIPT.index("  function drawMetricGraph("):SCRIPT.index("  const windDirections =")]
    result = run_graph_script(card_renderer + """
const window = {devicePixelRatio: 1};
const document = {documentElement: {}};
const getComputedStyle = () => ({getPropertyValue: () => ''});
const metricValue = value => String(value);
const strokes = [];
const fills = [];
const context = new Proxy({
  stroke() { strokes.push({color: this.strokeStyle, width: this.lineWidth}); },
  fillRect() { fills.push(this.fillStyle); },
  measureText: () => ({width: 40}),
}, {get: (target, key) => target[key] ?? (() => {})});
const canvas = {clientWidth: 400, getContext: () => context, closest: () => null};
drawMetricGraph(canvas, {key: 'temperature', unit: '°C', decimals: 1,
  series: [{timestamp: '2026-10-19T06:00:00Z', value: 20},
           {timestamp: '2026-10-19T12:00:00Z', value: 25}]},
  '2026-10-19T12:00:00Z', 'America/Denver');
console.log(JSON.stringify({strokes, fills}));
""")
    assert result["fills"][0] == "#66cc66"
    assert result["strokes"][-1] == {"color": "#ffffff", "width": 2.25}
    assert result["strokes"][-2]["color"] == "#ffffff"


@pytest.mark.parametrize("current, expected_needles", [(None, 0), (0, 1)])
def test_gauge_keeps_missing_reading_distinct_from_zero(current, expected_needles):
    gauge_renderer = SCRIPT[SCRIPT.index("  function drawMetricGauge("):SCRIPT.index("  function drawCompassGauge(")]
    result = run_graph_script(gauge_renderer + """
const window = {devicePixelRatio: 1};
const document = {documentElement: {}};
const getComputedStyle = () => ({getPropertyValue: () => ''});
const labels = [];
const metricValue = value => Number.isFinite(value) ? String(value) : 'N/A';
let needles = 0;
const context = new Proxy({
  closePath() { needles += 1; },
  fillText(text) { labels.push(String(text)); },
}, {get: (target, key) => target[key] ?? (() => {})});
const canvas = {clientWidth: 400, getContext: () => context, closest: () => null};
drawMetricGauge(canvas, {key: 'temperature', unit: '°C', current: CURRENT});
console.log(JSON.stringify({needles, label: labels[labels.length - 1]}));
""".replace("CURRENT", json.dumps(current)))
    assert result["needles"] == expected_needles
    assert result["label"] == ("N/A" if current is None else "0")
