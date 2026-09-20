#!/usr/bin/env python3
"""Generate SVG charts for the research write-up from verified source data.

Data sources (all read from this repo's predictions/ directory):
- grid-delta variant distribution: predictions/grid_delta_spearman.json
- all other figures: hard-coded from the archived records cited in the chapter
  (breakthrough commit 606117e; R10/R11 replay reports; roster version log).

Usage: python3 make_charts.py <repo_root> <output_dir> [private_repo_root]

<repo_root> is this repository (predictions/ is read from it); the
optional <private_repo_root> is the research archive whose
outputs/experiments/ holds the raw artifact JSONs not distributed
here (the two September-20 charts read from it; when omitted, both
default to <repo_root>).
"""
import json, sys
from pathlib import Path

FONT = "-apple-system,'PingFang SC','Microsoft YaHei','Segoe UI',sans-serif"
INK, MUT, RED, BLUE, GRID = '#1c1c1e', '#5f6368', '#d40000', '#1f5fa8', '#e4e4e7'

def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def open_svg(w, h, title):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
            f'<style>text{{font-family:{FONT};}}</style>',
            f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
            f'<text x="20" y="26" font-size="15" font-weight="700" fill="{INK}">{esc(title)}</text>']

def text(x, y, s, size: float = 12, fill=None, anchor='start', weight='400'):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill or INK}" text-anchor="{anchor}" font-weight="{weight}">{esc(s)}</text>'

def rect(x, y, w, h, fill, rx=0):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" rx="{rx}"/>'

def line(x1, y1, x2, y2, stroke=GRID, width: float = 1, dash=''):
    d = f' stroke-dasharray="{dash}"' if dash else ''
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{width}"{d}/>'

def write(path, parts):
    parts.append('</svg>')
    Path(path).write_text('\n'.join(parts), encoding='utf-8')
    print('wrote', path)

def hbar_chart(path, title, rows, xmin, xmax, hi_index, notes=None):
    """rows: list of (label, value). Horizontal bars; notes drawn below the bars."""
    notes = notes or []
    w, h = 640, 60 + len(rows) * 46 + 12 + len(notes) * 17 + 16
    p = open_svg(w, h, title)
    x0, x1 = 250, w - 90
    for i, (label, v) in enumerate(rows):
        y = 60 + i * 46
        frac = (v - xmin) / (xmax - xmin)
        bw = max(4, int(frac * (x1 - x0)))
        color = RED if i == hi_index else '#9aa4b2'
        p.append(text(x0 - 10, y + 15, label, 12.5, INK, 'end'))
        p.append(rect(x0, y, bw, 22, color, 3))
        p.append(text(x0 + bw + 8, y + 16, f'{v:.4f}', 12.5, color if i == hi_index else MUT, weight='600' if i == hi_index else '400'))
    for j, note in enumerate(notes):
        p.append(text(20, 60 + len(rows) * 46 + 6 + j * 17, note, 11.5, MUT))
    write(path, p)

def column_chart(path, title, labels, values, ymin, ymax, hi_indices, notes=None):
    w, h = 640, 360
    p = open_svg(w, h, title)
    x0, x1, y0, y1 = 70, w - 30, h - 60, 60
    # y gridlines: 4 lines
    for k in range(5):
        yy = y0 - (y0 - y1) * k / 4
        val = ymin + (ymax - ymin) * k / 4
        p.append(line(x0, yy, x1, yy, GRID))
        p.append(text(x0 - 8, yy + 4, f'{val:.2f}', 11, MUT, 'end'))
    n = len(labels)
    slot = (x1 - x0) / n
    bw = min(56, slot * 0.55)
    for i, (lab, v) in enumerate(zip(labels, values)):
        cx = x0 + slot * (i + 0.5)
        frac = (v - ymin) / (ymax - ymin)
        bh = max(2, int(frac * (y0 - y1)))
        color = RED if i in hi_indices else '#9aa4b2'
        p.append(rect(cx - bw / 2, y0 - bh, bw, bh, color, 3))
        p.append(text(cx, y0 - bh - 8, f'{v:.4f}', 11.5, color if i in hi_indices else MUT, 'middle', '600' if i in hi_indices else '400'))
        p.append(text(cx, y0 + 20, lab, 12, INK, 'middle'))
    if notes:
        for j, note in enumerate(notes):
            p.append(text(x0, y0 + 44 + j * 16, note, 11.5, MUT))
    write(path, p)

def slope_chart(path, title, series, ymin, ymax, notes=None):
    """series: list of (label, color, v_left, v_right)."""
    w, h = 640, 380
    p = open_svg(w, h, title)
    x_left, x_right, y0, y1 = 150, w - 170, h - 80, 70
    for k in range(5):
        yy = y0 - (y0 - y1) * k / 4
        val = ymin + (ymax - ymin) * k / 4
        p.append(line(x_left, yy, x_right, yy, GRID))
        p.append(text(x_left - 8, yy + 4, f'{val:.2f}', 11, MUT, 'end'))
    p.append(text(x_left, y1 - 22, 'R10 (Belgium)', 12.5, INK, 'middle', '600'))
    p.append(text(x_right, y1 - 22, 'R11 (Hungary)', 12.5, INK, 'middle', '600'))
    def ypos(v):
        return y0 - (v - ymin) / (ymax - ymin) * (y0 - y1)
    for label, color, vl, vr in series:
        p.append(line(x_left, ypos(vl), x_right, ypos(vr), color, 2.5))
        for (xx, v, _) in ((x_left, vl, 'end'), (x_right, vr, 'start')):
            p.append(f'<circle cx="{xx}" cy="{ypos(v):.1f}" r="4.5" fill="{color}"/>')
        p.append(text(x_left - 12, ypos(vl) - 8, f'{vl:.4f}', 12, color, 'end', '600'))
        p.append(text(x_right + 12, ypos(vr) - 8, f'{vr:.4f}', 12, color, 'start', '600'))
        p.append(text(x_left - 12, ypos(vl) + 12, label, 12, MUT, 'end'))
    if notes:
        for j, note in enumerate(notes):
            p.append(text(60, y0 + 40 + j * 17, note, 12, MUT))
    write(path, p)

def histogram(path, title, bins, ref_value, ref_label, notes=None):
    w, h = 640, 380
    p = open_svg(w, h, title)
    x0, x1, y0, y1 = 70, w - 30, h - 80, 60
    vmin, vmax = -0.40, 0.70
    slot = (x1 - x0) / ((vmax - vmin) / 0.025)
    maxc = max(c for _, c in bins)
    for k in range(5):
        yy = y0 - (y0 - y1) * k / 4
        p.append(line(x0, yy, x1, yy, GRID))
        p.append(text(x0 - 8, yy + 4, str(int(maxc * k / 4)), 11, MUT, 'end'))
    for v, c in bins:
        xx = x0 + (v - vmin) / (vmax - vmin) * (x1 - x0)
        bh = max(1, int(c / maxc * (y0 - y1)))
        p.append(rect(xx - slot / 2 + 1, y0 - bh, slot - 2, bh, '#9aa4b2', 2))
    for k in range(3):
        v = -0.25 + k * 0.25
        xx = x0 + (v - vmin) / (vmax - vmin) * (x1 - x0)
        p.append(text(xx, y0 + 20, f'{v:+.2f}', 11, MUT, 'middle'))
    xr = x0 + (ref_value - vmin) / (vmax - vmin) * (x1 - x0)
    p.append(line(xr, y1 - 10, xr, y0, RED, 1.5, '5,4'))
    p.append(text(xr - 6, y1 - 16, ref_label, 11.5, RED, 'end', '600'))
    if notes:
        for j, note in enumerate(notes):
            p.append(text(x0, y0 + 44 + j * 16, note, 11.5, MUT))
    write(path, p)

def line_chart(path, title, labels, series, ymin, ymax, vline=None):
    """series: list of (label, color, values)."""
    w, h = 700, 380
    p = open_svg(w, h, title)
    x0, x1, y0, y1 = 70, w - 150, h - 70, 70
    for k in range(5):
        yy = y0 - (y0 - y1) * k / 4
        val = ymin + (ymax - ymin) * k / 4
        p.append(line(x0, yy, x1, yy, GRID))
        p.append(text(x0 - 8, yy + 4, f'{val:.2f}', 11, MUT, 'end'))
    n = len(labels)
    def xpos(i):
        return x0 + (x1 - x0) * i / (n - 1)
    def ypos(v):
        return y0 - (v - ymin) / (ymax - ymin) * (y0 - y1)
    for i, lab in enumerate(labels):
        p.append(text(xpos(i), y0 + 20, lab, 11, MUT, 'middle'))
    if vline is not None:
        xv = xpos(vline)
        p.append(line(xv, y1 - 8, xv, y0, RED, 1.2, '5,4'))
        p.append(text(xv + 5, y1 - 12, 'weights frozen', 11, RED))
    for label, color, values in series:
        pts = ' '.join(f'{xpos(i):.1f},{ypos(v):.1f}' for i, v in enumerate(values))
        p.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        for i, v in enumerate(values):
            p.append(f'<circle cx="{xpos(i):.1f}" cy="{ypos(v):.1f}" r="3.5" fill="{color}"/>')
    for j, (label, color, _) in enumerate(series):
        ly = 60 + j * 20
        p.append(line(x1 + 14, ly - 4, x1 + 40, ly - 4, color, 3))
        p.append(text(x1 + 46, ly, label, 12, INK))
    write(path, p)


def box_stats(values):
    """Return (min, q1, median, q3, max) with linear interpolation on quartiles."""
    v = sorted(values)
    n = len(v)
    def q(p):
        if n == 1:
            return v[0]
        idx = (n - 1) * p
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        frac = idx - lo
        return v[lo] * (1 - frac) + v[hi] * frac
    return v[0], q(0.25), q(0.5), q(0.75), v[-1]


def box_plot(path, title, groups, ymin, ymax, notes=None, width=None):
    """groups: list of (label, values, color). Vertical box-whisker per group."""
    n = len(groups)
    w = width or max(420, 90 + n * 34 + 40)
    h = 380
    p = open_svg(w, h, title)
    x0, x1, y0, y1 = 70, w - 30, h - 90, 70
    for k in range(5):
        yy = y0 - (y0 - y1) * k / 4
        val = ymin + (ymax - ymin) * k / 4
        p.append(line(x0, yy, x1, yy, GRID))
        p.append(text(x0 - 8, yy + 4, f'{val:.2f}', 11, MUT, 'end'))
    def ypos(v):
        return y0 - (v - ymin) / (ymax - ymin) * (y0 - y1)
    slot = (x1 - x0) / n
    bw = min(20, slot * 0.6)
    for i, (label, values, color) in enumerate(groups):
        cx = x0 + slot * (i + 0.5)
        mn, q1, med, q3, mx = box_stats(values)
        p.append(line(cx, ypos(mx), cx, ypos(mn), color, 1.2))
        p.append(line(cx - bw / 3, ypos(mx), cx + bw / 3, ypos(mx), color, 1.2))
        p.append(line(cx - bw / 3, ypos(mn), cx + bw / 3, ypos(mn), color, 1.2))
        p.append(f'<rect x="{cx - bw / 2:.1f}" y="{ypos(q3):.1f}" width="{bw}" height="{max(1, ypos(q1) - ypos(q3)):.1f}" fill="none" stroke="{color}" stroke-width="1.4"/>')
        p.append(line(cx - bw / 2, ypos(med), cx + bw / 2, ypos(med), color, 2.4))
        rot = ' transform="rotate(-90 %.1f %.1f)"' % (cx, y0 + 14) if n > 8 else ''
        p.append(f'<text x="{cx:.1f}" y="{y0 + 18}" font-size="{10.5 if n > 8 else 12}" fill="{color}" text-anchor="{"middle" if n <= 8 else "end"}"{rot}>{esc(label)}</text>')
    if notes:
        for j, note in enumerate(notes):
            p.append(text(x0, y0 + 52 + j * 16, note, 11.5, MUT))
    write(path, p)


def vertical_bars(path, title, labels, values, highlight, ymin, ymax, notes=None, width=None):
    n = len(labels)
    w = width or max(420, 90 + n * 22 + 40)
    h = 380
    p = open_svg(w, h, title)
    x0, x1, y0, y1 = 70, w - 30, h - 90, 70
    for k in range(5):
        yy = y0 - (y0 - y1) * k / 4
        val = ymin + (ymax - ymin) * k / 4
        p.append(line(x0, yy, x1, yy, GRID))
        p.append(text(x0 - 8, yy + 4, f'{val:.2f}', 11, MUT, 'end'))
    slot = (x1 - x0) / n
    bw = min(24, slot * 0.62)
    for i, (lab, v) in enumerate(zip(labels, values)):
        cx = x0 + slot * (i + 0.5)
        frac = (v - ymin) / (ymax - ymin)
        bh = max(1, int(frac * (y0 - y1)))
        color = RED if i in highlight else '#9aa4b2'
        p.append(rect(cx - bw / 2, y0 - bh, bw, bh, color, 2))
        rot = ' transform="rotate(-90 %.1f %.1f)"' % (cx, y0 + 14) if n > 8 else ''
        p.append(f'<text x="{cx:.1f}" y="{y0 + 18}" font-size="{10.5 if n > 8 else 12}" fill="{color if i in highlight else INK}" text-anchor="{"middle" if n <= 8 else "end"}" font-weight="{"700" if i in highlight else "400"}"{rot}>{esc(lab)}</text>')
    if notes:
        for j, note in enumerate(notes):
            p.append(text(x0, y0 + 52 + j * 16, note, 11.5, MUT))
    write(path, p)



def nsw_space_guide(out):
    """NSW three-dimension guide: N base shapes x S rescalings x W windows."""
    n_groups = [
        ("raw", ["N0"], "raw delta"),
        ("position bands", ["N1a", "N1b", "N1c", "N1d", "N1e"], "2/4/6/8 bands"),
        ("curve fits", ["N2", "N2a", "N2b", "N2c", "N2d"], "poly / log / sqrt"),
        ("non-parametric", ["N3", "N4", "N5"], "iso / spline / kernel"),
        ("piecewise linear", ["N6", "N7"], "2 / 3 segments"),
        ("aggregations of the linear fit",
         ["N2f0", "N2f1", "N2f2", "N2f3", "N2f4", "N2f5", "N2f6", "N2f7", "N2f8", "N2f9"],
         "10 statistics - see 6.6"),
    ]
    w_names = ["Wexp", "W3", "W5", "W7"]
    s_names = ["S0 centering", "S1 z-score"]
    ox, oy = 130, 372
    ndx, ndy = 13.8, 4.5
    gap_units = 7.0 / 13.0
    wdx, wdy = 16.0, -16.0
    slab = 64
    n_x, cx = [], 0.0
    for gi, (_, nms, _) in enumerate(n_groups):
        if gi:
            cx += gap_units
        for nm in nms:
            n_x.append((nm, ox + cx * ndx, oy + cx * ndy))
            cx += 1
    g = open_svg(1120, 716, "NSW variant space: 26 base shapes x 2 rescalings x 4 windows = 208 combinations")
    # S slabs: two baseline strokes (S0 front, S1 lifted)
    for sk, sname in enumerate(s_names):
        zoff = -sk * slab
        col = GRID if sk == 0 else "#d4d7dd"
        g.append(line(ox - 16, oy + 16 + zoff, ox + 3 * wdx + 30, oy + 3 * wdy - 14 + zoff, col, 1))
        g.append(line(ox - 16, oy + 16 + zoff, ox - 16, oy - 2 + zoff, col, 1))
        g.append(text(ox - 22, oy + 8 + zoff, sname, 11, INK if sk == 0 else MUT, "end", "600" if sk == 0 else "400"))
    # S axis (vertical) with labels on its right
    g.append(line(ox - 16, oy + 16, ox - 16, 128, MUT, 1.4))
    g.append(text(ox - 10, 124, "S · rescaling", 12, INK, "start", "700"))
    g.append(text(ox - 10, 140, "what common scale does", 10.5, MUT))
    g.append(text(ox - 10, 153, "each value go on?", 10.5, MUT))
    # W axis (depth direction, upper right), arrow beyond the last slab corner
    wx_end = ox + 3 * wdx + 30
    wy_end = oy + 3 * wdy - 14
    g.append(line(wx_end - 6, wy_end + 6, wx_end + 26, wy_end - 46, MUT, 1.4))
    g.append(text(wx_end + 30, wy_end - 52, "W · window", 12, INK, "start", "700"))
    g.append(text(wx_end + 30, wy_end - 38, "how much history,", 10.5, MUT))
    g.append(text(wx_end + 30, wy_end - 25, "how fast it fades", 10.5, MUT))
    # W labels at the right end of each depth row
    last_x = n_x[-1][1]
    for j, wn in enumerate(w_names):
        g.append(text(last_x + j * wdx + 24, oy + j * wdy + 4 + (3 - j) * 0, wn, 10.5, MUT, "start", "600"))
    # 208 points: 26 N x 4 W, two S layers
    for sk in range(2):
        zoff = -sk * slab
        for j in range(4):
            for (nm, px, py) in n_x:
                col = "#7f8ea3" if sk == 0 else "#a9b4c4"
                g.append(f'<circle cx="{px + j * wdx:.1f}" cy="{py + j * wdy + zoff:.1f}" r="2.2" fill="{col}" fill-opacity="0.8"/>')
    # N group labels below their own group center
    cx = 0.0
    for gi, (gname, nms, gdesc) in enumerate(n_groups):
        if gi:
            cx += gap_units
        gx = ox + (cx + len(nms) / 2 - 0.5) * ndx
        gy = oy + (cx + len(nms) / 2) * ndy
        drop = 0 if gi % 2 == 0 else 42
        g.append(text(gx, gy + 44 + drop, gname, 10.5, INK, "middle", "600"))
        g.append(text(gx, gy + 57 + drop, gdesc, 9.2, MUT, "middle"))
        cx += len(nms)
    # incumbent: N2f6 (7th aggregation) x Wexp x S0, leader line to free space above the S1 slab
    fx, fy = n_x[22][1], n_x[22][2]
    g.append(line(fx, fy - 5, fx + 6, fy - slab - 62, RED, 1))
    g.append(f'<circle cx="{fx:.1f}" cy="{fy:.1f}" r="4.4" fill="{RED}"/>')
    g.append(text(fx - 12, fy - slab - 72, "incumbent source:", 11, RED, "end", "600"))
    g.append(text(fx - 12, fy - slab - 59, "N2f6 hit rate, Wexp, S0", 11, RED, "end", "600"))
    # N axis title, bottom-left
    g.append(text(ox, oy + 26 * ndy + 122, "N · base shape - how is each driver's recovery record summarized?", 12, INK, "start", "700"))
    for j, note in enumerate([
        "Read one small dot as one candidate feature: pick a summarization (N), a history window (W) and a rescaling (S).",
        "26 x 2 x 4 = 208 combinations; 204 produced usable values (four sparse columns). In the frozen formula the S pair",
        "scores identically (the formula standardizes its input anyway), so the space contains 104 distinct orderings."]):
        g.append(text(20, 634 + j * 16, note, 11.5, MUT))
    write(out / "nsw-space-guide.svg", g)


def main():
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    priv = Path(sys.argv[3]) if len(sys.argv) > 3 else root
    pred_dir = root / 'predictions'
    out.mkdir(parents=True, exist_ok=True)

    # 1. assembly ladder (roster version log)
    hbar_chart(out / 'assembly-ladder.svg', 'Qualifying line: four assembly iterations (R03–R09 window means)',
        [('Round 1 · cross-paradigm ensemble', 0.4795),
         ('Round 2 · slot assembly', 0.4903),
         ('Round 3 · robust', 0.4934),
         ('Round 3 · peak', 0.5039),
         ('Round 4 · robust (#31)', 0.5103),
         ('Round 4 · peak (#30)', 0.5173)],
        0.46, 0.53, 5)

    # 2. replay swap (R10/R11 reports)
    slope_chart(out / 'replay-swap.svg', 'A reversal across the two replays (single-event C0)',
        [('#23 Gaussian pairwise approx', BLUE, 0.4943, 0.2864),
         ('#31 Slot Ensemble · Robust', RED, 0.3183, 0.4765)],
        0.25, 0.55,
        notes=['R10: all 31 candidates ran; #23 first, #31 last.',
               'R11: #23 fell to 27th (0.2864), #31 rose to 2nd (0.4765).',
               'The same candidate went from last to second in two rounds; the other, from first to twenty-seventh.'])

    # 3. transform controls (606117e message, test window)
    column_chart(out / 'transform-controls.svg', 'Transform comparison experiment (R10–R11 test window)',
        ['Baseline', 'Centering', 'Log', 'Sqrt', 'Rank', 'Box-Cox', 'Standardize'],
        [0.5438, 0.5438, 0.5213, 0.5438, 0.5438, 0.5438, 0.5766],
        0.50, 0.58, {6},
        notes=['Baseline = no transform; centering, sqrt, rank and Box-Cox are flat against it.',
               'Log is worse (0.5213). Only standardization (red) brings a gain.'])

    # 4. race upgrade (8/02 performance table, test window)
    column_chart(out / 'race-upgrade.svg', 'Race model: three-step upgrade (R10–R11 test window)',
        ['Grid baseline', '+ standardized features', '+ back-of-grid interaction'],
        [0.5438, 0.5766, 0.5917],
        0.50, 0.60, {1, 2},
        notes=['Standardization: +6.04%; interaction: another +2.62%; total +8.81%.'])

    # 5. variant distribution (artifact, full 208 variants)
    data = json.load(open(pred_dir / 'experiments/grid_delta_spearman.json'))
    variants = [x for x in data if x['feature'] != 'grid_position']
    import collections
    bins = collections.Counter()
    none_count = 0
    for x in variants:
        if x['pooled_rho'] is None:
            none_count += 1
            continue
        bins[round(x['pooled_rho'] * 40) / 40] += 1
    histogram(out / 'variant-distribution.svg', 'Correlation of 208 grid-delta variants with race result',
        sorted(bins.items()), 0.6729, 'Reference (raw grid) 0.6729',
        notes=[f'Of 208 variants, {208 - none_count} produced a computable correlation ({none_count} did not).',
               'The distribution is bimodal: most variants sit in the negative range; one stronger cluster gathers near 0.63 — none beats the reference.'])

    # 6. race by round (predictions/race/predictions.json)
    race_doc = json.load(open(pred_dir / 'race/predictions.json'))
    labels_r = ['R%02d' % r for r in range(3, 15)]
    line_chart(out / 'race-by-round.svg',
        'Race model vs grid baseline: score by round (single-event C0)',
        labels_r,
        [('Grid baseline', '#9aa4b2',
          [race_doc['rounds'][str(r)]['race_grid_only']['c0'] for r in range(3, 15)]),
         ('Optimized model', RED,
          [race_doc['rounds'][str(r)]['race_optimized_606117e']['c0'] for r in range(3, 15)])],
        0.38, 0.72, vline=9)

    # 7. race version ladder (test window means; mid version has no per-round record)
    hbar_chart(out / 'race-version-ladder.svg', 'Race line: version iterations (R10–R11 test window means)',
        [('Grid baseline', 0.5438),
         ('+ standardized features', 0.5766),
         ('+ back-of-grid interaction (final)', 0.5917)],
        0.53, 0.60, 2,
        notes=['Change 1, baseline → standardized: form and racecraft become within-round standardized relative strengths (+6.04%);',
               'Change 2, standardized → final: adds a back-of-grid × constructor-strength interaction (+2.62%).',
               'Note: the middle standardized version reported only a mean, so it is absent from the box plot below.'])

    # 8. race version box (baseline vs final, all scored rounds from predictions/race)
    def span(model):
        return [e[model]['c0'] for e in race_doc['rounds'].values()
                if e.get(model) and e[model].get('status') == 'scored']
    box_plot(out / 'race-version-box.svg', 'Race: per-round distribution, baseline vs final (R03–R14 single-event)',
        [('Grid baseline', span('race_grid_only'), '#9aa4b2'),
         ('Final (frozen)', span('race_optimized_606117e'), RED)],
        0.35, 0.72,
        notes=['12 rounds each (R03–R14). Box = interquartile range, line = median, whiskers = extremes;',
               'the "+standardized" middle version left no per-round scores and cannot appear here.'])

    # 9. qualifying: 31 candidates bars + box (predictions/qualifying/predictions.json)
    qual = json.load(open(pred_dir / 'qualifying/predictions.json'))
    labels, means, boxes, hilite = [], [], [], set()
    for c in qual['candidates']:
        o = c['ordinal']
        labels.append(f'#{o}')
        means.append(c['combined_mean_r03_r14'])
        vals = [rd['c0'] for rd in c['rounds'].values() if rd['c0'] is not None]
        boxes.append(vals)
        if o in (30, 31):
            hilite.add(len(labels) - 1)
    vertical_bars(out / 'qualifying-bars.svg',
        'Qualifying line: combined means of 31 candidates (R03–R14, every candidate scored on every round)',
        labels, means, hilite, 0.36, 0.49,
        notes=['Sorted by combined mean; #30 and #31 (red) are the two final ensembles.',
               'All 372 candidate-round cells are scored under the seat-rotation policy (decision-log entry 12).'])
    groups = [(lab, vals, RED if i in hilite else '#9aa4b2') for i, (lab, vals) in enumerate(zip(labels, boxes))]
    box_plot(out / 'qualifying-box.svg', 'Qualifying line: single-event score distribution per candidate (R03–R14)',
        groups, -0.05, 0.72,
        notes=['31 candidates, sorted by combined mean; #30 and #31 (red) are the two final ensembles.',
               'Boxes use all twelve rounds; every candidate-round cell is scored.'],
        width=900)
    # 10. formula-slot audit scatter (private artifact nsw_scan.json)
    nsw = json.load(open(priv / 'outputs/experiments/race/nsw_racecraft_scan_035117f2/nsw_scan.json'))
    pts = [(v['delta_full_vs_base'], v['delta_pros_vs_base'])
           for k, v in nsw['scan'].items() if k != 'official_baseline']
    scatter_plot(out / 'nsw-formula-slot.svg',
        'Formula-slot audit: 204 racecraft variants vs the incumbent (R03-R14 deltas)',
        pts, (-0.09, 0.012), (-0.11, 0.03),
        [('x', 0.0, MUT, '6,4', 'incumbent level (deltas measured against it)'),
         ('y', 0.010, RED, '', 'prospective gate +0.010')],
        [(-0.0281, 0.0183, 'N2f2_Wexp: the only gate pass')],
        'delta vs incumbent, full window R03-R14',
        'delta vs incumbent, prospective R10-R14',
        notes=['Every variant sits left of the incumbent level: none beats it over the full window.',
               'The one variant over the prospective gate (red) loses 0.028 on the full window.',
               'The succession rule requires BOTH - the top-right region is empty.',
               'Note: S0/S1 rescaling pairs score identically (the formula standardizes anyway), so points overlap in pairs - 204 combinations, 104 distinct orderings.'])

    # 11. practice-signal correlation by round (private artifact fp_corr_stats_A.json)
    fpa = json.load(open(priv / 'outputs/experiments/whatif_upgrade/fp_signal_corr_d739e6e0/fp_corr_stats_A.json'))
    rds = sorted(fpa['rounds'].items(), key=lambda kv: int(kv[0]))
    labels_fp = ['R%02d' % int(k) for k, _ in rds]
    rhos = [v['spearman_rho'] for _, v in rds]
    lo = min(range(len(rhos)), key=lambda i: rhos[i])
    vertical_bars(out / 'fp-corr-by-round.svg',
        'Practice rank vs same-round qualifying: Spearman rho by round (pooled 0.886, 14/14 positive)',
        labels_fp, rhos, {lo}, 0.0, 1.0,
        notes=['Every round positive; weakest R04 Miami 0.748, strongest R08 Austria 0.967 - practice',
               'reliability varies by circuit type (an archived mechanism finding).',
               'Red = the weakest round. Signal is real - but redundant with recent form (0.876) and adds no model gain.'])

    # 12. qualifying heatmap: 31 candidates x 12 rounds (predictions/qualifying/predictions.json)
    hm_rows, hm_vals, hm_hi = [], [], set()
    for i, c in enumerate(qual['candidates']):
        o = c['ordinal']
        hm_rows.append(f'#{o}')
        hm_vals.append([rd['c0'] for rd in c['rounds'].values()])
        if o in (30, 31):
            hm_hi.add(i)
    n_colds = len(hm_vals[0])
    med = [sorted(r[j] for r in hm_vals)[len(hm_vals) // 2] for j in range(n_colds)]
    heatmap(out / 'qualifying-heatmap.svg',
        'Qualifying line: single-event C0, 31 candidates x 12 rounds (sorted by combined mean)',
        hm_rows, labels_r, hm_vals, 0.0, 0.65, hm_hi,
        notes=['Darker blue = higher single-round score; red tint = negative (penalised into it; none in the official caliber).',
               'The bottom reference row is the field median per round: R13 is the darkest column for everyone (median 0.34),',
               'R09 the brightest (0.53) - the heavy-shuffle reading of 7.2/7.3, visible for the whole field. #30/#31 in red, the two ensembles.'],
        col_ref=med)
    nsw_space_guide(out)

def scatter_plot(path, title, points, xrange, yrange, ref_lines, hi_points, xlabel, ylabel, notes=None):
    """points: list of (x, y). ref_lines: list of (axis, value, color, dash, label).
    hi_points: list of (x, y, label). notes drawn below."""
    notes = notes or []
    w, h = 680, 540
    p = open_svg(w, h, title)
    x0, x1, y0, y1 = 78, w - 30, h - 108, 64
    def px(v):
        return x0 + (v - xrange[0]) / (xrange[1] - xrange[0]) * (x1 - x0)
    def py(v):
        return y0 - (v - yrange[0]) / (yrange[1] - yrange[0]) * (y0 - y1)
    for gv in [xrange[0] + k * 0.02 for k in range(6)]:
        p.append(line(px(gv), y1, px(gv), y0, GRID))
        p.append(text(px(gv), y0 + 16, f'{gv:+.2f}', 10.5, MUT, 'middle'))
    for gv in [yrange[0] + k * 0.02 for k in range(7)]:
        p.append(line(x0, py(gv), x1, py(gv), GRID))
        p.append(text(x0 - 8, py(gv) + 4, f'{gv:+.2f}', 10.5, MUT, 'end'))
    for axis, val, color, dash, lab in ref_lines:
        if axis == 'x':
            p.append(line(px(val), y1, px(val), y0, color, 1.6, dash))
            p.append(text(px(val) + 5, y1 + 12, lab, 10.5, color))
        else:
            p.append(line(x0, py(val), x1, py(val), color, 1.6, dash))
            p.append(text(x1 - 6, py(val) - 6, lab, 10.5, color, 'end'))
    for x, y in points:
        p.append(f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="3" fill="#9aa4b2" fill-opacity="0.45"/>')
    for x, y, lab in hi_points:
        p.append(f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="4.5" fill="{RED}"/>')
        p.append(text(px(x) + 8, py(y) - 7, lab, 11, RED, weight='600'))
    p.append(text((x0 + x1) / 2, y0 + 32, xlabel, 12, INK, 'middle'))
    p.append(f'<text x="24" y="{(y0 + y1) / 2}" font-size="12" fill="{INK}" text-anchor="middle" transform="rotate(-90 24 {(y0 + y1) / 2})">{esc(ylabel)}</text>')
    for j, note in enumerate(notes):
        p.append(text(x0, y0 + 50 + j * 16, note, 11.5, MUT))
    write(path, p)


def _heat_color(v, vmin, vmax):
    """Sequential blue for v >= 0; a distinct red tint for negative cells."""
    if v < 0:
        k = min(1.0, abs(v) / 0.08)
        return '#%02x%02x%02x' % (int(0xf3 - 0x10 * k), int(0xd0 - 0x40 * k), int(0xd3 - 0x40 * k))
    k = max(0.0, min(1.0, (v - vmin) / (vmax - vmin)))
    lo, hi = (0xf8, 0xfa, 0xfd), (0x1f, 0x5f, 0xa8)
    return '#%02x%02x%02x' % tuple(int(lo[i] + (hi[i] - lo[i]) * k) for i in range(3))


def heatmap(path, title, row_labels, col_labels, values, vmin, vmax, hi_rows, notes=None, col_ref=None):
    """values: rows x cols numbers. col_ref: optional per-column reference row (median)."""
    notes = notes or []
    n_r, n_c = len(row_labels), len(col_labels)
    cell, ch = 34, 15
    w = 120 + n_c * cell + 40
    h = 70 + n_r * ch + (26 if col_ref else 0) + 66 + len(notes) * 16
    p = open_svg(w, h, title)
    x0, y0 = 120, 64
    for j, cl in enumerate(col_labels):
        p.append(text(x0 + j * cell + cell / 2, y0 - 8, cl, 10.5, INK, 'middle'))
    for i, rl in enumerate(row_labels):
        yy = y0 + i * ch
        color = RED if i in hi_rows else INK
        weight = '700' if i in hi_rows else '400'
        p.append(text(x0 - 8, yy + ch * 0.75, rl, 10.5, color, 'end', weight))
        for j, v in enumerate(values[i]):
            p.append(rect(x0 + j * cell, yy, cell - 1.5, ch - 1.5, _heat_color(v, vmin, vmax)))
    if col_ref:
        yy = y0 + n_r * ch + 8
        p.append(text(x0 - 8, yy + ch * 0.75, 'field median', 10, MUT, 'end'))
        for j, v in enumerate(col_ref):
            p.append(rect(x0 + j * cell, yy, cell - 1.5, ch - 1.5, _heat_color(v, vmin, vmax)))
            p.append(text(x0 + j * cell + cell / 2, yy + ch * 0.75, f'{v:.2f}', 8.5, INK if v < 0.35 else '#ffffff', 'middle'))
    # legend
    ly = y0 + n_r * ch + (34 if col_ref else 8)
    for k in range(24):
        v = vmin + (vmax - vmin) * k / 23
        p.append(rect(x0 + k * 14, ly, 14, 10, _heat_color(v, vmin, vmax)))
    p.append(text(x0 + 24 * 14 + 8, ly + 9, f'{vmin:.2f}', 10, MUT))
    p.append(text(x0 - 6, ly + 9, f'{vmax:.2f}', 10, MUT, 'end'))
    p.append(rect(x0 + 24 * 14 + 70, ly, 14, 10, _heat_color(-0.04, vmin, vmax)))
    p.append(text(x0 + 24 * 14 + 88, ly + 9, 'negative (penalised)', 10, MUT))
    for j, note in enumerate(notes):
        p.append(text(x0, ly + 28 + j * 16, note, 11.5, MUT))
    write(path, p)


if __name__ == '__main__':
    main()
