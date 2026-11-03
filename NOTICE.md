# Project provenance

The current English desktop edition is in [`caelo-bme/`](caelo-bme/README.md).
It integrates the Apache-2.0 Caelo host with the owner's BME Research Agent tools.
See [`caelo-bme/BME-NOTICE.md`](caelo-bme/BME-NOTICE.md) and the preserved
[`caelo-bme/LICENSE`](caelo-bme/LICENSE) for the applicable, distinct licensing status.
The BME donor and legacy root code have no explicit reuse license in this source;
publishing them does not automatically extend Caelo's license to those portions.

The legacy v0.5.1 implementation remains at the repository root. Its original code,
tests and sample fixtures are retained. The new interface and runtime have their own
entry point, dependencies and checks inside `caelo-bme/`.

The owner authorized the real-experiment result figures. Raw source workbooks,
prepared tables, private profiles and record-level export bundles are excluded.
See [`REAL-DATA-METHOD.md`](caelo-bme/docs/demo/REAL-DATA-METHOD.md).
