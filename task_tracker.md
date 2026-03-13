<p align="center">
  <strong>📋 M2 Task Tracker</strong>
</p>

<p align="center">
  <em>Track who is working on what — fill in Assigned & Status</em>
</p>

---

| Area | Task | Assigned | Status |
|------|------|----------|--------|


| 🧪 M2 / Pipeline | Refactor data → features → train → evaluate into reusable Python modules (no notebook-only logic) | | |
| 🧪 M2 / Pipeline | Define one command / script to run end-to-end training and write models to `models/artifacts/` | | |
| 🧪 M2 / Data Quality | Add schema checks for Kafka logs, user API, movie API, and `/recommend/<userid>` inputs | | |
| 🧪 M2 / Data Quality | Implement simple drift checks on key fields (e.g., ratings, watch events, request mix) | | |
| 🧪 M2 / Testing | Add unit tests for data parsing, feature engineering, and model utilities | | |
| 🧪 M2 / Testing | Add tests for `get_recommendations` (known user, cold-start, popularity fallback, edge cases) | | |
| 🧪 M2 / Testing | Add tests for Flask API behavior and response format (mocking user API) | | |
| ⚙️ M2 / CI | Set up CI (e.g., GitHub Actions) to install deps and run tests on each push/PR | | |
| ⚙️ M2 / CI | Enable coverage reporting for core modules (src, models, scripts) | | |
| 📊 M2 / Offline Eval | Define offline accuracy metric (3-step: metric, data, operationalization) and data split | | |
| 📊 M2 / Offline Eval | Implement offline evaluation script/notebook and run it for current production model | | |
| 🌐 M2 / Online Eval | Define online accuracy metric and required telemetry from Kafka / logs | | |
| 🌐 M2 / Online Eval | Implement script to compute online accuracy from recent production data | | |
| 💰 M2 / Cost | Define online cost metric (license cost + any LLM cost) in 3-step format | | |
| 💰 M2 / Cost | Implement script to compute online cost metric from production data | | |
| 📝 M2 Report | Draft `m2_report` sections (offline eval, online eval, data quality, pipeline & testing, CI) with code links | | |
| 📝 M2 Report | Add team contract update (or “no change”) and brief note on commits / PR process | | |
| ✅ M2 Admin | Ensure CI is green on main branch and tests are stable | | |
| ✅ M2 Admin | Submit latest commit URL and schedule M2 debrief with mentor | | |
| ✅ M2 Admin | Each member completes M2 teamwork survey | | |

---

**Status ideas:** `⬜ Not started` · `🟡 In progress` · `🟢 Done`
