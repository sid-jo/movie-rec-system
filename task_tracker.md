<p align="center">
  <strong>📋 M1 Task Tracker</strong>
</p>

<p align="center">
  <em>Track who is working on what — fill in Assigned & Status</em>
</p>

---

| Area | Task | Assigned | Status |
|------|------|----------|--------|
| 📥 Data / Kafka | Configure Kafka consumer to use course Kafka (bootstrap servers + topic from Canvas) | | |
| 📥 Data / Kafka | Run Kafka collector and/or Kafka→GCS so raw logs are ingested | | |
| 📥 Data / Kafka | Ensure `data/raw_logs/` (or GCS) has recent log files | | |
| 📥 Data / Kafka | Run metadata fetch so `metadata/users.json` and `metadata/movies.json` are up to date | | |
| 📊 Data / Prep | Run data prep (`notebooks/data_prep.py` or equivalent) to produce `data/processed/ratings.csv` and `watches.csv` | | |
| 🤖 Models / Training | Run `models/train_models.py` and confirm `models/saved/cf_model.pkl`, `cb_model.pkl`, `cold_start.pkl` exist | | |
| 📈 Models / Evaluation | Run model comparison (accuracy, training cost, inference cost, model size) and record results | | |
| 📈 Models / Evaluation | Add/run evaluation code and document metrics (3-step: metric, data, operationalization) | | |
| 🔧 API / Format | Change API response to single line: up to 20 comma-separated movie IDs only (no titles, no userid) | | |
| 🚀 API / Serving | Load saved models (CF, content-based, cold-start) at app startup in `src/app.py` | | |
| 🚀 API / Serving | Implement recommendation logic: use CF/content-based for known users, cold-start for new users | | |
| 🚀 API / Serving | Ensure response latency < 600 ms (optimize/cache if needed) | | |
| 🆕 Cold start | Use user API "likes"/"dislikes" (and any other signals) in cold-start path | | |
| 🆕 Cold start | Wire ColdStartHandler into API for new users and document in report | | |
| 🌐 Deployment | Deploy recommendation service on team VM, port 8082, reachable by course | | |
| 🌐 Deployment | Keep service running for 24h window (before/after M1 submission); use process manager if needed | | |
| 🌐 Deployment | Verify firewall: port 8082 open; test `curl http://<VM>:8082/recommend/<userid>` | | |
| 📝 M1 Report | Create Report Templates (.md and Doc) | | |
| 📝 M1 Report | Fill Learning section (data, techniques, cold start, link to training code) | | |
| 📝 M1 Report | Fill Model comparison (four metrics in 3-step format, table, production choice, link to eval code) | | |
| 📝 M1 Report | Fill Prediction service section (how ranking is derived, links to training and serving code) | | |
| 📝 M1 Report | Ensure meeting notes link shows who / what / when for M1 | | |
| ✅ Admin | Push final code; ensure `m1_report.md` (or .pdf) in repo root | | |
| ✅ Admin | Submit latest commit URL on Canvas | | |
| ✅ Admin | Schedule debrief with team mentor within one week after submission | | |
| ✅ Admin | Each member: complete Teammaker (Catme) survey | | |
| ✅ Admin | Each member: complete M1 teamwork survey | | |

---

**Status ideas:** `⬜ Not started` · `🟡 In progress` · `🟢 Done`
