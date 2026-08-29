from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from data_loader import (
    load_workbook_tables, build_annual_long, summary_metrics, top_stats_table,
    temperature_histogram_table, get_comparison_table, get_state_counts,
    build_workbook_plot_tables, get_pr_analysis_summary, pi_cdf_median_trend
)
from charts import (
    pi_rank_chart, pi_distribution_by_type, degradation_scatter, annual_pi_cone,
    age_distribution_chart, age_table_chart, state_count_chart, site_actual_chart,
    site_pi_chart, workbook_line_chart, workbook_ratio_chart,
    temperature_comparison_chart, null_overlap_chart, variability_middle_systems_chart,
    variability_single_system_chart, piecewise_pi_trend_chart, pi_cdf_chart,
    pr_vs_temperature_chart, pi_temperature_adjustment_chart
)
from map_view import make_cluster_map

st.set_page_config(page_title="Oldest 100 U.S. PV Systems", page_icon="☀️", layout="wide")

@st.cache_data(show_spinner=False)
def get_data():
    tables = load_workbook_tables()
    actual_long, pi_long = build_annual_long(tables["plant"])
    tables["actual_long"] = actual_long
    tables["pi_long"] = pi_long
    tables["summary"] = summary_metrics(tables["plant"])
    tables["top_stats"] = top_stats_table(tables["plant"], tables["newer25"])
    tables["comparison"] = get_comparison_table(tables["comparison_raw"])
    tables["state_counts"] = get_state_counts(tables["states_raw"])
    tables["workbook_plots"] = build_workbook_plot_tables(tables["raw_sheets"])
    tables["workbook_plots"]["temperature_hist"] = temperature_histogram_table(
        tables["plant"], tables["newer25"]
    )
    tables["pr_summary"] = get_pr_analysis_summary(tables["raw_sheets"]["PRanalysis"])
    tables["cdf_trend"] = pi_cdf_median_trend(tables["pi_cdf"])
    return tables


def format_pct(x, decimals: int = 1):
    try:
        return f"{x:.{decimals}%}"
    except Exception:
        return "n/a"


def format_decimal(x, decimals: int = 2):
    try:
        return f"{x:.{decimals}f}"
    except Exception:
        return "n/a"


def _short_value(metric, value):
    import pandas as pd
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return "" if pd.isna(value) else value
    metric_text = str(metric).lower()
    if "degr" in metric_text or metric_text.startswith("%") or "clip" in metric_text or "tracking" in metric_text or "hot" in metric_text or "cold" in metric_text:
        # Degradation values are stored as negative slopes; display as positive (absolute) percentages.
        if "degr" in metric_text:
            return f"{abs(num):.1%}"
        return f"{num:.1%}"
    if "pi" in metric_text or "std deviation" in metric_text or "ilr" in metric_text or "df" in metric_text:
        return f"{num:.2f}"
    if "poa" in metric_text:
        return f"{num:.1f}"
    if "mwp" in metric_text or "years" in metric_text:
        return f"{num:.1f}"
    return f"{num:.2f}"


def display_comparison_table(df):
    shown = df.copy()
    for col in ["Set A", "Set B"]:
        if col in shown.columns:
            shown[col] = [_short_value(metric, value) for metric, value in zip(shown["Metric"], shown[col])]
    st.dataframe(shown, use_container_width=True, hide_index=True)


def rounded_for_display(df):
    out = df.copy()
    for col in out.select_dtypes(include="number").columns:
        name = str(col).lower()
        if "degr" in name or "frac" in name or "pi" in name or "percentile" in name or "clip" in name:
            out[col] = out[col].round(3)
        elif "lat" in name or "long" in name:
            out[col] = out[col].round(4)
        else:
            out[col] = out[col].round(2)
    return out


def chart_note(text: str):
    st.caption(text)


def chart_filter_panel(
    plant,
    key: str,
    label: str = "Chart filters",
    row_control: dict | None = None,
):
    """Return a plant subset using local chart-level filters.

    When row_control is provided, also place the row-count slider inside
    the same chart/table control panel so it is easy to find.
    """
    row_value = None
    with st.container(border=True):
        st.markdown(f"**{label}**")
        if row_control:
            c1, c2, c3 = st.columns([1.15, 1.15, 0.85])
        else:
            c1, c2 = st.columns(2)
            c3 = None
        states = c1.multiselect(
            "State", sorted(plant["State"].dropna().unique()), key=f"{key}_states"
        )
        types = c2.multiselect(
            "Structure", sorted(plant["Type"].dropna().unique()), key=f"{key}_types"
        )
        if row_control and c3 is not None:
            row_value = c3.slider(
                row_control.get("label", "Rows shown"),
                row_control.get("min_value", 10),
                row_control.get("max_value", 100),
                row_control.get("value", 30),
                row_control.get("step", 5),
                key=f"{key}_rows",
            )
    subset = plant.copy()
    if states:
        subset = subset[subset["State"].isin(states)]
    if types:
        subset = subset[subset["Type"].isin(types)]
    if subset.empty:
        st.warning("No sites match these chart filters. Clear one selection or choose a broader combination.")
        subset = plant.iloc[0:0].copy()
    if row_control:
        return subset, row_value
    return subset


def main():
    st.title("America’s 100 Oldest Utility-Scale and Distributed PV Systems")
    st.caption(
        "Interactive analysis of the oldest 100 U.S. PV systems, as drawn primarily "
        "from the Energy Information Administration (EIA) "
        "https://www.eia.gov/beta/electricity/data/browser/. Use the chart-level "
        "filters to explore performance by geography and system structure."
    )

    st.markdown(
        '<p class="attrib">This webpage was created and co-authored by '
        '<b>Tim Townsend</b>, <b>Kajal Sheth</b>, <b>Kenneth Sauer</b> 😊</p>',
        unsafe_allow_html=True
    )

    tables = get_data()
    plant = tables["plant"]
    consolidated = tables["consolidated"]
    actual_long = tables["actual_long"]
    pi_long = tables["pi_long"]
    summary = tables["summary"]
    workbook_plots = tables["workbook_plots"]
    detail_p50 = tables.get("detail_p50")
    pr_analysis = tables.get("pr_analysis")
    age_table = tables.get("age_table")
    tmy_locations = tables.get("tmy_locations")
    pi_cdf = tables.get("pi_cdf")
    cdf_trend = tables.get("cdf_trend", {})
    overlap_stats = tables.get("overlap_stats", {})
    pr_summary = tables.get("pr_summary", {})

    tabs = st.tabs(["Summary", "Map", "Performance", "Site Drilldown", "Data Tables"])

    with tabs[0]:
        st.subheader("Top Statistics by Sample")
        top_stats_display = tables["top_stats"].copy()
        if "Set" in top_stats_display.columns:
            top_stats_display["Set"] = top_stats_display["Set"].replace({
                "Set A": "Set A - typical start 2010",
                "Set B": "Set B - all started 2018",
            })
        st.dataframe(
            top_stats_display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Sites": st.column_config.NumberColumn(format="%d"),
                "MWp": st.column_config.NumberColumn(format="%d"),
                "MWac": st.column_config.NumberColumn(format="%d"),
            },
        )

        st.subheader("Fleet Summary Comparison")
        display_comparison_table(tables["comparison"])
        if pr_summary.get("median_pi_original") and pr_summary.get("median_pi_corrected"):
            chart_note(
                "Expected energy is adjusted for the module temperature each system actually "
                "operates at, so that hot and cold climates are compared on a more even footing. "
                f"This moves the median lifetime PI from {pr_summary['median_pi_original']:.3f} "
                f"to {pr_summary['median_pi_corrected']:.3f} and shifts individual rankings. The "
                "Finding column above predates this adjustment: the hot-versus-cold difference in "
                "seven-year PI is now about 2.5 percentage points, though a wider gap remains "
                "over full lifetimes."
            )
        st.info("Set A is the 100 longest-running PV systems in the EIA database. Set B is a random set of 25 PV systems that began operating in 2018. This comparison is offered to show how the performance over the first seven years of the older set compares to the initial seven years, approximately, of the newer sample. Since most of the older set began in about 2010, there is an eight-year industry evolution that takes place in terms of equipment, design practice, developers, and locale. The most notable shift over the eight years between these samples is the inverter loading ratio, or ILR, often equivalently called the dc:ac ratio. In the older set, the median and average ILRs were 1.12 and 1.18, respectively. With ILRs this low, there is very little energy sacrificed due to clipping in this older set of 100. It is nearly negligible. However, in the newer set, the median ILR of 1.33 and the average ILR of 1.25 suggest the typical clipping loss for the newer systems has been in excess of 2% per year. Clipping hides part of the otherwise noticeable degradation, making high-ILR systems appear to be more stable than an otherwise identical system with a lower ILR and no clipping.")
        st.plotly_chart(state_count_chart(tables["state_counts"]), use_container_width=True)
        st.info("The taller layout keeps every state label readable in print or exported screenshots.")
        

    with tabs[1]:
        st.subheader("Clustered Site Map")
        map_filtered = chart_filter_panel(plant, "map", "Map filters")
        st.write("Nearby points are clustered automatically. Use the layer selector on the map to switch between the light basemap and satellite imagery. Satellite mode includes optional place and road labels where tile coverage is available. Cluster colors reflect marker density: green clusters contain fewer nearby systems, while yellow/orange clusters contain more systems. As you zoom in, larger clusters split into smaller clusters or individual sites.")
        st_folium(make_cluster_map(map_filtered), height=650, use_container_width=True)

    with tabs[2]:
        st.subheader("Fleet Performance")

        rank_filtered, show_rows = chart_filter_panel(
            plant,
            "rank",
            "Ranking chart filters",
            row_control={
                "label": "Rows shown",
                "min_value": 10,
                "max_value": 100,
                "value": 30,
                "step": 5,
            },
        )
        rank_names = set(rank_filtered["Name"].dropna())
        rank_table = consolidated[consolidated["Name"].isin(rank_names)] if "Name" in consolidated.columns else consolidated
        st.plotly_chart(pi_rank_chart(rank_table.head(show_rows), rows=show_rows), use_container_width=True)
        chart_note("This ranking highlights the strongest lifetime performers. Sites at the top are good models for investigating what design choices and O&M practices have been used and are worth replicating, especially if the poorer-performing systems are marked by readily identifiable differences in equipment and O&M. The rankings here assume an allowed 0.5%/year degradation for all systems.")

        if age_table is not None and not age_table.empty:
            # The revised workbook states the operating-age counts directly, split by
            # structure, so this chart reads them instead of recomputing ages. Because
            # the counts are fleet-wide totals, the chart-level filters do not apply.
            latest_year = None
            if not actual_long.empty and "calendar_year" in actual_long.columns:
                latest_year = int(pd.to_numeric(actual_long["calendar_year"], errors="coerce").max())
            st.plotly_chart(age_table_chart(age_table, latest_year), use_container_width=True)
            chart_note("The age distribution shows how many systems fall into each operating-age range based on the EIA's latest available production year, typically through 2024 as of the time of this analysis. Only four of the 100 systems have logged at least 17 years, and only one has been operating longer than 17 years, though all 100 have logged at least 12 years. Just under half of the sample has amassed an operating history of 14 to 15 years. Bars are split into fixed-tilt and tracking. This chart always shows the full fleet and is not affected by the chart filters.")
        else:
            age_filtered = chart_filter_panel(plant, "age", "Age distribution filters")
            st.plotly_chart(age_distribution_chart(age_filtered, actual_long), use_container_width=True)
            chart_note("The age distribution shows how many systems fall into each operating-age range based on the EIA's latest available production year, typically through 2024 as of the time of this analysis. Only four of the 100 systems have logged at least 17 years, and only one has been operating longer than 17 years, though all 100 have logged at least 12 years. Just under half of the sample has amassed an operating history of 14 to 15 years.")

        dist_filtered = chart_filter_panel(plant, "dist", "PI and degradation chart filters")
        st.plotly_chart(pi_distribution_by_type(dist_filtered), use_container_width=True)
        chart_note("The two box plots show the lifetime PI for fixed-tilt, about two-thirds of the 100 systems, and tracking, about one-third of the 100 systems, structures. The boxes show the median line, bounded on the high and low sides by the middle quartiles. The whiskers represent the extent to which the observed data points fit within 1.5 times the adjoining interquartile range. Points beyond the whiskers may be viewed as outliers.")
        st.plotly_chart(degradation_scatter(dist_filtered), use_container_width=True)
        chart_note("This scatter plot checks whether high lifetime PI sites also show lower calculated degradation. Points far from the central trend deserve site-level review because they may reflect outages, data gaps, clipping, soiling, or site-specific operating constraints.")

        pi_filtered = chart_filter_panel(plant, "annual_pi", "Annual PI curve filters")
        filtered_pi_long = pi_long[pi_long["Name"].isin(pi_filtered["Name"])]
        st.plotly_chart(annual_pi_cone(filtered_pi_long), use_container_width=True)
        chart_note("This annual PI chart recalculates the P10, P50, P90, and average curves from the selected sites. The straight-line fits are limited to operating years 1 through 16 because only four systems have data beyond year 16, making later-year fitted slopes unreliable.")

        st.divider()
        st.subheader("PI Probability Distribution by Operating Year")
        if pi_cdf is None or pi_cdf.empty:
            # Previously this whole section was skipped when the table was missing, which
            # made a stale cache or an out-of-date deployment look like the chart had never
            # been added. Failing visibly makes that situation obvious instead.
            st.error(
                "This section did not load. If the app was recently updated, clear the cache "
                "from the menu in the upper right and reload the page."
            )
        else:
            cdf_filtered = chart_filter_panel(plant, "cdf", "PI distribution chart filters")
            cdf_names = set(cdf_filtered["Name"].dropna())
            cdf_subset = pi_cdf[pi_cdf["Name"].isin(cdf_names)]
            st.plotly_chart(pi_cdf_chart(cdf_subset), use_container_width=True)
            trend_text = ""
            if cdf_trend:
                trend_text = (
                    f" At the p50 line, the median PI falls from about "
                    f"{cdf_trend['first_year_median']:.2f} in year {cdf_trend['first_year']} to "
                    f"{cdf_trend['last_year_median']:.2f} by year {cdf_trend['last_year']}, an "
                    f"average decline of {abs(cdf_trend['slope']) * 100:.1f} PI percentage points "
                    "per year on top of the 0.5%/yr already allowed for."
                )
            chart_note(
                "For each operating year, the systems are sorted from worst to best PI and "
                "plotted against the increasing percentage of the fleet, giving a classic "
                "cumulative distribution shape. The gradual right-to-left shift of the curves "
                "illustrates the fleet's degradation." + trend_text + " The curves also soften "
                "and widen with time. Ideally the plot would be a sharp zig-zag, flat at zero "
                "until PI=1.0 and then jumping straight to 100%, but in reality the S-shape "
                "flattens out. Years 1, 4, 7, 10, 13, and 16 are drawn thicker to make the "
                "separation easier to see."
            )
            st.info(
                "Hover any point to see which system it represents. All 100 systems contribute "
                "to years 1 through 12, but only 97, 73, 41, and 24 reach years 13, 14, 15, and "
                "16, so the later curves rest on a thinner sample."
            )

        st.divider()
        st.subheader("Additional Performance Diagnostics")

        st.plotly_chart(
            workbook_line_chart(
                workbook_plots["fleet_percentiles"],
                "100 Oldest U.S. PV Systems: P10, P50, and P90 PI by Operating Year",
                "Performance Index"
            ),
            use_container_width=True,
        )
        chart_note("This percentile chart summarizes annual normalized performance by operating year. P50 represents the central system in the fleet, P10 represents the high-performance case, and P90 represents the downside or weaker-performance case. The trend equations make the direction and rate of change transparent instead of relying only on visual slope. A Gaussian p10 is also shown, estimated from the median and the annual fleet standard deviation, so the upside has both an observed and a fitted version as the downside already did.")

        st.plotly_chart(
            workbook_ratio_chart(
                workbook_plots["p90_p50_split"],
                "p90/p50 Ratio Split into Early and Later Operating Periods"
            ),
            use_container_width=True,
        )
        chart_note("This split-period view compares the ratio of the p90 downside case to the median over two distinct periods. The first seven years show a consistent ratio of about 0.74. Beyond that, the ratio of the p90 case relative to the also-declining p50 case worsens with time, by about 3.5 percentage points per year.")

        st.plotly_chart(
            piecewise_pi_trend_chart(workbook_plots["piecewise_trends"]),
            use_container_width=True,
        )
        chart_note("This chart shows the median annual PI and the p90 downside annual PI with separate best-fit lines for years 1 to 7 and years 7 to 16.")

        st.plotly_chart(
            workbook_ratio_chart(
                workbook_plots["p90_p50_full"],
                "Empirical vs. Statistical P90/Median Downside Ratio by Operating Year"
            ),
            use_container_width=True,
        )
        chart_note("This chart keeps both downside-risk definitions visible. The empirical P90 curve uses the observed 10th-percentile annual performer in the fleet. The statistical P90 curve estimates the downside case from the median using 1.28 times the annual fleet standard deviation, which produces a smoother benchmark. Because the two methods are similar but not identical, the chart is useful as a diagnostic rather than as the sole source for the final downside-risk multiplier.")

        st.plotly_chart(
            temperature_comparison_chart(
                workbook_plots["temperature_hist"],
                "Module Temperature Distribution: Set A vs. Set B"
            ),
            use_container_width=True,
        )
        chart_note("This temperature distribution compares the older and newer samples as a percentage of each sample. Set A contains 47 cold, 41 medium, and 12 hot sites; Set B contains 18 cold, 6 medium, and 1 hot site.")

        st.plotly_chart(
            null_overlap_chart(
                workbook_plots["null_overlap"],
                overlap_band=workbook_plots.get("null_overlap_band"),
            ),
            use_container_width=True,
        )
        overlap_pct = overlap_stats.get("overlap_area")
        non_overlap_pct = overlap_stats.get("non_overlap_area")
        if overlap_pct is not None and non_overlap_pct is not None:
            st.info(
                f"The estimated overlap between the older-fleet and newer-fleet distributions is "
                f"about {overlap_pct:.0%}. Interpreted simply, only about {non_overlap_pct:.0%} of "
                "the distribution area does not overlap, so the evidence that the two samples are "
                "statistically different is weak. The newer fleet median PI is slightly lower, but "
                "not with a high degree of confidence."
            )
        else:
            st.info("The estimated overlap between the older-fleet and newer-fleet distributions is about 84%. Interpreted simply, only about 16% of the distribution area does not overlap, so the evidence that the two samples are statistically different is weak. The newer fleet median PI is slightly lower, but not with a high degree of confidence.")
        chart_note("This null-overlap chart compares the early-year PI distribution of the 100 older systems against the 25 newer systems. The large overlap suggests that the newer sample should be treated as broadly comparable in early-life performance, while still recognizing that its median is modestly lower. The shaded region shows the area the two distributions have in common.")

        if pr_analysis is not None and not pr_analysis.empty:
            st.divider()
            st.subheader("Performance Ratio and Module Temperature")
            st.plotly_chart(pr_vs_temperature_chart(pr_analysis), use_container_width=True)
            chart_note("This chart relates each system's demonstrated lifetime performance ratio to its module temperature, separately for fixed-tilt and tracking structures. For fixed-tilt systems the fitted line is nearly flat, so there is little relationship. For trackers the line does decline with temperature, but the scatter around it is wide enough that the relationship is erratic rather than dependable.")
            st.plotly_chart(pi_temperature_adjustment_chart(pr_analysis), use_container_width=True)
            chart_note("Each vertical line connects one system's lifetime PI before and after the temperature adjustment. Systems running hotter than the fleet average are credited upward and cooler systems are pulled down, so the correction is close to neutral overall while still moving individual systems by up to about five percentage points.")

        if detail_p50 is not None and not detail_p50.empty:
            st.divider()
            st.subheader("Weather-Variability Context for Representative Median Systems")
            st.plotly_chart(variability_middle_systems_chart(detail_p50), use_container_width=True)
            chart_note("This chart focuses on five middle-ranked systems, ranked 48 through 52 by lifetime PI. These are intentionally representative, middle-of-the-road systems rather than best or worst cases. The plot shows their annual PI histories only; it does not display a weather-variability band.")
            selected_variability_site = st.selectbox("Select representative system for detailed POA variability view", detail_p50["Name"].dropna().tolist(), index=min(2, len(detail_p50)-1))
            st.plotly_chart(variability_single_system_chart(detail_p50, selected_variability_site), use_container_width=True)
            chart_note("The shaded bands represent normal POA variability around the fitted PI trend, using the long-term average POA basis available in this workbook. Points beyond the shaded bands suggest annual movement that is unlikely to be explained by normal weather variability alone and may reflect operations, degradation, curtailment, data quality, or equipment behavior.")

    with tabs[3]:
        st.subheader("Site-Level Detail")
        site_filter = chart_filter_panel(plant, "site", "Site selector filters")
        site = st.selectbox("Select site", sorted(site_filter["Name"].dropna().unique()))
        row = plant[plant["Name"] == site].iloc[0]
        meta_cols = ["Name", "EIA#", "State", "Sector", "Module type", "Developer", "Type", "Slope/Tilt", "MWp", "MWac", "POA (by eqn.)", "TMY2 Source", "Annual T,air", "Estim. Tmod", "DF", "Est.Clip", "Clip Frac.", "Expected", "Actual", "Lifetime PI", "Percentile Rank", "Lifetime Degr"]
        meta = row[[c for c in meta_cols if c in row.index]].to_frame("Value")
        # This column mixes text fields with numeric ones, which Arrow cannot serialize as
        # a single typed column. Rounding first, then rendering as text, keeps the table
        # readable and avoids the fallback conversion warning.
        meta = rounded_for_display(meta)
        meta["Value"] = meta["Value"].apply(lambda v: "" if pd.isna(v) else str(v))
        st.dataframe(meta, use_container_width=True)
        st.plotly_chart(site_actual_chart(actual_long, site), use_container_width=True)
        chart_note("This chart shows the selected site’s annual generation over calendar time. The dashed trendline and equation summarize the direction of production change, while individual points reveal year-specific dips that may come from downtime, curtailment, weather, or equipment performance.")
        st.plotly_chart(site_pi_chart(pi_long, site), use_container_width=True)
        chart_note("The site PI curve normalizes annual production against the expected energy. For this plot, the PI points do not make an allowance for degradation. Also, each year is compared against the same long-term average POA assumption, so true (and smoother) PIs that reflect annual irradiance variations are not captured here. The main purpose is to normalize across plant sizes and across typical fixed-versus-tracker expected yield differences. A reference near 1.0 makes it easier to judge whether the selected system is producing approximately what it is supposed to produce.")

    with tabs[4]:
        st.subheader("Data Tables")
        with st.container(border=True):
            c1, c2 = st.columns([1, 2])
            table_rows = c1.slider(
                "Rows shown in each table",
                10,
                100,
                30,
                5,
                key="data_table_rows",
            )
            #c2.caption("This control only affects the visible rows in the two data tables below. Download/export logic, if added later, should use the full source tables.")

        st.subheader("Ranked Results Table")
        st.dataframe(
            rounded_for_display(consolidated.head(table_rows)),
            use_container_width=True,
            hide_index=True,
        )
        chart_note("PI values and rank order reflect the module-temperature adjustment described on the Summary tab.")

        st.subheader("Plant-Level Data Extract Used by the App")
        display_cols = [c for c in ["Line#", "EIA#", "Name", "1st full yr", "Sector", "Module type", "Developer", "Type", "State", "Lat", "Long", "MWp", "MWac", "TMY2 Source", "Lifetime PI", "Percentile Rank", "Lifetime Degr"] if c in plant.columns]
        st.dataframe(
            rounded_for_display(plant[display_cols].head(table_rows)),
            use_container_width=True,
            hide_index=True,
        )

        if tmy_locations is not None and not tmy_locations.empty:
            st.subheader("TMY Locations Used Across Both Data Sets")
            st.dataframe(
                tmy_locations,
                use_container_width=True,
                hide_index=True,
                column_config={"#": st.column_config.NumberColumn(format="%d")},
            )
            chart_note(f"The {len(tmy_locations)} unique typical-meteorological-year locations used to build the expected-energy basis for both sets. Several systems share a location.")


if __name__ == "__main__":
    main()
