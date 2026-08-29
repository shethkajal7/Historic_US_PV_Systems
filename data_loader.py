from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple, List
import re
import numpy as np
import pandas as pd

DATA_PATH = Path(__file__).resolve().parent / "data" / "100oldest.xlsx"

CORE_COLS = [
    "Line#", "EIA#", "Name", "1st full yr", "1st kWh", "Sector", "Module type",
    "Developer", "(F)ix,(T)rkr", "Slope/Tilt", "State", "Lat", "Long", "MWp", "MWac",
    "POA (by eqn.)", "TMY2 Source", "Annual T,air", "Estim. Tmod", "and C<40",
    "GHI", "DHI", "Kt", "DF", "Est.Clip", "Clip Frac.", "p50,Yr1 MWh",
    "Expected", "Actual", "Lifetime PI", "Percentile Rank", "Type", "Lifetime Degr",
    "Linest slope", "Linest Int."
]

YEAR_COLS = list(range(1, 24))
PI_COLS = [f"{i}.1" for i in range(1, 24)]
PI_COLS[13] = "14.2"  # Excel duplicate-column name created by pandas for the 14th relative-year PI field.


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() if not isinstance(c, int) else c for c in df.columns]
    return df


def _col_to_idx(col: str) -> int:
    idx = 0
    for ch in col.upper():
        if ch.isalpha():
            idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _cell_to_rc(cell: str) -> tuple[int, int]:
    match = re.match(r"\$?([A-Z]+)\$?(\d+)", cell.upper())
    if not match:
        raise ValueError(f"Invalid Excel cell reference: {cell}")
    return int(match.group(2)) - 1, _col_to_idx(match.group(1))


def excel_range(raw: pd.DataFrame, range_ref: str) -> pd.DataFrame:
    """Return a workbook-style range from a raw sheet loaded with header=None."""
    start, end = range_ref.replace("$", "").split(":")
    r1, c1 = _cell_to_rc(start)
    r2, c2 = _cell_to_rc(end)
    return raw.iloc[r1:r2 + 1, c1:c2 + 1]


def _series_from_cells(raw: pd.DataFrame, name_cell: str | None, x_range: str, y_range: str) -> pd.DataFrame:
    x = excel_range(raw, x_range).to_numpy().ravel()
    y = excel_range(raw, y_range).to_numpy().ravel()
    name = "Series"
    if name_cell:
        r, c = _cell_to_rc(name_cell.replace("$", ""))
        name = raw.iat[r, c]
    return pd.DataFrame({"series": str(name), "x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna(subset=["x", "y"])


def load_workbook_tables(path: Path = DATA_PATH) -> Dict[str, pd.DataFrame]:
    if not path.exists():
        raise FileNotFoundError(f"Could not find workbook at {path}")

    plant = pd.read_excel(path, sheet_name="PlantData", header=5, engine="openpyxl")
    plant = _clean_columns(plant)
    plant = plant[pd.to_numeric(plant.get("Line#"), errors="coerce").between(1, 100)].copy()

    for col in ["Line#", "EIA#", "1st full yr", "1st kWh", "Lat", "Long", "MWp", "MWac", "POA (by eqn.)",
                "Annual T,air", "Estim. Tmod", "GHI", "DHI", "Kt", "DF", "Est.Clip", "Clip Frac.",
                "p50,Yr1 MWh", "Expected", "Actual", "Lifetime PI", "Percentile Rank", "Lifetime Degr",
                "Linest slope", "Linest Int."]:
        if col in plant.columns:
            plant[col] = pd.to_numeric(plant[col], errors="coerce")

    consolidated = pd.read_excel(path, sheet_name="ConsolidatedResults", header=2, engine="openpyxl")
    consolidated = _clean_columns(consolidated)
    consolidated = consolidated.dropna(how="all", axis=1).dropna(how="all")
    consolidated = consolidated[pd.to_numeric(consolidated.get("PI rank #"), errors="coerce").notna()].copy()

    comparison = pd.read_excel(path, sheet_name="Comparison", header=None, engine="openpyxl")
    states = pd.read_excel(path, sheet_name="States100", header=None, engine="openpyxl")

    newer25 = pd.read_excel(path, sheet_name="Newer25", header=5, engine="openpyxl")
    newer25 = _clean_columns(newer25)
    newer25 = newer25[pd.to_numeric(newer25.get("Line#"), errors="coerce").between(1, 25)].copy()
    for col in ["Line#", "MWp", "MWac", "Estim. Tmod"]:
        if col in newer25.columns:
            newer25[col] = pd.to_numeric(newer25[col], errors="coerce")

    raw_sheets = {
        "PlantData": pd.read_excel(path, sheet_name="PlantData", header=None, engine="openpyxl"),
        "States25": pd.read_excel(path, sheet_name="States25", header=None, engine="openpyxl"),
        "NullOverlap": pd.read_excel(path, sheet_name="NullOverlap", header=None, engine="openpyxl"),
        "DetailOfP50": pd.read_excel(path, sheet_name="DetailOfP50", header=None, engine="openpyxl"),
        "PRanalysis": pd.read_excel(path, sheet_name="PRanalysis", header=None, engine="openpyxl"),
    }

    # ConsolidatedResults was not refreshed for the module-temperature adjustment, so only
    # its PI values and rank order are rebuilt from PlantData. All other columns are kept.
    consolidated = rebuild_consolidated(consolidated, plant)

    return {
        "plant": plant,
        "newer25": newer25,
        "consolidated": consolidated,
        "comparison_raw": comparison,
        "states_raw": states,
        "raw_sheets": raw_sheets,
        "detail_p50": get_detail_p50(raw_sheets["DetailOfP50"]),
        "pr_analysis": get_pr_analysis(raw_sheets["PRanalysis"]),
        "age_table": get_age_table(raw_sheets["PlantData"]),
        "tmy_locations": get_tmy_locations(raw_sheets["States25"]),
        "pi_cdf": build_pi_cdf(plant),
        "overlap_stats": get_overlap_stats(raw_sheets["NullOverlap"]),
    }


def rebuild_consolidated(consolidated: pd.DataFrame, plant: pd.DataFrame) -> pd.DataFrame:
    """Refresh the ranked results table with temperature-adjusted PI values.

    ConsolidatedResults still holds pre-adjustment PI. This joins the adjusted
    'Lifetime PI' from PlantData by name and re-sorts, leaving other columns untouched.
    """
    out = consolidated.copy()
    if "Name" not in out.columns or "PI (@0.5% degr)" not in out.columns:
        return out
    if "Name" not in plant.columns or "Lifetime PI" not in plant.columns:
        return out

    adjusted = plant[["Name", "Lifetime PI"]].dropna(subset=["Name"]).drop_duplicates("Name")
    lookup = dict(zip(adjusted["Name"], pd.to_numeric(adjusted["Lifetime PI"], errors="coerce")))

    mapped = out["Name"].map(lookup)
    # Fall back to the stored value for any system that cannot be matched by name.
    out["PI (@0.5% degr)"] = mapped.fillna(pd.to_numeric(out["PI (@0.5% degr)"], errors="coerce"))

    out = out.sort_values("PI (@0.5% degr)", ascending=False, kind="mergesort").reset_index(drop=True)
    out["PI rank #"] = np.arange(1, len(out) + 1)
    return out


def build_annual_long(plant: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    id_cols = ["Line#", "Name", "State", "Type", "Module type", "MWp", "MWac", "1st full yr", "Lifetime PI", "Lifetime Degr"]
    existing_id = [c for c in id_cols if c in plant.columns]

    actual_cols = [c for c in YEAR_COLS if c in plant.columns]
    actual = plant[existing_id + actual_cols].melt(
        id_vars=existing_id, value_vars=actual_cols, var_name="relative_year", value_name="actual_mwh"
    )
    actual["relative_year"] = pd.to_numeric(actual["relative_year"], errors="coerce")
    actual["calendar_year"] = actual["1st full yr"] + actual["relative_year"] - 1
    actual = actual.dropna(subset=["actual_mwh"])

    pi_cols = [c for c in PI_COLS if c in plant.columns]
    pi = plant[existing_id + pi_cols].melt(
        id_vars=existing_id, value_vars=pi_cols, var_name="relative_year_raw", value_name="pi"
    )
    raw_to_year = {c: i + 1 for i, c in enumerate(PI_COLS)}
    pi["relative_year"] = pi["relative_year_raw"].map(raw_to_year)
    pi["calendar_year"] = pi["1st full yr"] + pi["relative_year"] - 1
    pi = pi.dropna(subset=["pi"])
    return actual, pi


def top_stats_table(plant: pd.DataFrame, newer25: pd.DataFrame) -> pd.DataFrame:
    """Top summary rows requested by reviewer: sample, sites, integer MWp, integer MWac."""
    return pd.DataFrame([
        {
            "Set": "Set A - typical start 2010",
            "Sites": int(plant["Name"].nunique()),
            "MWp": int(np.floor(pd.to_numeric(plant["MWp"], errors="coerce").sum(skipna=True) + 0.5)),
            "MWac": int(np.floor(pd.to_numeric(plant["MWac"], errors="coerce").sum(skipna=True) + 0.5)),
        },
        {
            "Set": "Set B - all started 2018",
            "Sites": int(newer25["Name"].nunique()),
            "MWp": int(np.floor(pd.to_numeric(newer25["MWp"], errors="coerce").sum(skipna=True) + 0.5)),
            "MWac": int(np.floor(pd.to_numeric(newer25["MWac"], errors="coerce").sum(skipna=True) + 0.5)),
        },
    ])


def temperature_histogram_table(plant: pd.DataFrame, newer25: pd.DataFrame) -> pd.DataFrame:
    """Temperature-bin comparison as percent of each sample."""
    bins = [
        ("Cold, Tmod < 40°C", -np.inf, 40),
        ("Medium, 40°C to 50°C", 40, 50),
        ("Hot, Tmod > 50°C", 50, np.inf),
    ]
    rows = []
    for label, df in [("Set A", plant), ("Set B", newer25)]:
        vals = pd.to_numeric(df.get("Estim. Tmod"), errors="coerce").dropna()
        total = len(vals)
        for bin_label, low, high in bins:
            if np.isneginf(low):
                count = int((vals < high).sum())
            elif np.isposinf(high):
                count = int((vals > low).sum())
            else:
                count = int(((vals >= low) & (vals <= high)).sum())
            rows.append({
                "Set": label,
                "Temperature bin": bin_label,
                "Count": count,
                "Percent of sample": count / total if total else np.nan,
            })
    return pd.DataFrame(rows)


def summary_metrics(plant: pd.DataFrame) -> Dict[str, float]:
    return {
        "site_count": int(plant["Name"].nunique()),
        "total_mwp": float(plant["MWp"].sum(skipna=True)),
        "total_mwac": float(plant["MWac"].sum(skipna=True)),
        "median_pi": float(plant["Lifetime PI"].median(skipna=True)),
        "weighted_pi": float(np.average(plant["Lifetime PI"].dropna(), weights=plant.loc[plant["Lifetime PI"].notna(), "MWp"])),
        "median_degr": float(plant["Lifetime Degr"].median(skipna=True)),
        "p90_pi_rank": float(plant["Lifetime PI"].quantile(0.10)),
        "median_years": float(plant["Line#"].count()),
    }


def get_comparison_table(comparison_raw: pd.DataFrame, path: Path = DATA_PATH) -> pd.DataFrame:
    left = comparison_raw.iloc[8:34, [3, 5, 6, 7]].copy()
    left.columns = ["Metric", "Set A", "Set B", "Finding"]
    left = left[left["Metric"].notna()].reset_index(drop=True)

    # Values are read straight from the Comparison sheet so the page matches the workbook.
    # A previous override of the degradation rows (median of per-system slopes) was removed:
    # it reported a different statistic from the sheet's slope-of-the-median and sat further
    # from the piecewise chart on the same page.
    return left


def get_state_counts(states_raw: pd.DataFrame) -> pd.DataFrame:
    state = states_raw.iloc[1:, [1, 2]].copy()
    state.columns = ["State", "Count"]
    state = state[state["State"].notna()]
    state["Count"] = pd.to_numeric(state["Count"], errors="coerce")
    return state.dropna(subset=["Count"]).reset_index(drop=True)



def get_detail_p50(detail_raw: pd.DataFrame) -> pd.DataFrame:
    """Parse the representative median-system variability table from DetailOfP50."""
    rows = detail_raw.iloc[5:10, :93].copy()
    records = []
    for _, r in rows.iterrows():
        if pd.isna(r.iloc[1]):
            continue
        rec = {
            "PI rank": pd.to_numeric(r.iloc[0], errors="coerce"),
            "Name": r.iloc[1],
            "Lifetime variability": pd.to_numeric(r.iloc[2], errors="coerce"),
            "State": r.iloc[3],
            "MWp": pd.to_numeric(r.iloc[4], errors="coerce"),
            "p50 Yr1 exp. MWh": pd.to_numeric(r.iloc[5], errors="coerce"),
            "TMY2": r.iloc[6],
            "Normal POA Variability": pd.to_numeric(r.iloc[7], errors="coerce"),
            "LTAvg POA": pd.to_numeric(r.iloc[8], errors="coerce"),
            "Structure": r.iloc[9],
            "Expected PR": pd.to_numeric(r.iloc[10], errors="coerce"),
            "Life PI": pd.to_numeric(r.iloc[11], errors="coerce"),
            "7-yr variability": pd.to_numeric(r.iloc[12], errors="coerce"),
            "Weather-explained share": pd.to_numeric(r.iloc[14], errors="coerce"),
            "7-yr degradation": pd.to_numeric(r.iloc[15], errors="coerce"),
            "Post-7 degradation": pd.to_numeric(r.iloc[16], errors="coerce"),
            "Early slope": pd.to_numeric(r.iloc[17], errors="coerce"),
            "Early intercept": pd.to_numeric(r.iloc[18], errors="coerce"),
            "Lifetime slope": pd.to_numeric(r.iloc[19], errors="coerce"),
            "Lifetime intercept": pd.to_numeric(r.iloc[20], errors="coerce"),
            "Years of data": pd.to_numeric(r.iloc[21], errors="coerce"),
        }
        # Actual annual PI history from the chart source range W:AM.
        for year in range(1, 18):
            rec[f"year_{year}"] = pd.to_numeric(r.iloc[22 + year - 1], errors="coerce") if 22 + year - 1 < len(r) else np.nan
        # Cached best-fit values from the chart source range AO:BE. These are read directly
        # so the app follows the spreadsheet chart ranges instead of recomputing visually similar lines.
        for year in range(1, 18):
            rec[f"fit_year_{year}"] = pd.to_numeric(r.iloc[40 + year - 1], errors="coerce") if 40 + year - 1 < len(r) else np.nan
        # High/low weather-variability bands at BG:BW and BY:CO. Only populated for one
        # system, so the app computes the band where they are blank.
        for year in range(1, 18):
            rec[f"high_year_{year}"] = pd.to_numeric(r.iloc[58 + year - 1], errors="coerce") if 58 + year - 1 < len(r) else np.nan
            rec[f"low_year_{year}"] = pd.to_numeric(r.iloc[76 + year - 1], errors="coerce") if 76 + year - 1 < len(r) else np.nan
        records.append(rec)
    df = pd.DataFrame(records)
    return df


def get_pr_analysis(pr_raw: pd.DataFrame) -> pd.DataFrame:
    """Performance ratio versus estimated module temperature, with the correction factor
    and the original and corrected performance index for each system."""
    if pr_raw is None or pr_raw.empty:
        return pd.DataFrame()
    rows = pr_raw.iloc[6:106, :18].copy()
    records = []
    for _, r in rows.iterrows():
        if pd.isna(r.iloc[0]) or pd.isna(r.iloc[2]):
            continue
        records.append({
            "Line#": pd.to_numeric(r.iloc[0], errors="coerce"),
            "EIA#": pd.to_numeric(r.iloc[1], errors="coerce"),
            "Name": r.iloc[2],
            "Module type": r.iloc[3],
            "Type": r.iloc[4],
            "Slope/Tilt": pd.to_numeric(r.iloc[5], errors="coerce"),
            "State": r.iloc[6],
            "Lat": pd.to_numeric(r.iloc[7], errors="coerce"),
            "Long": pd.to_numeric(r.iloc[8], errors="coerce"),
            "Estim. Tmod": pd.to_numeric(r.iloc[9], errors="coerce"),
            "PR": pd.to_numeric(r.iloc[10], errors="coerce"),
            "PI with Tmod correction": pd.to_numeric(r.iloc[11], errors="coerce"),
            "Tmod correction": pd.to_numeric(r.iloc[12], errors="coerce"),
            "PI original": pd.to_numeric(r.iloc[13], errors="coerce"),
        })
    df = pd.DataFrame(records)
    if not df.empty:
        df["PI change"] = df["PI with Tmod correction"] - df["PI original"]
    return df


def get_pr_analysis_summary(pr_raw: pd.DataFrame) -> Dict[str, float]:
    """Set-level average module temperatures and median PI before/after correction."""
    out: Dict[str, float] = {}
    if pr_raw is None or pr_raw.empty:
        return out
    try:
        out["set_a_tmod"] = float(pd.to_numeric(pr_raw.iat[2, 1], errors="coerce"))
        out["set_b_tmod"] = float(pd.to_numeric(pr_raw.iat[3, 1], errors="coerce"))
        out["median_pi_corrected"] = float(pd.to_numeric(pr_raw.iat[3, 11], errors="coerce"))
        out["median_pi_original"] = float(pd.to_numeric(pr_raw.iat[3, 13], errors="coerce"))
    except Exception:
        pass
    return out


def get_age_table(plant_raw: pd.DataFrame) -> pd.DataFrame:
    """Operating-age counts split by structure, stated directly at PlantData FY6:GB18."""
    if plant_raw is None or plant_raw.shape[1] <= 183:
        return pd.DataFrame()
    block = plant_raw.iloc[6:18, 180:184].copy()
    block.columns = ["Age", "Number", "Fixed-tilt", "Tracking"]
    for col in block.columns:
        block[col] = pd.to_numeric(block[col], errors="coerce")
    block = block.dropna(subset=["Age"])
    block = block[block["Number"].fillna(0) > 0].reset_index(drop=True)
    return block


def get_tmy_locations(states25_raw: pd.DataFrame) -> pd.DataFrame:
    """Unique TMY locations used across both data sets, from States25 J31:J85."""
    if states25_raw is None or states25_raw.shape[1] <= 9:
        return pd.DataFrame()
    block = states25_raw.iloc[31:, [8, 9]].copy()
    block.columns = ["#", "TMY location"]
    block["#"] = pd.to_numeric(block["#"], errors="coerce")
    block = block.dropna(subset=["TMY location"])
    block = block[block["#"].notna()].reset_index(drop=True)
    block["#"] = block["#"].astype(int)
    return block


def build_pi_cdf(plant: pd.DataFrame, max_year: int = 16) -> pd.DataFrame:
    """Cumulative distribution of annual PI for each operating year.

    Systems are sorted worst to best PI against the increasing percentage of the fleet.
    Built from the plant table, so every point keeps its identifying fields for hover.
    """
    id_cols = [c for c in ["Name", "State", "Type", "MWp", "1st full yr"] if c in plant.columns]
    frames = []
    for year in range(1, max_year + 1):
        col = PI_COLS[year - 1]
        if col not in plant.columns:
            continue
        part = plant[id_cols + [col]].copy()
        part = part.rename(columns={col: "pi"})
        part["pi"] = pd.to_numeric(part["pi"], errors="coerce")
        part = part.dropna(subset=["pi"]).sort_values("pi", kind="mergesort").reset_index(drop=True)
        count = len(part)
        if count == 0:
            continue
        part["Operating year"] = year
        part["rank"] = np.arange(1, count + 1)
        # Match the workbook's plotting positions: (rank - 0.5) / n.
        part["Cumulative fraction"] = (part["rank"] - 0.5) / count
        part["Systems in year"] = count
        frames.append(part)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def pi_cdf_median_trend(cdf: pd.DataFrame) -> Dict[str, float]:
    """Median PI by operating year and the fitted decline across the CDF family."""
    if cdf is None or cdf.empty:
        return {}
    medians = cdf.groupby("Operating year")["pi"].median()
    if len(medians) < 2:
        return {}
    slope, intercept = np.polyfit(medians.index.to_numpy(float), medians.to_numpy(float), 1)
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "first_year_median": float(medians.iloc[0]),
        "last_year_median": float(medians.iloc[-1]),
        "first_year": int(medians.index[0]),
        "last_year": int(medians.index[-1]),
    }


def get_overlap_stats(null_raw: pd.DataFrame) -> Dict[str, float]:
    """Overlap area, crossover PI, and the two set statistics from NullOverlap.

    Summary values are located by scanning for their labels rather than by fixed cell.
    """
    out: Dict[str, float] = {}
    if null_raw is None or null_raw.empty:
        return out
    try:
        out["set_a_pi7"] = float(pd.to_numeric(null_raw.iat[3, 1], errors="coerce"))
        out["set_a_stdev"] = float(pd.to_numeric(null_raw.iat[3, 2], errors="coerce"))
        out["set_b_pi7"] = float(pd.to_numeric(null_raw.iat[4, 1], errors="coerce"))
        out["set_b_stdev"] = float(pd.to_numeric(null_raw.iat[4, 2], errors="coerce"))
    except Exception:
        pass

    # Locate the labelled summary lines in the explanatory column and read the value
    # recorded a few rows below each label.
    labels = null_raw.iloc[:, 5]
    for row_idx, raw_text in labels.items():
        if not isinstance(raw_text, str):
            continue
        lowered = raw_text.lower()
        if "equal probability" in lowered:
            out["crossover_pi"] = float(pd.to_numeric(null_raw.iat[row_idx + 1, 5], errors="coerce"))
        elif lowered.startswith("the total area common"):
            out["overlap_area"] = float(pd.to_numeric(null_raw.iat[row_idx + 1, 8], errors="coerce"))
        elif lowered.startswith("so the chance that these are different"):
            out["non_overlap_area"] = float(pd.to_numeric(null_raw.iat[row_idx + 1, 8], errors="coerce"))
    return {k: v for k, v in out.items() if v == v}


def build_workbook_plot_tables(raw_sheets: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    plant_raw = raw_sheets["PlantData"]
    states25 = raw_sheets["States25"]
    null_overlap = raw_sheets["NullOverlap"]

    percentile_parts: List[pd.DataFrame] = [
        _series_from_cells(plant_raw, "BA218", "BB215:BQ215", "BB218:BQ218"),
        _series_from_cells(plant_raw, "BA109", "BB215:BQ215", "BB109:BQ109"),
        _series_from_cells(plant_raw, "BA113", "BB215:BQ215", "BB113:BQ113"),
    ]
    # The revised workbook adds a statistical p10 row to sit alongside the existing
    # statistical p90, so the high case now has both an observed and a fitted version.
    if plant_raw.shape[0] > 218:
        try:
            percentile_parts.append(
                _series_from_cells(plant_raw, "BA219", "BB215:BQ215", "BB219:BQ219")
            )
        except Exception:
            pass
    percentile = pd.concat(percentile_parts, ignore_index=True)

    p90_p50_split = pd.concat([
        _series_from_cells(plant_raw, None, "BB6:BH6", "BB107:BH107").assign(series="Years 1 to 7"),
        _series_from_cells(plant_raw, None, "BH6:BQ6", "BH107:BQ107").assign(series="Years 7 to 16"),
    ], ignore_index=True)

    p90_p50_full = pd.concat([
        _series_from_cells(plant_raw, None, "BB6:BQ6", "BB108:BQ108").assign(series="Empirical P90 downside / median"),
        _series_from_cells(plant_raw, None, "BB6:BQ6", "BB107:BQ107").assign(series="Statistical P90 downside / median (1.28σ)"),
    ], ignore_index=True)

    piecewise = pd.concat([
        _series_from_cells(plant_raw, "BA4", "BB6:BQ6", "BB4:BQ4").assign(series="Median PI"),
        _series_from_cells(plant_raw, "BA2", "BB6:BQ6", "BB2:BQ2").assign(series="P90 statistical PI"),
        _series_from_cells(plant_raw, None, "BB6:BH6", "BB4:BH4").assign(series="Median trend, years 1 to 7"),
        _series_from_cells(plant_raw, None, "BH6:BQ6", "BH4:BQ4").assign(series="Median trend, years 7 to 16"),
        _series_from_cells(plant_raw, None, "BB6:BH6", "BB2:BH2").assign(series="P90 trend, years 1 to 7"),
        _series_from_cells(plant_raw, None, "BH6:BQ6", "BH2:BQ2").assign(series="P90 trend, years 7 to 16"),
    ], ignore_index=True)

    # Column K is a 'Min density' envelope: the smaller of the two density curves at each
    # PI value, tracing the area the two distributions have in common.
    null_df = pd.concat([
        _series_from_cells(null_overlap, "I1", "F4:F23", "I4:I23"),
        _series_from_cells(null_overlap, "J1", "F4:F23", "J4:J23"),
    ], ignore_index=True)

    null_overlap_band = _series_from_cells(null_overlap, None, "F4:F23", "K4:K23").assign(
        series="Overlapping area"
    )

    return {
        "fleet_percentiles": percentile,
        "p90_p50_split": p90_p50_split,
        "p90_p50_full": p90_p50_full,
        "piecewise_trends": piecewise,
        "temperature_hist": pd.DataFrame(),
        "null_overlap": null_df,
        "null_overlap_band": null_overlap_band,
    }
