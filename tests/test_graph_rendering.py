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


def run_graph_script(code):
    result = subprocess.run(
        [NODE], input=HELPERS + RENDERER + code, text=True,
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
