#!/usr/bin/env python3
"""Generate SVG charts for the research write-up from verified source data.

Data sources (all read from this repo's predictions/ directory):
- grid-delta variant distribution: predictions/grid_delta_spearman.json
- all other figures: hard-coded from the archived records cited in the chapter
  (breakthrough commit 606117e; R10/R11 replay reports; roster version log).

Usage: python3 make_charts.py <private_repo_root> <output_dir>
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


def main():
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
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
        means.append(c['combined_mean_r03_r12'])
        vals = [rd['c0'] for rd in c['rounds'].values() if rd['c0'] is not None]
        boxes.append(vals)
        if o in (30, 31):
            hilite.add(len(labels) - 1)
    vertical_bars(out / 'qualifying-bars.svg',
        'Qualifying line: combined means of 31 candidates (R03–R12; R13/R14 increments in the box plot)',
        labels, means, hilite, 0.38, 0.53,
        notes=['Sorted by combined mean; #30 and #31 (red) are the two final ensembles.',
               'For the nine-round candidates (#10–#13, #30, #31), R12 was unscoreable due to the mid-season line-up change.'])
    groups = [(lab, vals, RED if i in hilite else '#9aa4b2') for i, (lab, vals) in enumerate(zip(labels, boxes))]
    box_plot(out / 'qualifying-box.svg', 'Qualifying line: single-event score distribution per candidate (combined rounds + R13/R14 increments)',
        groups, -0.05, 0.72,
        notes=['31 candidates, sorted by combined mean; #30 and #31 (red) are the two final ensembles.',
               'Boxes use every scoreable round (six candidates have R03–R11, the rest ten rounds).'],
        width=900)

if __name__ == '__main__':
    main()
