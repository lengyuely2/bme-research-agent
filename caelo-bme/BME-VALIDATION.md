# Local validation / 本地验证

Date: 2026-11-02. Windows, Python 3.12.7, Node 24.22.1, Electron 45.2.1.
Host snapshot: Caelo `5de4a43b94692c0122b135bd61b0f458ddd16971`.
Local branch: `bme-research`.

## Automated checks

- **22 Python checks passed**: 14 BME integration cases (including four approval-mode
  variants), plus 8 upstream OpenAI adapter/error checks.
- **29 frontend checks passed**: BME workflow/IME/session/HTML/key-field regressions,
  plus Caelo agent-client, session reconstruction, credential vault and authenticated
  request-bridge checks.
- TypeScript node + web checks passed; targeted ESLint completed without warnings;
  Electron main/preload and React production build completed.
- TestClient emits one upstream deprecation warning about httpx; it does not affect
  the application request transport.

## What was exercised

- Real local synthetic CSV inspection, known blank mean `0.04` and sample SD `0.01`,
  15 observations / 5 groups / 3 independent synthetic replicates per group.
- Plan validation, exclusion-reason rejection, unique PNG/ZIP outputs, SVG and audit
  content in ZIP, unchanged source SHA-256, PDF physical-page reading and rasterization.
- Live local monitor thread: stable new synthetic PNG event, metadata-only result,
  one-time event delivery, stop and restart without orphaned monitor threads.
- Absolute/traversal/hardlink reads, overlapping source/output roots, unknown tool
  calls, native file/shell/web/delegate/MCP/LSP requests rejected, including bypass mode.
- Generic write/terminal/git/hook/plugin/undo HTTP routes absent; REST/WS auth remains
  fail-closed. A model cannot grant itself those capabilities through its response.
- Actual Caelo agent loop + OpenAI adapter + mocked Responses SSE + actual BME tool
  execution over authenticated WebSocket. New account-returned model ID accepted
  without needing a release-time catalog entry. Tool output fed back into the next
  request; `store:false`; conversation saved and loaded without an API-key marker.
- Normal Enter sends once without a confirmation modal; Chinese IME composition
  does not submit. Updating a mapped column invalidates the old export action.
- Restoring old history does not authorize its former source directory.
- Model-generated HTML remains code; renderer CSP blocks remote images, scripts
  and frames. API-key field clears after saving even if model lookup then fails.
- Manual balance persists with source/time; invalid/infinite/negative values rejected;
  unknown balance stays unknown and token usage never alters the recorded amount.

## Native graphical checks

The real compiled Electron app and Python sidecar were opened locally, including
through `Open-Caelo-BME.vbs`. The home page connects to the sidecar. In the GUI,
the synthetic biosensor CSV was inspected, previewed and exported to a new PNG and
ZIP; PDF page 1 displayed `[paper_demo.pdf-P001]` with the expected synthetic text.
The native folder picker connected the dedicated synthetic watch folder. After starting
monitoring, a new 32×32 PNG appeared automatically as `synthetic-ui-watch.png`
(116 bytes); Stop returned to the idle state. No model call was made.
Screenshots contain only this app and synthetic fixtures.

## Limits of this validation

- No real API key was read from another app, entered by the agent, or sent to OpenAI.
  Real account quota, billing, specific models, live cloud tool reasoning and vision
  still require the user to connect their own key in the new GUI.
- There is no general software automation or arbitrary code execution in this build.
  Code files are drafts only. Analysis presets do not implement every BME method.
- This is a local development integration, not a signed installer or a full security
  audit. Electron was updated from the host's 42.x declaration to 45.2.1. The inherited
  build/test dependency tree still has npm advisories (including dev tooling);
  public packaging needs dependency remediation and separate release verification.
- Application-level path checks are not an OS sandbox and do not protect against a
  malicious process running as the same Windows user. Local session history may
  contain document text and image previews the user asked the model to read.
- BME donor redistribution licensing is separately documented in `BME-NOTICE.md`.
  This fork was not pushed or published.

## Version 0.1.1 — English interface and real-data walkthrough

The earlier native checks describe the original v0.1 synthetic-fixture session.
For v0.1.1, visible BME labels, settings, errors, analysis notes, and exports are English.
Chinese input aliases and multilingual chat remain supported. The English native home
was visually checked. Desktop interaction was then stopped by the user's Escape key;
no further UI automation was performed. This video is an edited analysis walkthrough.

The demo uses owner-provided real CLICK SA data. The original workbook stayed unchanged;
all 3,200 prepared readings and 32 final-five-cycle endpoints were reconciled. The app's
engine generated endpoint, kinetics, and four-well figures, with zero exclusions.
PNG/SVG and full local audit ZIPs were produced; record-level bundles remain private.
Units and biological independence are unconfirmed. The English video has an app home
capture, actual scientific figures, explanation cards, offline narration, and WebVTT.
It decoded successfully end-to-end (174.49 seconds, H.264/AAC).

23 Python tests, 29 frontend tests, both TypeScript projects, changed-file ESLint,
and the production build passed. Python compileall passed. One existing Starlette/httpx
deprecation warning was observed. No live OpenAI key, billing query, model access,
vision response, or real cloud tool reasoning was tested.

The owner authorized public source publication and the reviewed real-data demo.
This supersedes the earlier local-only status, without assigning a new BME license.
See BME-NOTICE.md and docs/demo/REAL-DATA-METHOD.md.
