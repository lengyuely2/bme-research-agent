# Caelo BME v0.1.1 — English workbench and real-data walkthrough

An English Caelo-based desktop for biosensing and disease-detection research, with GPT research assistance and fixed local data, paper, plotting, and image-watch tools. The complete current source is in `caelo-bme/`; legacy v0.5.1 remains at the repository root.

- English navigation, settings, validation messages, analysis notes, and export documentation.
- Narrated English **real CLICK SA experiment** walkthrough: 32 physical wells, 100 recorded cycles each, eight supplied concentrations, zero exclusions. Source and endpoint reconciliation completed against the unchanged private workbook.
- MP4, English WebVTT subtitles, transcript, and method note attached. The video presents an actual home capture and analysis-engine figures with explanation cards; it is not a continuous UI recording. No live GPT response is simulated.
- Read-only sources, separate unique outputs, encrypted credentials, fixed BME tool boundary, and a **manual** balance snapshot. General software control and arbitrary code execution are disabled.
- 23 focused Python tests, 29 frontend tests, typechecks, changed-file lint and build passed. The preserved legacy suite passed 145 tests. Video decoded end-to-end.

Original Excel, prepared CSV, private profiles, keys, and per-record audit bundles are **not distributed**. Concentration units and biological independence are unconfirmed. No trend-forcing exclusions or clinical diagnostic claims.

This is a **source development preview**, without a signed installer. Live account/model access was not tested and inherited dependency advisories remain. Caelo host licensing and BME donor licensing are distinct; see `NOTICE.md` and `caelo-bme/BME-NOTICE.md`. This independent project is not the official Grok web interface or an xAI model release.
