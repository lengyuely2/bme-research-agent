# CLICK SA real-data demo: method and publication scope

The published figures use the owner's previously supplied **real experiment**, not synthetic measurements. They were exported by the application's own fixed local analysis engine. No live GPT call was needed. The example presents scientific result figures and their analysis method.

## Source and reconciliation

- Private CLICK SA Spark Excel workbook, worksheet `Result sheet`.
- Original SHA-256: `0df82787671ad7e8d631cb54c6e11afb503c16f88d6539376d9bcfcfc1440b5d`.
- 32 physical wells A1-D8, 100 recorded cycles per well: **3,200 measurements**.
- Every prepared measurement was reconciled to the original well, source cell, signal, and actual timestamp. Source SHA-256 remained unchanged.
- All 32 endpoints were checked against the arithmetic mean of each well's **final five recorded cycles**. This preserves the previously defined method; it is not an optimized clinical endpoint.

## Experimental mapping

| Plate column | Supplied concentration | Physical wells |
| --- | ---: | --- |
| 1 | 0 | A1-D1 |
| 2 | 10 | A2-D2 |
| 3 | 100 | A3-D3 |
| 4 | 1,000 | A4-D4 |
| 5 | 10,000 | A5-D5 |
| 6 | 100,000 | A6-D6 |
| 7 | 1,000,000 | A7-D7 |
| 8 | 10,000,000 | A8-D8 |

The owner supplied this sequence. **Concentration units were not provided. Biological independence is not established.** Four physical wells do not establish four independent biological samples. Signal is displayed in arbitrary units, matching the prepared signal field rather than inferring absolute calibration.

## Analysis

Code path: `Dataset.load` → `workflow.review` → `workflow.render` / `workflow.export_zip` in `caelo_core/bme/engine`.

1. **Endpoint:** all 32 well endpoints; individual points, mean and sample SD at eight categorical concentration levels. The categorical axis does not represent equal numeric concentration distances.
2. **Full kinetics:** all 3,200 readings; actual elapsed minutes; mean and sample SD over four physical wells per cycle and concentration. Requested instrument intervals are not substituted for actual timestamps.
3. **Four wells:** all 400 readings from A4-D4 at concentration 1,000. One trace per well; SD for a single observation is unavailable and not plotted as zero uncertainty.

**Zero exclusions** in all three analyses. No smoothing, interpolation, significance tests, curve fitting, or trend-driven filtering. A prior exploratory spike flag is not treated as proof of instrument error. The observed non-monotonic concentration response is retained.

## Publication scope

Public: three derived scientific plots (endpoint response, full kinetics, and four individual wells) and this method note. Private: original workbook, prepared CSVs, per-record audit JSON/ZIP, local profile, credentials, and conversations. Full export bundles were verified locally but contain record-level data and are not published.

Synthetic CSV/PDF fixtures elsewhere in the source support tests and optional examples; they are **not** the source of these experimental figures. Without the owner's private data, readers can inspect methods and code but cannot independently reproduce these particular values. No clinical diagnostic conclusions are made.
