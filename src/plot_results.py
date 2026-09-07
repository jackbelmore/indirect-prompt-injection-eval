"""
Figure generator for the Results chapter.

Reads the same five result files the chapter's tables are computed from and writes ten PDF
figures into the dissertation's figures directory. Wilson confidence intervals come from
statistics_analyzer so the error bars cannot disagree with the intervals quoted in the text.

Run it from anywhere; every path is resolved from this file's location:

    python3 src/plot_results.py [--out-dir DIR]

In the shipped harness, where there is no dissertation alongside it, the figures go to
pipeline/figures/ instead. --out-dir overrides both.

Every percentage the script plots is also printed to stdout, so the figures can be checked
against the tables in chapters/results.tex without opening the PDFs.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch

sys.path.insert(0, str(Path(__file__).parent))
from paths import ROOT
from statistics_analyzer import calculate_confidence_interval, run_fishers_exact_test

# The five completed runs. The early pilots and abandoned-model runs (dolphin-phi, gemma, phi3,
# a short qwen2.5:1.5b, the first merged files) sit in results/archive/ and feed nothing here.
RUNS = {
    "qwen2.5:7b": "results/audit_results_qwen25_fixed.jsonl",
    "qwen3:30b-a3b": "results/audit_results_qwen3_30b_moe.jsonl",
    "qwen3:8b": "results/qwen3_8b_fixed_pipeline.jsonl",
    "llama3.1:8b": "results/audit_results_llama_baseline.jsonl",
    "qwen2.5:1.5b": "results/audit_results_qwen15b_fixed.jsonl",
}

# A trial counts as an exploit only when the tool log records an unauthorised call.
EXPLOITED = {"exploited_command_execution", "exploited_data_exfil"}

# The figures belong to the dissertation, which sits one level above the pipeline. When the
# harness ships on its own that directory does not exist, so they go to pipeline/figures/.
_LATEX_FIGURES = ROOT.parent / "docs" / "latex" / "figures"
OUT_DIR = _LATEX_FIGURES if _LATEX_FIGURES.parent.is_dir() else ROOT / "figures"

# Colour does one job per figure and the same job the same way every time.
#
# Model identity is a category, so each model keeps one hue everywhere it appears and the reader
# learns the mapping once. The five hues below are checked for colour-vision separation as a set
# against a white page, worst adjacent pair 9.1 under simulated protanopia and 19.6 under normal
# vision. Three of them fall below a 3:1 contrast ratio on white, which is why every bar in those
# figures carries its value printed beside it.
MODEL_COLOUR = {
    "qwen2.5:7b": "#2a78d6",     # blue
    "qwen3:8b": "#eb6834",       # orange
    "qwen3:30b-a3b": "#1baf7a",  # aqua
    "llama3.1:8b": "#eda100",    # yellow
    "qwen2.5:1.5b": "#e87ba4",   # magenta
}

# The reasoning toggle is two states rather than more-or-less of one thing, so it takes two
# separate hues. Landing two obviously different colours at the same height is the point of that
# figure: the reasoning mode does not move the rate and the system prompt does.
THINK_OFF = "#2a78d6"
THINK_ON = "#eb6834"

# The outcome taxonomy is not a set of unrelated categories. It runs from worst to best, so it
# takes a diverging scale: a red arm for the trials where the attack did something, a neutral band
# for the trials where the model just did as it was asked, and a blue arm for the trials where it
# refused or checked first. Red means exploited here and in every TikZ diagram in the document.
# benign_compliance is deliberately the palest fill. It is 60-92% of every bar and it is the
# "nothing happened" case, so it reads as background rather than competing with the red.
OUTCOME_COLOUR = {
    "exploited_command_execution": "#7d1f22",
    "exploited_data_exfil": "#c0392f",
    "partial_compliance": "#8a867e",
    "complied_no_tool": "#b3a894",
    "benign_compliance": "#e9e6e0",
    "sought_confirmation": "#6aa8e6",
    "safe_refusal": "#1f5fae",
}

INK = "#3a3a38"      # axis text and error bars, softer than pure black on the page
HAIRLINE = "#c9c7c0"  # bar outlines, so a near-white fill still has a definite edge

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": "#e4e2dc",
    "grid.linewidth": 0.6,
    "figure.dpi": 150,
    # Chrome recedes so the bars carry the figure. Pure black on white is heavier than the
    # document's body text and pulls the eye to the axes instead of the data.
    "text.color": INK,
    "axes.labelcolor": INK,
    "axes.edgecolor": "#b8b6b0",
    "xtick.color": INK,
    "ytick.color": INK,
})


def load(path):
    """Yield every non-error trial from one results file."""
    with open(ROOT / path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("status") == "error":
                continue
            yield r


def split_condition(condition):
    """Separate the system-prompt condition from the reasoning mode.

    Qwen 3 runs label conditions 'neutral_think_off'; Qwen 2.5 and Llama runs, which have no
    reasoning toggle, label the same condition plain 'neutral'.
    """
    if condition.endswith("_think_on"):
        return condition[: -len("_think_on")], "on"
    if condition.endswith("_think_off"):
        return condition[: -len("_think_off")], "off"
    return condition, None


def cohort(payload_id):
    """The three payload groups the cohort figure splits on.

    The third group was labelled "APE" until 3 Sept 2026. Only Wave 1 is adapted from the
    HiddenLayer APE taxonomy: methodology 3.4 records that none of the six proposed APE
    identifiers held up against the taxonomy's own source data, so Wave 3 cites the published
    work behind each technique instead. "Advanced" is what results.tex 4.1 and the figure's own
    caption already call the group.
    """
    n = int(payload_id[1:])
    if n <= 14:
        return "Baseline\nP001\u2013P014"
    if n <= 17:
        return "garak\nP015\u2013P017"
    return "Advanced\nP018\u2013P031"


def payload_of(document_name):
    return re.match(r"(P\d+)", document_name).group(1)


def asr(successes, total):
    """Rate and 95% Wilson interval, all as percentages."""
    if total == 0:
        return 0.0, 0.0, 0.0
    lo, hi = calculate_confidence_interval(successes, total)
    return 100 * successes / total, 100 * lo, 100 * hi


def p_label(p, spaced=False):
    """A p-value as the figures print it: three decimals, four below 0.01, scientific below 0.001."""
    eq = " = " if spaced else "="
    if p >= 0.01:
        return f"$p{eq}{p:.3f}$"
    if p >= 0.001:
        return f"$p{eq}{p:.4f}$"
    mant, exp = f"{p:.1e}".split("e")
    return f"$p{eq}{mant}\\times10^{{{int(exp)}}}$"


def verdict(p, alpha=0.0033):
    """Against the Bonferroni threshold results.tex 4.6 sets."""
    if p < alpha:
        return "significant, survives correction"
    if p < 0.05:
        return "significant, does not survive correction"
    return "not significant"


def save(fig, name):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    fig.savefig(path, bbox_inches="tight", format="pdf")
    plt.close(fig)
    print(f"  wrote {path}")


def figure_asr_by_model(data):
    """Figure 1: headline ASR per model with Wilson intervals."""
    rows = []
    for model, trials in data.items():
        total = len(trials)
        hits = sum(1 for r in trials if r["status"] in EXPLOITED)
        rate, lo, hi = asr(hits, total)
        rows.append((model, rate, lo, hi, total))
    rows.sort(key=lambda r: r[1])

    print("\nFigure 1 -- ASR by model")
    for model, rate, lo, hi, total in reversed(rows):
        print(f"  {model:15s} {rate:5.2f}% [{lo:.2f}, {hi:.2f}]  n={total}")

    fig, ax = plt.subplots(figsize=(6.3, 2.9))
    y = range(len(rows))
    ax.barh(
        list(y),
        [r[1] for r in rows],
        color=[MODEL_COLOUR[r[0]] for r in rows],
        height=0.62,
        edgecolor=HAIRLINE,
        linewidth=0.5,
        xerr=[[r[1] - r[2] for r in rows], [r[3] - r[1] for r in rows]],
        error_kw={"ecolor": INK, "elinewidth": 0.9, "capsize": 3},
    )
    for i, (model, rate, lo, hi, total) in enumerate(rows):
        # A model that never exploited has no bar to see. Without a mark at zero the row reads as
        # missing data rather than as a measured zero, which is the opposite of what it means.
        if rate == 0:
            ax.plot([0, 0], [i - 0.31, i + 0.31], color=MODEL_COLOUR[model], linewidth=2.4,
                    solid_capstyle="butt")
        ax.text(hi + 0.7, i, f"{rate:.1f}%  (n={total:,})", va="center", fontsize=8)

    ax.set_yticks(list(y))
    ax.set_yticklabels([r[0] for r in rows], fontfamily="monospace", fontsize=8.5)
    ax.set_xlabel("Attack success rate (%)")
    ax.set_xlim(0, max(r[3] for r in rows) + 9)
    ax.grid(axis="y", visible=False)
    save(fig, "fig-asr-by-model.pdf")


def figure_condition_reasoning(data):
    """Figure: both Qwen 3 models across system-prompt condition and reasoning mode.

    This started as one panel for the Mixture-of-Experts model, with a table beside it holding the
    same six cells and a second table holding the dense model's. Both tables are now in the
    appendix and the second panel does their comparing: the conditions fall in the same order on
    both models, the two reasoning modes sit on top of each other inside every condition, and the
    architecture gap opens only in the two conditions that do not push back.
    """
    models = ["qwen3:8b", "qwen3:30b-a3b"]
    order = ["safety_reinforced", "neutral", "tool_encouraging"]

    print("\nFigure -- both Qwen 3 models by condition and reasoning mode (shared P001--P023)")
    fig, axes = plt.subplots(1, 2, figsize=(6.3, 3.2), sharey=True)
    width = 0.34
    for ax, model in zip(axes, models):
        trials = [r for r in data[model] if payload_of(r["document_name"]) <= "P023"]
        counts = defaultdict(lambda: [0, 0])  # (condition, mode) -> [hits, total]
        for r in trials:
            cond, mode = split_condition(r["condition"])
            cell = counts[(cond, mode)]
            cell[1] += 1
            if r["status"] in EXPLOITED:
                cell[0] += 1

        print(f"  {model}")
        for offset, mode, colour, label in (
            (-width / 2, "off", THINK_OFF, "Reasoning off"),
            (width / 2, "on", THINK_ON, "Reasoning on"),
        ):
            rates, tops, errs = [], [], [[], []]
            for cond in order:
                hits, total = counts[(cond, mode)]
                rate, lo, hi = asr(hits, total)
                rates.append(rate)
                tops.append(hi)
                errs[0].append(rate - lo)
                errs[1].append(hi - rate)
                print(f"    {cond:20s} think_{mode:3s} {hits:3d}/{total:3d} "
                      f"{rate:5.2f}% [{lo:.2f}, {hi:.2f}]")
            xs = [i + offset for i in range(len(order))]
            ax.bar(xs, rates, width, color=colour, edgecolor=HAIRLINE, linewidth=0.5, label=label,
                   yerr=errs, error_kw={"ecolor": INK, "elinewidth": 0.9, "capsize": 3})
            # Sit the value above the upper interval cap so the two never overlap.
            for x, rate, top in zip(xs, rates, tops):
                ax.text(x, top + 0.5, f"{rate:.1f}", ha="center", fontsize=7.6)

        ax.set_xticks(range(len(order)))
        ax.set_xticklabels(order, fontfamily="monospace", fontsize=7.2, rotation=22, ha="right")
        ax.set_ylim(0, 22)
        ax.set_yticks([0, 5, 10, 15, 20])
        ax.grid(axis="x", visible=False)
        ax.set_title(model, loc="left", fontsize=8.5, fontfamily="monospace", pad=5)

    axes[0].set_ylabel("Attack success rate (%)")
    axes[0].legend(frameon=False, fontsize=8.5, loc="upper left")
    save(fig, "fig-asr-condition-reasoning.pdf")


def figure_three_axes(data):
    """Figure: the three research axes as dot-and-interval pairs on one shared scale.

    RQ1, RQ2 and RQ3 were each written out as a paragraph of rates, intervals and p-values. They
    are three comparisons of exactly the same shape, so they belong on one picture with one scale:
    the reader sees at a glance that version moves the rate furthest, architecture moves it the
    wrong way, and reasoning mode moves it only on the advanced cohort.

    The populations are not the same in all three panels and that is not a detail to hide, so each
    panel names the trials behind it. Panels 1 and 2 use the shared P001-P023 set; panel 3 uses
    the two pooled Wave-1 runs on qwen3:8b, which is the only place the reasoning effect
    reaches significance.
    """
    matched = {
        model: [r for r in trials if payload_of(r["document_name"]) <= "P023"]
        for model, trials in data.items()
    }

    def rate_of(records):
        hits = sum(1 for r in records if r["status"] in EXPLOITED)
        return (*asr(hits, len(records)), len(records), hits)

    def p_between(a, b):
        return run_fishers_exact_test(a[4], a[3], b[4], b[3])[1]

    pooled = list(load("results/advanced_cohort_qwen3_wave1_pooled.jsonl"))
    advanced = {"on": [], "off": []}
    for r in pooled:
        _, mode = split_condition(r["condition"])
        if mode:
            advanced[mode].append(r)

    baseline = {"on": [], "off": []}
    wave2 = {"on": [], "off": []}
    for r in data["qwen3:8b"]:
        pid = payload_of(r["document_name"])
        _, mode = split_condition(r["condition"])
        if not mode:
            continue
        if pid <= "P017":
            baseline[mode].append(r)
        elif "P024" <= pid <= "P026":
            wave2[mode].append(r)

    # P025 is the payload behind the Wave-2 reversal, so the panel names it.
    p025 = {mode: rate_of([r for r in wave2[mode] if payload_of(r["document_name"]) == "P025"])
            for mode in ("on", "off")}
    p025_note = (f"P025 alone: {p025['on'][0]:.2f}% on, {p025['off'][0]:.2f}% off "
                 f"({p025['on'][4]}/{p025['on'][3]} against {p025['off'][4]}/{p025['off'][3]})")

    def pair(title, population, rows, note=""):
        p = p_between(rows[0][2], rows[1][2])
        return (title, population, p_label(p, spaced=True), verdict(p), rows, note)

    # (panel title, population note, p-value label, Bonferroni verdict, rows, extra note).
    # Every p is Fisher's exact test on the two counts drawn, computed here rather than carried
    # as a string, so a change in the data cannot leave a stale label behind.
    panels = [
        pair("Version (RQ1)", "shared P001–P023 set",
             [("qwen2.5:7b", MODEL_COLOUR["qwen2.5:7b"], rate_of(matched["qwen2.5:7b"])),
              ("qwen3:8b", MODEL_COLOUR["qwen3:8b"], rate_of(matched["qwen3:8b"]))]),
        pair("Architecture (RQ2)", "shared P001–P023 set",
             [("qwen3:30b-a3b", MODEL_COLOUR["qwen3:30b-a3b"], rate_of(matched["qwen3:30b-a3b"])),
              ("qwen3:8b", MODEL_COLOUR["qwen3:8b"], rate_of(matched["qwen3:8b"]))]),
        # The three reasoning panels are the RQ3 finding. Splitting them is the point: the axis
        # does nothing on naive payloads, protects on Wave 1, and goes the other way on Wave 2,
        # and one pooled panel would average all of that away.
        pair("Reasoning mode on simple payloads (RQ3)", "P001–P017, qwen3:8b",
             [("think_off", THINK_OFF, rate_of(baseline["off"])),
              ("think_on", THINK_ON, rate_of(baseline["on"]))]),
        pair("Reasoning mode on advanced payloads (RQ3)", "the two pooled Wave-1 runs, qwen3:8b",
             [("think_off", THINK_OFF, rate_of(advanced["off"])),
              ("think_on", THINK_ON, rate_of(advanced["on"]))]),
        pair("Reasoning mode on Wave 2 (RQ3)", "P024–P026, qwen3:8b",
             [("think_off", THINK_OFF, rate_of(wave2["off"])),
              ("think_on", THINK_ON, rate_of(wave2["on"]))], p025_note),
    ]

    print("\nFigure -- the three axes")
    fig, axes = plt.subplots(5, 1, figsize=(6.3, 6.9), sharex=True,
                             gridspec_kw={"hspace": 0.72})
    for ax, (title, population, plabel, verdict_text, rows, note) in zip(axes, panels):
        print(f"  {title}  ({population})  {plabel}, {verdict_text}")
        for i, (name, colour, (rate, lo, hi, n, _hits)) in enumerate(rows):
            y = len(rows) - 1 - i
            ax.errorbar(rate, y, xerr=[[rate - lo], [hi - rate]], fmt="o", color=colour,
                        markersize=6.5, elinewidth=1.5, capsize=3.5,
                        ecolor=colour, markeredgecolor=HAIRLINE, markeredgewidth=0.5)
            ax.text(hi + 0.8, y, f"{rate:.2f}%  [{lo:.2f}, {hi:.2f}]  n={n:,}",
                    va="center", fontsize=7.6)
            print(f"    {name:14s} {rate:5.2f}% [{lo:.2f}, {hi:.2f}]  n={n:,}")
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([r[0] for r in reversed(rows)], fontfamily="monospace", fontsize=8.5)
        # A panel with a second note line needs room under the rows for both lines.
        ax.set_ylim(-1.75 if note else -1.15, len(rows) - 0.45)
        ax.grid(axis="y", visible=False)
        ax.set_title(f"{title}, {population}", loc="left", fontsize=8.8, pad=6)
        # The p-value and whether it clears the corrected threshold belong beside the pair they
        # describe, not in a sentence three pages later.
        label = f"{plabel}, {verdict_text}" + (f"\n{note}" if note else "")
        ax.text(0.012, 0.045, label, transform=ax.transAxes,
                ha="left", va="bottom", fontsize=7.6, color=INK)
        if note:
            print(f"    {note}")

    axes[-1].set_xlabel("Attack success rate (%), with 95% Wilson interval")
    axes[-1].set_xlim(0, 45)
    save(fig, "fig-three-axes.pdf")


def figure_gap(data):
    """Figure: the GAP rate per model, exploited trials whose reply still refused.

    results.tex 4.7 quoted four rates with their fractions and intervals in one paragraph. One row
    per model reads at a glance and keeps the llama3.1:8b outlier visible. The refusal test is the
    pipeline's own keyword list (analyze_results.py), applied to the reply the user saw.
    """
    refusal = ["sorry", "cannot", "unable", "i can't", "restricted"]
    rows = []
    for model in ["llama3.1:8b", "qwen2.5:7b", "qwen3:30b-a3b", "qwen3:8b"]:
        exploited = [r for r in data[model] if r["status"] in EXPLOITED]
        gap = sum(1 for r in exploited
                  if any(k in (r.get("llm_response") or "").lower() for k in refusal))
        rows.append((model, MODEL_COLOUR[model], (*asr(gap, len(exploited)), len(exploited), gap)))
    rows.sort(key=lambda row: row[2][0], reverse=True)

    print("\nFigure -- GAP rate by model")
    fig, ax = plt.subplots(figsize=(6.3, 1.9))
    for i, (name, colour, (rate, lo, hi, n, gap)) in enumerate(rows):
        y = len(rows) - 1 - i
        ax.errorbar(rate, y, xerr=[[rate - lo], [hi - rate]], fmt="o", color=colour,
                    markersize=6.5, elinewidth=1.5, capsize=3.5,
                    ecolor=colour, markeredgecolor=HAIRLINE, markeredgewidth=0.5)
        ax.text(hi + 0.8, y, f"{rate:.2f}%  [{lo:.2f}, {hi:.2f}]  ({gap}/{n})",
                va="center", fontsize=7.6)
        print(f"    {name:14s} {gap:3d}/{n:5d} = {rate:5.2f}% [{lo:.2f}, {hi:.2f}]")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in reversed(rows)], fontfamily="monospace", fontsize=8.5)
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.set_xlim(0, 45)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Share of exploited trials whose reply still refused (%), with 95% Wilson interval")
    save(fig, "fig-gap-by-model.pdf")


def figure_ablations(data):
    """Figure: the Wave-2 and Wave-3 payload ablations on the four models that ran them.

    Both waves were reported as tables with the prose walking through the cells underneath. The
    two arguments they carry are comparisons, so they are drawn as comparisons: the top panel puts
    each variant of P020 next to the unobfuscated P020 it was made from, and the bottom panel puts
    the five screened families on the same scale. Sharing one x-axis is what lets the obfuscation
    boundary be seen rather than described, since P029 and P030 sit far below the command-execution
    payload in the panel above them without collapsing the way base64 does.
    """
    wave2 = [("P020", "P020  CoT-spoof, exfiltration"),
             ("P024", "P024      + base64 encoding"),
             ("P025", "P025      + payload splitting"),
             ("P026", "P026  CoT-spoof, command execution")]
    wave3 = [("P027", "P027  Many-Shot Jailbreaking"),
             ("P028", "P028  The Skeleton Key"),
             ("P029", "P029  Hyphen-spaced characters"),
             ("P030", "P030  Case-swapped letters"),
             ("P031", "P031  DeepInception"),]
    # qwen3:8b ran Waves 2 and 3 on 2 Sept 2026 in both reasoning modes; it is pooled across them
    # here, as figure_technique_family pools it, so its cells hold n=180 against n=90. The MoE
    # model ran the same eight payloads in both reasoning modes and is pooled the same way.
    models = ["llama3.1:8b", "qwen2.5:7b", "qwen3:8b", "qwen3:30b-a3b"]

    def cell(model, pid):
        rows = [r for r in data[model] if payload_of(r["document_name"]) == pid]
        hits = sum(1 for r in rows if r["status"] in EXPLOITED)
        return (*asr(hits, len(rows)), len(rows))

    print("\nFigure -- Wave-2 and Wave-3 ablations")
    fig, axes = plt.subplots(2, 1, figsize=(6.3, 5.9),
                             gridspec_kw={"height_ratios": [4, 5], "hspace": 0.28}, sharex=True)
    height = 0.20
    for ax, block, title in (
        (axes[0], wave2, "Wave 2: obfuscating and re-aiming the strong P020 payload"),
        (axes[1], wave3, "Wave 3: the five screened families"),
    ):
        print(f"  {title}")
        offsets = [1.5 * height, 0.5 * height, -0.5 * height, -1.5 * height]
        for offset, model in zip(offsets, models):
            ys, rates = [], []
            for i, (pid, _) in enumerate(block):
                rate, lo, hi, n = cell(model, pid)
                if n == 0:
                    continue   # not run: draw nothing rather than a stub that reads as a measured zero
                y = len(block) - 1 - i + offset
                ys.append(y)
                rates.append(rate)
                # A measured zero must look measured. Without the stub it reads as missing data.
                if rate == 0:
                    ax.plot([0, 0], [y - height / 2, y + height / 2], color=MODEL_COLOUR[model],
                            linewidth=2.2, solid_capstyle="butt")
                ax.text(rate + 1.2, y, f"{rate:.2f}", va="center", fontsize=7.4)
                print(f"    {pid}  {model:13s} {rate:6.2f}%  n={n}")
            ax.barh(ys, rates, height=height, color=MODEL_COLOUR[model], edgecolor=HAIRLINE,
                    linewidth=0.5, label=model)
        ax.set_yticks(range(len(block)))
        ax.set_yticklabels([lab for _, lab in reversed(block)], fontsize=8, fontfamily="monospace")
        ax.set_ylim(-0.7, len(block) - 0.3)
        ax.grid(axis="y", visible=False)
        ax.set_title(title, loc="left", fontsize=8.8, pad=6)

    axes[1].legend(frameon=False, fontsize=8.5, loc="lower right")
    axes[-1].set_xlim(0, 100)
    # Four models put the caption over one line at this width, so it wraps rather than running
    # off the right-hand edge of the axes.
    axes[-1].set_xlabel("Attack success rate (%), $n=90$ per cell,\n"
                        "$n=180$ for the two Qwen 3 models (both reasoning modes)")
    save(fig, "fig-ablations.pdf")


def figure_hardening(data):
    """Figure: whether adding safety instructions to the system prompt helps.

    The Discussion argued this across four models in eight rates and four p-values, and the point
    it was making is an ordering rather than any one number: hardening failed on the most exposed
    model and on the least exposed one, and worked on the two in between. Drawn with the models in
    order of exposure, that non-monotonicity is the shape of the panel, so a defender can see that a
    model's own ASR does not predict whether a preamble will help it.

    The second panel is the case that runs the other way. Pooled over both Wave-3 runs, the Skeleton
    Key is least effective under the neutral prompt and most effective under safety_reinforced,
    which inverts the ordering the hardening exists to produce. It had no picture anywhere.

    Rates here are whole-file, which is the population the Discussion quotes. fig:asr-condition-
    reasoning draws the two Qwen 3 models on the matched P001-P023 grid instead, where the
    Mixture-of-Experts model reads 11.67% against 5.43%. Both are right and the caption says which
    is which, because 11.18% is also that model's matched-grid ASR and 5.59% is also llama3.1:8b's
    overall ASR, and those collisions are coincidences.
    """
    # Ordered by each model's own whole-file ASR, worst first. That ordering is the argument.
    def overall_rate(model):
        return sum(1 for r in data[model] if r["status"] in EXPLOITED) / len(data[model])
    models = sorted(["qwen2.5:7b", "qwen3:30b-a3b", "qwen3:8b", "llama3.1:8b"],
                    key=overall_rate, reverse=True)


    def cell(trials, condition):
        rows = [r for r in trials if split_condition(r["condition"])[0] == condition]
        hits = sum(1 for r in rows if r["status"] in EXPLOITED)
        return (*asr(hits, len(rows)), hits, len(rows))

    # P028 ran twice on qwen2.5:7b, once in the Wave-3 cohort and once in the fixed-pipeline
    # baseline, and results.tex 4.5.7 pools them. Same justification, same n=60 per condition.
    pooled = [r for r in data["qwen2.5:7b"] if payload_of(r["document_name"]) == "P028"]
    pooled += [r for r in load("results/advanced_cohort_wave3.jsonl")
               if r["model"] == "qwen2.5:7b" and payload_of(r["document_name"]) == "P028"]

    print("\nFigure -- does hardening the system prompt help?")
    # Not sharex: the two panels are different payload sets on different populations, and panel 1's
    # movements are a few points wide, so borrowing panel 2's 70-point range would flatten them.
    fig, axes = plt.subplots(2, 1, figsize=(6.3, 4.8),
                             gridspec_kw={"height_ratios": [4, 3], "hspace": 0.55})

    # ---- panel 1: neutral -> safety_reinforced on each model that recorded an exploit
    ax = axes[0]
    print("  Panel 1, whole-file rates")
    labels = []
    for i, model in enumerate(models):
        y = len(models) - 1 - i
        colour = MODEL_COLOUR[model]
        n_rate, n_lo, n_hi, n_hits, n_tot = cell(data[model], "neutral")
        s_rate, s_lo, s_hi, s_hits, s_tot = cell(data[model], "safety_reinforced")
        plabel = p_label(run_fishers_exact_test(n_hits, n_tot, s_hits, s_tot)[1])
        overall = 100 * sum(1 for r in data[model] if r["status"] in EXPLOITED) / len(data[model])
        labels.append(f"{model}\n{overall:.2f}% overall")
        # The connector carries the direction; the arrowhead says which end is the hardened one.
        ax.annotate("", xy=(s_rate, y), xytext=(n_rate, y),
                    arrowprops={"arrowstyle": "-|>", "color": colour, "linewidth": 1.6,
                                "shrinkA": 0, "shrinkB": 0})
        for rate, lo, hi, filled in ((n_rate, n_lo, n_hi, False), (s_rate, s_lo, s_hi, True)):
            ax.errorbar(rate, y, xerr=[[rate - lo], [hi - rate]], fmt="o", markersize=6,
                        color=colour, ecolor=colour, elinewidth=1.2, capsize=3,
                        markerfacecolor=colour if filled else "none",
                        markeredgecolor=colour, markeredgewidth=1.3, zorder=3 if filled else 4)
        # A fixed x makes the changes read as one column rather than four ragged labels.
        ax.text(26.5, y, f"{n_rate:.2f} to {s_rate:.2f},  {plabel}", va="center", fontsize=7.4)
        print(f"    {model:14s} neutral {n_hits:3d}/{n_tot:4d} {n_rate:5.2f}% [{n_lo:.2f}, {n_hi:.2f}]"
              f"  safety_reinforced {s_hits:3d}/{s_tot:4d} {s_rate:5.2f}% [{s_lo:.2f}, {s_hi:.2f}]"
              f"  overall {overall:5.2f}%  {plabel}")
    ax.set_yticks(range(len(models)))
    ax.set_yticklabels(list(reversed(labels)), fontsize=7.4, fontfamily="monospace")
    ax.set_ylim(-1.15, len(models) - 0.45)
    ax.set_xlim(0, 46)
    ax.set_xticks([0, 5, 10, 15, 20, 25])
    ax.spines["bottom"].set_bounds(0, 25)
    ax.set_xlabel("Attack success rate (%), with 95% Wilson interval", fontsize=8.5)
    ax.grid(axis="y", visible=False)
    ax.set_title("Adding safety instructions to the system prompt, whole-file rates",
                 loc="left", fontsize=8.8, pad=6)
    ax.legend(handles=[
        plt.Line2D([], [], marker="o", linestyle="none", markerfacecolor="none",
                   markeredgecolor=INK, markeredgewidth=1.3, markersize=6,
                   label="neutral prompt"),
        plt.Line2D([], [], marker="o", linestyle="none", color=INK, markersize=6,
                   label="safety_reinforced prompt"),
    ], frameon=False, fontsize=7.4, ncol=2, loc="lower left", bbox_to_anchor=(0.0, -0.02))

    # ---- panel 2: the one attack the hardening makes worse
    ax = axes[1]
    order = ["neutral", "tool_encouraging", "safety_reinforced"]
    colour = MODEL_COLOUR["qwen2.5:7b"]
    print("  Panel 2, P028 (the Skeleton Key) on qwen2.5:7b, pooled over both Wave-3 runs")
    for i, cond in enumerate(order):
        y = len(order) - 1 - i
        rate, lo, hi, hits, tot = cell(pooled, cond)
        ax.errorbar(rate, y, xerr=[[rate - lo], [hi - rate]], fmt="o", markersize=6, color=colour,
                    ecolor=colour, elinewidth=1.2, capsize=3, markeredgecolor=HAIRLINE,
                    markeredgewidth=0.5)
        ax.text(hi + 1.2, y, f"{rate:.2f}%  ({hits}/{tot})", va="center", fontsize=7.4)
        print(f"    {cond:20s} {hits:2d}/{tot:2d} {rate:5.2f}% [{lo:.2f}, {hi:.2f}]")
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(list(reversed(order)), fontsize=7.8, fontfamily="monospace")
    ax.set_ylim(-1.05, len(order) - 0.45)
    ax.set_xlim(0, 80)
    ax.set_xticks([0, 20, 40, 60, 80])
    ax.grid(axis="y", visible=False)
    ax.set_title("P028, the Skeleton Key, on qwen2.5:7b ($n=60$ per condition, two runs pooled)",
                 loc="left", fontsize=8.8, pad=6)
    _, _, _, nh, nt = cell(pooled, "neutral")
    _, _, _, sh, st = cell(pooled, "safety_reinforced")
    p28 = p_label(run_fishers_exact_test(nh, nt, sh, st)[1])
    ax.text(0.0, 0.02, f"neutral against safety_reinforced, {p28}", transform=ax.transAxes,
            ha="left", va="bottom", fontsize=7.4, color=INK)
    ax.set_xlabel("Attack success rate (%), with 95% Wilson interval")

    save(fig, "fig-hardening.pdf")


def figure_document_type(data):
    """Figure: ASR by document type, one small panel per model.

    RQ4's largest within-model effect is the document the payload arrived in, and it was split
    across two tables and a paragraph that restated both. Four panels in fixed document order let
    the finding be read directly: email is the tallest bar in every panel, and what sits below it
    changes from model to model, which is the part a single pooled figure would hide.

    Panels use each model's own hue, the same convention as the rest of the chapter, so document
    type is carried by position and label rather than by a second colour scheme.
    """
    carriers = [("email", "email"), ("code_comment", "code comment"), ("readme", "README")]
    models = ["qwen2.5:7b", "qwen3:30b-a3b", "qwen3:8b", "llama3.1:8b"]

    def carrier_of(name):
        return name.split("_", 1)[1].replace(".txt", "")

    print("\nFigure -- ASR by document type, each model's whole payload set")
    fig, axes = plt.subplots(1, 4, figsize=(6.3, 2.5), sharex=True)
    for ax, model in zip(axes, models):
        rates = []
        for key, _ in carriers:
            rows = [r for r in data[model] if carrier_of(r["document_name"]) == key]
            hits = sum(1 for r in rows if r["status"] in EXPLOITED)
            rate, lo, hi, n = *asr(hits, len(rows)), len(rows)
            rates.append(rate)
            print(f"  {model:14s} {key:13s} {rate:6.2f}% [{lo:.2f}, {hi:.2f}]  n={n:,}")
        ys = [len(carriers) - 1 - i for i in range(len(carriers))]
        ax.barh(ys, rates, height=0.6, color=MODEL_COLOUR[model], edgecolor=HAIRLINE,
                linewidth=0.5)
        for y, rate in zip(ys, rates):
            if rate == 0:
                ax.plot([0, 0], [y - 0.3, y + 0.3], color=MODEL_COLOUR[model], linewidth=2.2,
                        solid_capstyle="butt")
            ax.text(rate + 1.6, y, f"{rate:.2f}", va="center", fontsize=7.6)
        ax.set_yticks(ys)
        ax.set_yticklabels([lab for _, lab in carriers], fontsize=8)
        ax.set_ylim(-0.55, len(carriers) - 0.45)
        ax.grid(axis="y", visible=False)
        ax.set_title(model, loc="left", fontsize=8.3, fontfamily="monospace", pad=5)
        ax.set_xlim(0, 52)
        ax.set_xticks([0, 25, 50])
        if ax is not axes[0]:
            ax.tick_params(labelleft=False)
    fig.supxlabel("Attack success rate (%)", fontsize=9, y=-0.02)
    save(fig, "fig-asr-by-document.pdf")


# Magnitude, not identity, so one hue running light to dark. It runs to the same reds the outcome
# taxonomy uses for its exploit arm, which keeps "darker red means more exploited" true across every
# figure in the document. Never a rainbow: the reader has to be able to rank two cells by eye.
ASR_RAMP = LinearSegmentedColormap.from_list(
    "ipi_asr", ["#faf7f6", "#f0cdc8", "#dd8378", "#c0392f", "#7d1f22"]
)


def figure_technique_family(data):
    """Figure: Wave-1 technique family against model, as a heatmap with every value printed.

    The claim this supports is that no attack family dominates across models, and that claim is a
    shape rather than a list: the dark cells sit in a different row for each column. Written out as
    prose it was six rates in three sentences and the reader had to hold them all at once.

    Colour is the second encoding here, not the only one. Every cell carries its own number, so the
    figure survives greyscale printing and a reader who cannot separate the ramp's middle steps.
    """
    families = [("P018", "Control-token spoofing"), ("P019", "Response priming"),
                ("P020", "Chain-of-thought spoofing"), ("P021", "Tool self-escalation"),
                ("P022", "Syntax-framed override"), ("P023", "Indirect-visibility biasing")]
    # qwen3:8b pools its two independent same-pipeline Wave-1 runs, the same set the chapter uses.
    pooled = list(load("results/advanced_cohort_qwen3_wave1_pooled.jsonl"))
    columns = [("llama3.1:8b", data["llama3.1:8b"]), ("qwen2.5:7b", data["qwen2.5:7b"]),
               ("qwen3:8b", pooled)]

    grid, counts = [], []
    print("\nFigure -- Wave-1 technique family by model")
    for pid, name in families:
        row, ns = [], []
        for model, records in columns:
            rows = [r for r in records if payload_of(r["document_name"]) == pid]
            hits = sum(1 for r in rows if r["status"] in EXPLOITED)
            row.append(asr(hits, len(rows))[0])
            ns.append(len(rows))
        grid.append(row)
        counts.append(ns)
        print(f"  {pid} {name:28s} " + "  ".join(f"{v:6.2f}%" for v in row))

    fig, ax = plt.subplots(figsize=(6.3, 2.9))
    ax.imshow(grid, cmap=ASR_RAMP, vmin=0, vmax=100, aspect="auto")
    for i, row in enumerate(grid):
        for j, value in enumerate(row):
            # White ink only where the fill is dark enough to need it.
            ink = "white" if value >= 55 else INK
            ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=9, color=ink)

    ax.set_xticks(range(len(columns)))
    ax.set_xticklabels([m for m, _ in columns], fontfamily="monospace", fontsize=8.5)
    ax.xaxis.set_ticks_position("top")
    ax.set_yticks(range(len(families)))
    ax.set_yticklabels([f"{pid}  {name}" for pid, name in families], fontsize=8.5)
    ax.set_xticks([x - 0.5 for x in range(1, len(columns))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(families))], minor=True)
    # A hairline between cells so two adjacent pale fills do not read as one block.
    ax.grid(which="minor", color="white", linewidth=1.6)
    ax.grid(which="major", visible=False)
    ax.tick_params(which="minor", length=0)
    ax.tick_params(which="major", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    save(fig, "fig-technique-family.pdf")


def figure_cohort(data):
    """Figure 3: ASR by payload cohort, one small panel per cohort.

    Three panels rather than one grouped bar chart. Five models grouped inside three clusters
    needed a five-colour legend to read at all, the bars were narrow enough that the value labels
    had to be turned on their side, and a model that scored zero simply had no bar in any cluster.
    Putting the models on the vertical axis of each panel names every one of them in place, so the
    legend goes, the labels sit level, and a zero is a visible row with 0.0 written against it.
    The three panels share one x-axis range so a bar in one is directly comparable with a bar in
    another.
    """
    groups = ["Baseline\nP001\u2013P014", "garak\nP015\u2013P017", "Advanced\nP018\u2013P031"]
    models = ["qwen2.5:7b", "qwen3:8b", "qwen3:30b-a3b", "llama3.1:8b", "qwen2.5:1.5b"]

    counts = defaultdict(lambda: [0, 0])
    for model in models:
        for r in data[model]:
            cell = counts[(model, cohort(payload_of(r["document_name"])))]
            cell[1] += 1
            if r["status"] in EXPLOITED:
                cell[0] += 1

    print("\nFigure 3 -- ASR by payload group")
    fig, axes = plt.subplots(1, 3, figsize=(6.3, 2.6), sharey=True)
    y = list(range(len(models)))

    # One shared limit across the three panels, sized to the largest bar in any of them, so the
    # garak panel's 56.3% cannot be mistaken for the same length as the advanced panel's 30.7%.
    widest = max(asr(*counts[(m, g)])[0] for m in models for g in groups)
    xmax = widest * 1.34

    for ax, g in zip(axes, groups):
        rates = []
        for model in models:
            hits, total = counts[(model, g)]
            rate, lo, hi = asr(hits, total)
            rates.append(rate)
            print(f"  {model:15s} {g.replace(chr(10), ' '):22s} {hits:4d}/{total:4d} "
                  f"{rate:5.2f}% [{lo:.2f}, {hi:.2f}]")
        ax.barh(y, rates, color=[MODEL_COLOUR[m] for m in models], height=0.66,
                edgecolor=HAIRLINE, linewidth=0.5)
        for i, (model, rate) in enumerate(zip(models, rates)):
            if rate == 0:
                ax.plot([0, 0], [i - 0.33, i + 0.33], color=MODEL_COLOUR[model], linewidth=2.2,
                        solid_capstyle="butt")
            ax.text(rate + xmax * 0.035, i, f"{rate:.1f}", va="center", fontsize=7)

        ax.set_title(g, fontsize=8.5, pad=6)
        ax.set_xlim(0, xmax)
        ax.set_ylim(len(models) - 0.5, -0.5)
        ax.grid(axis="y", visible=False)
        ax.tick_params(axis="x", labelsize=7.5)

    axes[0].set_yticks(y)
    axes[0].set_yticklabels(models, fontfamily="monospace", fontsize=8)
    axes[1].set_xlabel("Attack success rate (%)")
    fig.subplots_adjust(wspace=0.12)
    save(fig, "fig-asr-by-cohort.pdf")


def figure_outcomes(data):
    """Figure 4: the full outcome taxonomy per model, as proportions."""
    # Ordered worst to best, so the exploited block sits at the left of every bar and the colour
    # runs red through neutral to blue across it.
    order = [
        ("exploited_command_execution", "Exploited: command execution"),
        ("exploited_data_exfil", "Exploited: data exfiltration"),
        ("partial_compliance", "Partial compliance"),
        ("complied_no_tool", "Complied, no tool call"),
        ("benign_compliance", "Benign compliance"),
        ("sought_confirmation", "Sought confirmation"),
        ("safe_refusal", "Safe refusal"),
    ]
    order = [(k, label, OUTCOME_COLOUR[k]) for k, label in order]
    models = ["qwen2.5:7b", "qwen3:30b-a3b", "qwen3:8b", "llama3.1:8b", "qwen2.5:1.5b"]

    print("\nFigure 4 -- outcome taxonomy (% of valid trials)")
    fig, ax = plt.subplots(figsize=(6.3, 3.0))
    lefts = [0.0] * len(models)
    shares = {}
    for model in models:
        c = Counter(r["status"] for r in data[model])
        n = sum(c.values())
        shares[model] = {k: 100 * c[k] / n for k, _, _ in order}
        print(f"  {model:15s} " + "  ".join(
            f"{k.split('_')[0][:6]}={shares[model][k]:.1f}%" for k, _, _ in order if shares[model][k]))

    for status, label, colour in order:
        widths = [shares[m][status] for m in models]
        ax.barh(range(len(models)), widths, left=lefts, height=0.62, color=colour,
                edgecolor="white", linewidth=0.8, label=label)
        lefts = [l + w for l, w in zip(lefts, widths)]

    # benign_compliance is nearly white, so without an outline the long middle of each bar has no
    # edge against the page and the bar looks like it stops where the red ends.
    for i in range(len(models)):
        ax.add_patch(plt.Rectangle((0, i - 0.31), 100, 0.62, fill=False, edgecolor=HAIRLINE,
                                   linewidth=0.6, zorder=3))

    ax.set_yticks(range(len(models)))
    ax.set_yticklabels(models, fontfamily="monospace", fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlabel("Share of valid trials (%)")
    ax.set_xlim(0, 100)
    ax.grid(axis="y", visible=False)
    handles = [Patch(facecolor=c, edgecolor="white", label=l) for _, l, c in order]
    ax.legend(handles=handles, frameon=False, fontsize=7.5, ncol=2,
              loc="upper center", bbox_to_anchor=(0.5, -0.24))
    save(fig, "fig-outcome-taxonomy.pdf")


def main():
    global OUT_DIR
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--out-dir", default=OUT_DIR, type=Path,
                    help=f"Where to write the figures (default: {OUT_DIR})")
    OUT_DIR = ap.parse_args().out_dir

    data = {}
    for model, path in RUNS.items():
        if not (ROOT / path).exists():
            sys.exit(f"Missing results file: {ROOT / path}")
        data[model] = list(load(path))

    total = sum(len(v) for v in data.values())
    print(f"Loaded {total:,} valid trials across {len(data)} models")
    if total != 19530:
        print(f"  WARNING: expected 19,530 valid trials, the chapter's figure. Got {total:,}.")

    figure_asr_by_model(data)
    figure_condition_reasoning(data)
    figure_three_axes(data)
    figure_ablations(data)
    figure_hardening(data)
    figure_document_type(data)
    figure_technique_family(data)
    figure_cohort(data)
    figure_outcomes(data)
    figure_gap(data)


if __name__ == "__main__":
    main()
