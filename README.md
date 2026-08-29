# Oldest 100 PV Systems Streamlit App

This version reproduces the workbook-derived logic using the calculated values stored in `data/100oldest.xlsx`. The public app does not allow users to upload, edit, or manipulate the source workbook.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Data

| File | Description |
| --- | --- |
| `data/100oldest.xlsx` | Current source workbook, revised to adjust expected energy for estimated module temperature. |
| `data/100oldest_pre_tmod_adj.xlsx` | Previous workbook, retained for provenance. Not read by the app. |

### About the module-temperature adjustment

The current workbook adjusts each system's expected energy for the module temperature it actually operates at, so that systems in hot and cold climates are compared on a more even footing. Actual generation and the degradation slopes are unchanged. The median lifetime PI moves from 0.878 before the adjustment to 0.867 after it. The adjustment is close to neutral across the fleet as a whole, raising the PI for about half the systems and lowering it for the other half, but it changes individual rankings noticeably.

## Main features

- Executive summary using workbook-derived Set A and Set B values
- Ranked Performance Index table
- Lifetime PI and degradation charts
- Relative-year PI spread chart with reviewer-limited trendlines through year 16
- PI cumulative distribution family by operating year, with per-system hover identification
- Performance ratio versus module temperature, split by structure
- State counts
- Clustered site map with click popups
- Site-level drilldown for metadata, annual generation, and PI trend

## Design choices

The app reads the workbook internally. It uses the workbook's existing calculated values first, rather than changing the methodology. Later versions can add EIA refresh, improved degradation models, Monte Carlo uncertainty, and additional regression methods after the workbook-matching version is approved.

There is one deliberate exception to reading values straight from the workbook. The `ConsolidatedResults` sheet was not refreshed when the module-temperature adjustment was applied, so its PI column and rank order are pre-adjustment. Leaving it alone would put the ranking chart and the ranked results table out of step with every other view. The app therefore rebuilds only the PI column and the rank order from `PlantData`, joining by system name, and leaves all other columns exactly as the workbook author curated them. The degradation slopes in that sheet are unaffected by the adjustment and are carried over untouched. See `rebuild_consolidated` in `data_loader.py`.

The PI cumulative distribution curves are likewise built from `PlantData` rather than from a separate anonymized export. The values are identical either way, but building them from the master table means every plotted point retains its system name, state, structure, and size for hover identification, the chart-level filters apply to it, and it cannot drift out of sync with the rest of the workbook.

## Workbook cell references

The app reads several chart source ranges by cell reference. If the workbook is revised again, these are the ranges to check first.

| Sheet | Range | Used for |
| --- | --- | --- |
| `PlantData` | `BB6:BQ6`, `BB215:BQ215` | Operating-year axis |
| `PlantData` | `BB2:BQ2`, `BB4:BQ4` | Statistical p90 and p50 annual PI |
| `PlantData` | `BB107:BQ107`, `BB108:BQ108` | p90/median downside ratios |
| `PlantData` | `BB109:BQ109`, `BB113:BQ113` | Median and observed p10 percentile curves |
| `PlantData` | `BB218:BQ218`, `BB219:BQ219` | Observed p10 and Gaussian p10 |
| `PlantData` | `FY6:GB18` | Operating-age counts by structure |
| `PlantData` | `BB7:BQ106` | Annual PI by system, source for the CDF family |
| `NullOverlap` | `F4:F23`, `I4:I23`, `J4:J23`, `K4:K23` | Distribution overlap, including the common-area envelope |
| `DetailOfP50` | `W:AM`, `AO:BE`, `BG:BW`, `BY:CO` | Annual PI, best-fit PI, and weather-variability bands |
| `PRanalysis` | `A6:R106` | Performance ratio versus module temperature |
| `States25` | `J31:J85` | Unique TMY locations |

## Comparison table

Every value in the Fleet Summary Comparison table is read straight from the workbook's `Comparison` sheet, so the page matches the spreadsheet cell for cell.

An earlier version overrode the three degradation rows with the median of the 100 per-system linest slopes. That override has been removed. The sheet reports the slope of the fleet median PI curve (-0.84%/yr over the first seven years), which is within 0.04 points of the piecewise chart on the same page (-0.80%/yr); the override reported the median of the individual slopes (-1.12%/yr), which is 0.32 points away from that chart. The two are different statistics, and because the distribution of per-system slopes is strongly left-skewed, the median of the slopes sits well below the slope of the median.

## Known deprecation

Streamlit reports that `use_container_width` will be replaced by `width`. The calls still work on the pinned version but will need updating on a future Streamlit release.
