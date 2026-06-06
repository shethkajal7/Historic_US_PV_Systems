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
        "Exclusions": pd.read_excel(path, sheet_name="Exclusions", header=None, engine="openpyxl"),
        "NullOverlap": pd.read_excel(path, sheet_name="NullOverlap", header=None, engine="openpyxl"),
        "DetailOfP50": pd.read_excel(path, sheet_name="DetailOfP50", header=None, engine="openpyxl"),
    }

    return {
        "plant": plant,
        "newer25": newer25,
        "consolidated": consolidated,
        "comparison_raw": comparison,
        "states_raw": states,
        "raw_sheets": raw_sheets,
        "detail_p50": get_detail_p50(raw_sheets["DetailOfP50"]),
    }


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

    # The Comparison sheet pulls its degradation values from PlantData BR1/BW1, which use
    # an SLD-based formula that does not match the piecewise linest slopes shown in the charts.
    # Override the three degradation rows with the correct medians computed directly from the
    # per-system linest slope columns in PlantData (col 143 = 7-yr degr, col 146 = post-7-yr degr)
    # and from Newer25 (col 82 = Lifetime Degr, which equals the 7-yr slope for Set B).
    try:
        plant_raw = pd.read_excel(path, sheet_name="PlantData", header=None, engine="openpyxl")
        newer25_raw = pd.read_excel(path, sheet_name="Newer25", header=None, engine="openpyxl")

        seta_7yr = pd.to_numeric(plant_raw.iloc[6:106, 143], errors="coerce").median()
        seta_post7 = pd.to_numeric(plant_raw.iloc[6:106, 146], errors="coerce").median()
        setb_7yr = pd.to_numeric(newer25_raw.iloc[6:31, 82], errors="coerce").median()

        for idx, row in left.iterrows():
            metric = str(row["Metric"]).strip()
            if metric == "Degr, first 7 yrs":
                left.at[idx, "Set A"] = seta_7yr
                left.at[idx, "Set B"] = setb_7yr
            elif metric == "Degr, beyond 7 yrs":
                left.at[idx, "Set A"] = seta_post7
    except Exception:
        pass

    return left


def get_state_counts(states_raw: pd.DataFrame) -> pd.DataFrame:
    state = states_raw.iloc[1:, [1, 2]].copy()
    state.columns = ["State", "Count"]
    state = state[state["State"].notna()]
    state["Count"] = pd.to_numeric(state["Count"], errors="coerce")
    return state.dropna(subset=["Count"]).reset_index(drop=True)



def get_detail_p50(detail_raw: pd.DataFrame) -> pd.DataFrame:
    """Parse the representative median-system variability table from DetailOfP50."""
    rows = detail_raw.iloc[5:10, :57].copy()
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
        records.append(rec)
    df = pd.DataFrame(records)
    return df


def build_workbook_plot_tables(raw_sheets: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    plant_raw = raw_sheets["PlantData"]
    states25 = raw_sheets["States25"]
    exclusions = raw_sheets["Exclusions"]
    null_overlap = raw_sheets["NullOverlap"]

    percentile_parts: List[pd.DataFrame] = [
        _series_from_cells(plant_raw, "BA218", "BB215:BQ215", "BB218:BQ218"),
        _series_from_cells(plant_raw, "BA109", "BB215:BQ215", "BB109:BQ109"),
        _series_from_cells(plant_raw, "BA113", "BB215:BQ215", "BB113:BQ113"),
    ]
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

    agua_fria = _series_from_cells(exclusions, None, "I2:AE2", "I5:AE5").assign(series="Agua Fria PI")

    null_df = pd.concat([
        _series_from_cells(null_overlap, "L1", "I4:I17", "L4:L17"),
        _series_from_cells(null_overlap, "M1", "I4:I17", "M4:M17"),
    ], ignore_index=True)

    return {
        "fleet_percentiles": percentile,
        "p90_p50_split": p90_p50_split,
        "p90_p50_full": p90_p50_full,
        "piecewise_trends": piecewise,
        "temperature_hist": pd.DataFrame(),
        "agua_fria": agua_fria,
        "null_overlap": null_df,
    }
