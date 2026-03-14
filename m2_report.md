# Milestone 2 Report: Model and Infrastructure Quality

## Offline Evaluation

*(1 page of text max, not counting figures)*

### Validation/Test Data

<!-- Describe the validation/test dataset: how it was derived, what time period it covers, how it was split from training data, and any preprocessing applied. -->

### Accuracy Metric

<!-- Provide a 3-step description of the accuracy metric used:
1. What is being measured (e.g., predicted ranking vs. actual watch behavior)
2. How the metric is operationalized (formula, computation method)
3. Justification for why this metric is appropriate for the problem -->

### Avoiding Common Pitfalls

<!-- Briefly discuss how you avoided:
- Label leakage
- Data dependencies (e.g., temporal ordering)
- Overfitting on test data
- Other evaluation pitfalls discussed in class -->

### Evaluation Results

<!-- Include evaluation results or link to them. Example:
- Metric value: ...
- Baseline comparison: ...
- Subpopulation analysis (if applicable): ... -->

### Implementation Pointer

<!-- Provide a link to the corresponding implementation in your code, e.g.:
[`evaluation/offline_eval.py`](evaluation/offline_eval.py) -->

---

## Online Evaluation

*(1 page of text max, not counting figures)*

### Model Accuracy Metric

<!-- 3-step description:
1. The accuracy metric used in production (e.g., click-through rate, watch completion rate)
2. Telemetry data collected (what events are logged, from which service, at what granularity)
3. How the metric is computed from the telemetry data -->

### Cost Metric

<!-- 3-step description:
1. The cost metric (movie licensing fees from the `cost` field + LLM token costs if applicable)
2. Telemetry data collected (which fields, how logged)
3. How the cost is aggregated/computed -->

### Evaluation Results

<!-- Include or link to online evaluation results:
- Model accuracy metric value over the evaluation period: ...
- Total/average licensing cost per recommendation: ...
- LLM token cost (if applicable): ... -->

### Implementation Pointer

<!-- Link to the corresponding implementation, e.g.:
[`evaluation/online_eval.py`](evaluation/online_eval.py)
[`telemetry/collector.py`](telemetry/collector.py) -->

---

## Data Quality

*(0.5 pages max)*

### Schema Enforcement

<!-- Describe schema validation applied to:
- Kafka stream events
- User API responses
- Movie API responses
- Incoming requests to your recommendation API -->

### Drift Detection

<!-- Describe drift detection strategy:
- What signals are monitored
- How strong drift is detected
- How alerts or fallbacks are triggered -->

### Implementation Pointer

<!-- Link to implementation, e.g.:
[`data_quality/schema.py`](data_quality/schema.py)
[`data_quality/drift.py`](data_quality/drift.py) -->

---

## Pipeline Implementation and Testing

*(1 page of text max, not counting figures)*

### Pipeline Structure

<!-- Describe how the pipeline is structured and implemented:
- Modules/steps (data ingestion from Kafka, feature extraction, training, evaluation, model serialization, serving, telemetry)
- How steps can be run independently or end-to-end
- Any intermediate storage used (files, databases) -->

### Testing Approach

<!-- Describe how the pipeline was tested:
- Unit tests for each pipeline step
- Use of sample/mock data instead of full production datasets
- Mocks/stubs for network connections or external APIs
- Edge cases and robustness scenarios covered -->

### Coverage Report

<!-- Include or link to a coverage report, e.g.:
- Overall coverage: X%
- Link: [coverage report](link-to-coverage-report) -->

### Adequacy Argument

<!-- Briefly argue why the testing is adequate:
- Which components are most critical and how they are tested
- Known gaps and why they are acceptable -->

### Implementation Pointer

<!-- Link to pipeline and tests, e.g.:
[`pipeline/`](pipeline/)
[`tests/`](tests/) -->

---

## Continuous Integration

*(0.5 pages max)*

### CI Setup

<!-- Describe the CI platform used (e.g., GitHub Actions with local runner, Jenkins on VM) and the overall setup. -->

### What Is Automated

<!-- Describe what runs automatically on each push:
- Unit tests
- Coverage reporting
- Any other checks (linting, type checking, etc.)
Note: model training/evaluation pipeline automation is not required. -->

### CI Service Pointer

<!-- Provide a link to the CI service/dashboard.
If credentials are required, note that mentor access has been granted. -->

---

## Pull Requests *(optional)*

<!-- If your team used pull requests and code review for the majority of changes, provide:
- A brief description of your PR/review process
- Links to 3 example pull requests -->

**Process description:**

**Example pull requests:**
1. [PR title](link)
2. [PR title](link)
3. [PR title](link)

---

## Team Contract Update

<!-- Either:
(a) Include the updated team contract and describe the reason for the change, OR
(b) State: "No update to team contract." -->

No update to team contract.

---

## Grading Checklist

For reference — items to verify before submission:

- [ ] 10pt: Commits are cohesive with reasonable messages; code is well structured.
- [ ] 10pt: Report describes pipeline structure with implementation pointer.
- [ ] 10pt: Data quality checks described and implemented for all external interfaces (Kafka, user/movie APIs, recommendation API).
- [ ] 10pt: Offline evaluation strategy covers (1) validation/test split, (2) 3-step metric description, (3) justification and pitfall avoidance. Results included.
- [ ] 10pt: Online model accuracy evaluation described in 3-step format with implementation pointer and results.
- [ ] 10pt: Online cost evaluation described in 3-step format (licensing fees + LLM costs) with implementation pointer and results.
- [ ] 10pt: Pipeline testing described, coverage report included/linked, adequacy argued.
- [ ] 10pt: Infrastructure tests automated with CI, triggered on GitHub push, pointer provided.
- [ ] 10pt: Team contract update or statement of no change included.
- [ ] 10pt (individual): Debriefing meeting scheduled within one week of submission.
- [ ] 3pt (individual): Teamwork survey filled out.
- [ ] 5pt (bonus): Pull requests and code review used for majority of changes; process described with 3 examples.
- [ ] 3pt (bonus): Social activity (see README).
- [ ] 3pt (bonus): Going beyond the comfort zone (see README).
