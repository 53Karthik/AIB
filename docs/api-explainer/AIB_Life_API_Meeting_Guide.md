# AIB Life: APIs, intelligence and rules engine

## The answer you can give in a meeting

We use internal APIs to move files and retrieve reports. Deterministic code calculates the SLAs. Optional external AI calls explain the computed results.

- The workbook says APIs to extract reports from source applications are unavailable or not allowed. That does not mean every API is prohibited.
- Upload, reconciliation, data quality and scoring use ordinary software modules, not LLMs.
- Intelligence contains optional model-assisted summaries and Q&A. No autonomous agent orchestration is evident in the reviewed implementation.
- The rules engine already exists in the prototype and should be described explicitly in the estimation document.

Use “LLM-assisted intelligence” rather than claiming an autonomous agent architecture. Scope statements are based on source review on 9 October 2026, not a production runtime audit. Credential values were not read or included.

## What is an API?

API means Application Programming Interface: an agreed way for one piece of software to ask another to do something or provide information.

- A service counter analogy: the request states what you want; the service processes it; the response tells you the result.
- For this web app, an endpoint is an address such as /api/extracts. A method states the action: GET reads, POST submits, DELETE removes.
- The request carries data, such as file bytes or a question. The response carries results or an error, usually as JSON.
- An API is not automatically AI, a paid third-party service, an agent, a database, or direct access to BaNCS.

Browser APIs such as fetch and FormData are programming interfaces too. The estimate should focus on application endpoints and external integration boundaries, not count every library function as a project interface. Background: MDN API introduction.

## Four different meanings of “API” here

Separate the source extraction boundary from the application boundary and the model boundary.

- Internal application API — implemented: browser to our backend for upload, report retrieval and intelligence requests.
- Source-system extraction API — unavailable/not allowed according to workbook D4: no direct automated extraction from the respective source applications is assumed.
- SharePoint or data-lake integration — proposed: a connector/API or another approved file-delivery mechanism; not implemented in this prototype.
- External model API — optional and implemented in intelligence: backend to Amazon Bedrock for generated language.

A file-based solution can still use APIs to transport files. A SharePoint connector may call Microsoft Graph behind the scenes; that is distinct from obtaining reports from the original business systems. Confirm permitted access with the relevant system owner.

## Why an API is used during upload

The browser needs a defined way to transfer the selected files to the server that owns processing and shared report storage.

- The Data Sources screen selects .csv or .xlsx files and calls api.upload(files).
- FormData puts each file in a field named files; fetch sends POST /api/extracts as multipart/form-data, preserving binary bytes.
- The backend validates/imports the files and rebuilds monthly results when at least one file is accepted.
- The JSON response identifies added, replaced and skipped files; the screen then refreshes extracts and bootstrap data.

No model call appears in the upload/import/rebuild path. A network API is required by this browser/server architecture, not by SLA maths in general: a local batch script can call the same rules pipeline directly. Sources: src/api.js; src/views/Extracts.jsx; backend/api.py; pipeline.py.

## The actual processing flow

Files → internal upload API → parsing and validation → deterministic rules → stored monthly results → dashboard → optional intelligence.

- Identify extract types from required columns, then normalise records and consolidate workflow data.
- Match related records, apply configured rules, classify item outcomes and calculate monthly rates.
- Persist original files, an extract index, monthly JSON analyses and a snapshot on the configured server filesystem.
- Intelligence builds facts from stored outputs; optional Bedrock calls turn those facts into narrative or answers.

Current storage defaults to AIB/data, configurable with DATA_DIR. It is not a demonstrated data lake or SharePoint repository. The application has five expected extract slots, including open and closed workflow slots. Server persistence and source-file retention need an agreed production design.

## How many APIs do we actually have?

The application defines 10 HTTP method-and-path operations across 9 distinct path templates. This is not the same as 10 external integrations.

- Data lifecycle: list, upload, delete, rebuild and load bundled extracts — five operations.
- Reports: bootstrap, monthly analysis and item drill-down — three operations.
- Intelligence: retrieve summary/trends and ask a report question — two operations.
- Estimate interfaces using a declared counting convention: endpoint operations, integration families and external systems are different measures.

Count verified directly: GET /api/bootstrap; GET and POST /api/extracts; DELETE /api/extracts/{id}; POST /api/extracts/rebuild; POST /api/extracts/bundled; GET /api/analysis/{month}; GET /api/items/{month}; GET /api/intelligence; POST /api/intelligence/ask. Ten operations, nine distinct path templates. Do not infer effort from count alone.

## What the estimation workbook actually says

Two sheets list the same nine capability rows. One is labelled File Based; the other Data Lake.

- D4 describes reports being uploaded into SharePoint because source report-extraction APIs are unavailable/not allowed.
- D5–D10 cover copy/paste removal, reconciliation, AI-assisted deck production, SLA calculations, reporting packs and data quality.
- D11 marks SLA slippage prediction as Additional; D12 explicitly labels report querying as LLM.
- Headers distinguish UI, interfaces/APIs, deterministic code, custom ML, pretrained models, LLM, tests, evals, solution and project management. Numeric estimates are blank.

The workbook is an estimation template, not proof of delivered capability or approved architectural detail. Option 2 repeats the SharePoint/file-ingestion text; it does not specify a lake platform, access method, schema, ownership, or lake ingestion implementation. No effort units, team rates, model volumes, durations or numeric costs are supplied.

## File based versus Data Lake

The business rules can remain the same while the ingestion and storage design changes.

- Option 1: approved report files land in SharePoint; a proposed ingestion mechanism retrieves and validates them.
- Option 2: the Data Lake label suggests a central data platform, but the actual ingestion path and reporting datasets still need definition.
- Both options require data contracts, source freshness, reconciliation, rule configuration, results and reporting controls.
- Current prototype: manual browser upload or bundled local files, with filesystem storage. Neither proposed enterprise integration is demonstrated.

Do not claim Option 2 removes extraction constraints. If source APIs are forbidden, a lake also needs an approved alternative feed. A lake SQL query, storage SDK, file delivery or HTTP API can each be a valid boundary; architecture approval determines which. Do not invent connector counts or lake product choices.

## Did we use agents outside intelligence?

No LLM or autonomous agent is evident in ingestion, reconciliation, data-quality checks or SLA scoring. Intelligence uses bounded model calls.

- API = communication interface. Module = code performing a task. Rules engine = explicit business logic. These terms describe different things.
- The current intelligence functions request a summary or one answer from Bedrock using a constructed report context.
- No agent planner, tool-selection loop, multi-agent orchestration or self-directed workflow appears in the reviewed code.
- The workbook’s “No. Of Agents” under Deterministic Code should be defined or renamed to “modules/components” to avoid implying AI everywhere.

If the team uses “agent” to mean any automation component, agree that definition explicitly. Two user-facing intelligence capabilities do not prove two agents. The code does not train a custom model or show a separate pretrained-ML pipeline. A generative LLM is itself pretrained, so avoid double-counting it in two estimate categories.

## Exactly where external AI is used

Optional model inference is confined to report explanation and Q&A; the authoritative figures are calculated first.

- GET /api/intelligence builds trend, concentration and backlog facts and may generate an executive narrative.
- POST /api/intelligence/ask builds question-specific report context and may generate a single grounded answer.
- The Python backend uses Bedrock Converse for Nova model IDs and InvokeModel for the Anthropic-style path; configured model and region determine the call.
- If configuration is absent or a call/output check fails, deterministic text provides a fallback. Narrative responses can also come from cache.

This source review does not prove a live Bedrock connection succeeds. SDK methods are still API calls. Source: backend/narrative.py and assistant.py. AWS documents model invocation through Bedrock; do not assume every intelligence screen visit incurs a call or that summaries are autonomous decisions.

## What is sent to the model?

The reviewed intelligence path sends a computed report context, not the raw uploaded CSV/XLSX files.

- Narrative context includes monthly outcomes, SLA targets/rates, repeated failures, selected concentration groups and overdue backlog summaries.
- Q&A adds the question and selected SLA history/context when an SLA is resolved.
- Group labels and dimensions may still be sensitive. Summarised data is not automatically anonymous.
- Unsupported-number checks, narrative contradiction checks and deterministic fallbacks reduce errors; they do not guarantee every generated statement is correct.

The model is instructed not to calculate new figures, forecast or alter pass/fail. Human review remains appropriate for governance publication. Production decisions should cover approved model/region, data minimisation, access, logging, retention and output review. Do not state that the code proves compliance or data residency.

## What is a rules engine?

A rules engine applies agreed conditions to data and produces a repeatable decision with an explainable basis.

- Inputs: validated extracts, workflow links, mappings, the SLA schedule, holidays, cut-off times and the reporting snapshot date.
- Logic: identify eligible records, determine start/completion/deadline, classify each outcome and aggregate results.
- Outputs: item evidence, monthly counts/rates, pass/fail status, unmatched/excluded records and quality findings.
- Same inputs + same rules + same calendar + same as-of date produce the same scoring outputs. Generated-at timestamps can change.

A rules engine is already implemented using Python functions and JSON configuration, with Node equivalents. A separate commercial engine or microservice is not required to describe it. A new rule authoring UI, independent service or governance workflow would be additional scope.

## Rules already implemented: Schedule 23

These are implementation facts from sla-schedule.json and rules.py; business owners should validate them against the agreed schedule.

- 23A policy issue — 97% target; before 15:00 due same business day, at/after 15:00 due next business day.
- 23B NUL — 96%, next business day; 23B UL — 98%, combining three steps using total met / total completed.
- 23C selected protection cancellations — 96%; matched approval-to-last-status elapsed time must be strictly under 48 hours.
- 23E unrecognised EFT manual reviews — 98%; same or next business day. UL step 1 uses date-only EBQ data without a time cut-off.

23B UL step 2 matches withdrawal approvals on the same policy to a workflow at/before last status and uses the 15:00 rule; step 3 scores unit-adjustment workflows using that rule. Configured holidays are an explicit list, not an automatically maintained calendar; review its coverage for future reporting dates. Exactly 48 hours fails 23C in current code.

## How pass/fail is determined

Completed rate = Met ÷ (Met + Missed). An SLA passes when its completed rate reaches its configured target.

- Example: 97 met and 3 missed gives 97/100 = 97%. At a 97% target, that is PASS.
- Add 5 overdue open items: rate including overdue open = 97/105 = 92.38%. This supplementary measure does not replace completed-rate pass/fail.
- No completed items produces NO_DATA, rather than a fabricated 0% or automatic pass.
- Rejected, unmatched and not-yet-due records remain distinct outcomes; the denominator must be explained rather than silently counting them as completed.

This is an illustrative calculation, not an observed AIB report result. Aggregation for 23B UL combines step counts, not an unweighted mean of the three step percentages. Open items are past deadline only when deadline is earlier than the snapshot date; deadline equal to snapshot date is not yet past due.

## A concrete deadline example

For 23A, receipt time determines the deadline; the model has no role in the decision.

- Illustration: workflow created Monday 5 October 2026 at 14:30. Assuming Monday is a configured business day, deadline is Monday.
- Completion on Monday is MET; completion on Tuesday is MISSED.
- If the same workflow starts at 15:00, its deadline is the next business day; weekends and configured holidays are skipped.
- Without completion, it is OPEN – NOT YET DUE on its deadline date and OPEN – PAST DEADLINE after that date.

The calendar interprets relevant workflow timestamps as Irish wall-clock values in the implementation. This is an example of the configured rule, not a legal interpretation. Missing times in EBQ are an explicit limitation; never pretend a 15:00 check can be applied to date-only data.

## Proposed wording for the rules-engine row

Add a clearly scoped deterministic rules-engine capability to the estimation document.

- “Configuration-driven rules engine for Schedule 23 SLA evaluation: eligibility, mappings, business calendars, cut-offs, deadlines, outcomes, aggregation and explainable exception evidence.”
- Place it under Deterministic Code. Include rule configuration and regression verification; do not assign it an LLM or ML cost.
- Use the existing in-process pipeline unless an independent rules service is specifically required. That choice determines whether new API operations are needed.
- Separate this enabling component from D8’s SLA calculation/reporting feature, and cross-reference effort to avoid charging the same scoring work twice.

Proposed additions beyond the prototype: rule version/effective-date management, approval workflow, immutable run history and a nontechnical editing UI, if required. These must be estimated separately. The revised workbook copy adds a proposal sheet; it does not overwrite the original or invent estimates.

## Ingestion, copy/paste and reconciliation

These capabilities can be automated with deterministic software; they do not inherently require AI.

- D4 ingestion/consolidation: parsing and manual upload exist. Automated SharePoint collection requires a proposed connector plus scheduling/retries/access.
- D5 copy/paste removal: structured parsing and rebuilding replace manual transfer of records and calculations in the current reporting flow.
- D6 reconciliation: workflow consolidation and rule-specific cross-file matching exist. General workflow deduplication and comprehensive control-total reconciliation are not demonstrated.
- Estimate source contracts, schema changes, duplicate handling, reprocessing and mismatch review; avoid describing basic matching as complete enterprise reconciliation.

Files covering the same extract slot replace earlier files; this is a current-set snapshot design, not append-only historical ingestion. An invalid file can be skipped while other files are accepted; it is not an atomic all-or-nothing batch. Confirm reconciliation acceptance criteria with business owners.

## Decks, calculations, packs and data quality

The prototype covers the scoring foundation; several document capabilities require additional delivery work.

- D7 AI-assisted deck production: model-generated narrative exists. There is no application API for automatic deck export/approval; a standalone PPT-building script exists separately.
- D8 SLA calculations and exceptions: deterministic rules, monthly scores and item drill-down are implemented.
- D9 weekly/monthly packs: monthly JSON report packs and dashboard views exist. Weekly scheduling, export, distribution and sign-off are not demonstrated.
- D10 missing/data-quality issues: column recognition, extract-slot status and quality flags exist. Enterprise validation/remediation scope must be specified.

The PowerPoint delivered with this explainer is a documentation artifact; it does not implement governance deck production in the application. Estimate rendering/templates, source references, human approval, versioning and distribution separately when production deck generation is required.

## Prediction versus querying the reports

Trend description is not prediction. The workbook correctly separates an additional prediction feature from LLM querying.

- D11 slippage prediction: not implemented. Current intelligence describes historical rates, failure concentration and overdue backlog.
- A predictive feature needs a defined outcome/horizon, suitable history, time-based validation, baselines and monitored performance.
- D12 LLM querying: implemented as single-turn Q&A grounded in computed report facts, with optional Bedrock and deterministic fallback.
- An LLM phrasing an answer is not evidence of a trained forecasting model, causal root-cause analysis, or an autonomous agent.

Forecasting could use a statistical baseline or ML; select only after data and evaluation requirements are agreed. No custom training pipeline is visible. Model answers about “why” reflect observed concentrations and report context, not proven causal explanations.

## How to fill the estimate columns responsibly

The workbook provides categories, not numbers. Estimate scoped work packages with an agreed unit and counting convention.

- UI: count actual screens and interactions. Interfaces: separate internal operations from SharePoint/lake/model integration families.
- Deterministic Code: count modules/components. ML and pretrained-model work: mark N/A unless there is a defined extra use case.
- LLM: estimate prompt/context integration, safeguards, evaluations and usage cost; do not double-count the pretrained LLM.
- Testing/evals/solution/PM: include appropriate effort, identify shared work once, and state dependencies, assumptions and contingency.

Use hours or person-days consistently. LLM running cost depends on input/output token volume, model/region, call frequency, cache hits and retries; use current approved pricing when numbers are requested. Infrastructure/storage/operations cost is separate. No numerical effort or cost can be justified from this workbook alone.

## What testing and evaluations mean here

Rules tests establish scoring correctness; integration tests establish communication; LLM evaluations assess generated explanations.

- Rules: cut-off boundaries, weekends/holidays, exact 48-hour behaviour, rejected/unmatched/open items, zero denominators and aggregation.
- Integration: valid/invalid uploads, partial acceptance, replacement/rebuild, report retrieval, unavailable external services and fallback.
- LLM evals: unsupported figures, contradictory claims, grounded answers, scope refusal and misleading causal/forecast language.
- UAT: compare agreed reference outcomes, inspect evidence, reconcile totals and obtain business-owner acceptance.

The repository includes Node and Python tests and reference comparison utilities; this documentation task does not claim they were executed as a production certification. A deterministic function suite does not replace integration, security, performance or business acceptance checks. Quality flags indicate issues; they do not prove the inputs are complete.

## What remains to make this production-ready

Treat prototype evidence and production requirements separately when answering delivery questions.

- Access and protection: identity, roles, least-privilege integration permissions, TLS and approved data/model boundaries.
- Operations: durable storage, backups, job retry/idempotency, monitoring, concurrent access and documented error handling.
- Governance: approved rule versions, effective dates, run lineage, immutable history, source freshness and human pack sign-off.
- Scope decisions: SharePoint versus lake ingestion, weekly output, deck export, forecasting and scale/performance acceptance criteria.

No explicit authentication/role middleware is present in the reviewed application route files; infrastructure controls were not audited. Current slot replacement and clearing/rebuilding stored monthly packs are not an immutable audit history. These are delivery questions, not a claim that all controls are absent from the wider environment.

## Use precise language in the document

“File-based ingestion with internal APIs; deterministic rules for SLA calculations; optional LLM-assisted narrative and report querying.”

- Replace “no APIs” with “direct source-system report-extraction APIs are unavailable/not permitted”.
- Replace undefined deterministic “agents” with “modules/components”, or add an explicit glossary definition.
- Clarify the Data Lake option’s ingestion route instead of repeating the SharePoint wording.
- Label implemented, partial, proposed and additional capabilities; state rules-engine scope and avoid duplicate estimates.

These are proposed editorial changes, not changes to the source workbook. The supplied review workbook preserves both original sheets and adds a mapping/proposal sheet with blank estimates. Your original Downloads file is unchanged.

## Meeting Q&A

### The workbook says APIs are unavailable. Why are we using one?

It refers specifically to APIs that extract reports from the source business applications. Our own upload/report APIs operate after files are obtained through the approved route. These are different interfaces.

### Is file upload an API call?

Yes. The browser calls our backend using POST /api/extracts and multipart/form-data. It is an internal application operation, not a source extraction or AI call.

### Can file upload work without an external API?

Yes. Current upload and scoring need no external service. The browser still uses our internal API to transfer the file to the server.

### Can the rules engine run without any HTTP API?

Yes. The engine and pipeline can be called directly by a script. HTTP exposes the functionality to the browser; it is not required by the calculation itself.

### Do we have APIs outside intelligence?

Yes: upload, file listing/removal/rebuild, dashboard bootstrap, monthly analyses and item drill-down. External model inference is restricted to intelligence in the reviewed code.

### Do we have agents outside intelligence?

No LLM or autonomous agent is evident there. Ingestion, matching, validation and scoring are deterministic modules. If the estimate uses agent as a synonym for automation component, define that usage.

### Is intelligence itself an autonomous agent?

The reviewed implementation is bounded narrative generation and single-turn Q&A, not a demonstrated planner/tool-using autonomous agent. Call it LLM-assisted intelligence.

### How many agents should I put in the estimate?

Do not derive an agent count from the number of features. Agree whether the column means software modules or autonomous AI agents. The current code does not justify a multi-agent count.

### How many APIs should I put in the estimate?

Current code defines 10 method/path operations across nine path templates. For project estimating, agree whether you count operations or integration families; SharePoint/lake are proposed, while Bedrock is one shared external model integration.

### Does SharePoint need an API even in a file-based solution?

Automated retrieval generally needs an approved connector/API or another delivery mechanism. Microsoft Graph supports file downloads, but the prototype has no SharePoint integration and tenant permissions/design remain to be agreed.

### Is the Data Lake option already implemented?

No. Its sheet is a proposal label with the same capability text as Option 1. The prototype uses server filesystem storage. A lake platform, feed and access design are not specified.

### Does Option 2 bypass the source API restriction?

No. Data must still reach the lake by an approved route. The workbook does not establish that route; its repeated SharePoint text needs clarification.

### Why use a backend instead of doing everything in the browser?

It centralises processing and shared results, controls storage, keeps service credentials server-side and presents a reusable contract. Browser-only processing is possible but would be a different architecture.

### Does the API calculate the SLA?

The route invokes the deterministic pipeline/rules engine. The API is the communication entry point; the rules functions perform the calculation.

### What is the difference between a rule, model, API and agent?

A rule is an explicit condition; a model learns or generates from statistical patterns; an API is an interface; an autonomous agent selects actions/tools to pursue a task. Ordinary automation need not involve a model or agent.

### Do we need to build a rules engine from scratch?

The prototype already has one. Document it and estimate any production enhancement separately. A separate product/service is needed only if requirements call for it.

### Will adding the rules-engine row add another API?

Not necessarily. The current engine runs inside the backend behind existing routes. A separately deployed rules service or rule-management UI may require additional APIs, if explicitly scoped.

### How do I avoid double-counting the rules engine?

D8 describes the delivered SLA calculation/reporting feature; the engine is its enabling component. Allocate shared scoring effort once and reference it from both rows. New rule-management controls can be separate effort.

### What determines pass/fail?

Met / (Met + Missed), compared with the configured target. Overdue open items affect a separate rateIncludingOpen measure, not current completed-rate pass/fail.

### What happens with no completed items?

The completed rate is null and the result is NO_DATA. It should not be presented as an automatic PASS or a genuine 0% completion rate.

### Are rejected and unmatched records treated as misses?

They are separate outcomes. Rejected EBQ records are excluded; unmatched workflows are identified separately. They do not enter the Met + Missed completed denominator.

### How are unit-linked steps aggregated?

The engine adds counts for Steps 1–3 and calculates total Met / total completed. It does not average percentages without weighting.

### What happens at exactly 15:00 or exactly 48 hours?

The configured 15:00 rule treats 15:00 as at/after cut-off and allows the next business day. For 23C, elapsed time must be less than 48 hours, so exactly 48 hours is MISSED in the current code.

### Can we apply the cut-off when a file contains dates only?

No exact time test is possible without a time. Current EBQ UL Step 1 uses same-business-day processing without a 15:00 test; make that source limitation explicit.

### Can rules change without changing code?

Targets, parameters, mappings and listed holidays are configurable JSON. New algorithm types or an approval/editing UI can still require code and delivery work. Version/effective-date controls are additional production scope.

### Is re-uploading safe from duplicate counting?

Files replace existing files covering the same extract slots, and workflows are consolidated. This helps current snapshot deduplication but is not a universal duplicate-control or immutable historical ingestion guarantee.

### Can only part of an upload succeed?

Yes. Unsupported files may be skipped while valid files are accepted; a rebuild occurs if any files were added. Users should inspect skipped/replaced results and slot completeness.

### Are all raw files sent to the LLM?

No raw uploaded file transmission appears in the reviewed intelligence path. It sends computed facts and the question. Group labels/dimensions can still be sensitive and require approved data handling.

### What if Bedrock fails or is not configured?

Narrative/Q&A fall back to deterministic text. SLA scores remain based on the engine. The API may still fail for other storage or processing errors; fallback does not solve all failures.

### Does every intelligence request call the model?

No. Missing configuration or empty data avoids model inference; narrative cache hits reuse text. When a configured model call or validation fails, the response uses fallback.

### Are generated explanations guaranteed correct?

No. Number and claim checks reduce risks but cannot prove every sentence. Human review and representative LLM evaluations are needed before publishing a governance pack.

### Did we train our own ML model?

No custom training pipeline is evident. Bedrock provides access to a configured pretrained generative model. Do not infer custom ML from ordinary trend calculations.

### Is SLA slippage prediction available?

No. D11 is additional scope. Current intelligence describes past results and backlog and explicitly instructs the LLM not to forecast.

### Is automated deck production finished?

Not as an application feature. Narrative and a standalone project PPT script exist, but no deck export API, scheduled publication or pack approval workflow is demonstrated.

### Are weekly governance packs available?

Monthly computed packs and dashboard views exist. Weekly scheduling, export and distribution are not implemented in the reviewed routes/pipeline.

### How do we estimate effort and model costs?

Agree work units, module/interface boundaries, acceptance criteria and dependencies first. Model costs require chosen model/region, token volumes, call rate, caching and retry assumptions; infrastructure and delivery effort are separate. Workbook numbers are blank.

### What security controls are already proven?

Only code-visible validation and server-side boundaries were reviewed. Route files show no explicit authentication/role middleware. Infrastructure controls, compliance, live model access and production readiness were not audited.

### Does automation eliminate all manual work?

It removes record copy/paste and repeat calculations in the current flow. Source report preparation, exception remediation, rule approvals and governance sign-off can still require people.

### Can this answer any question about the estimate?

It covers each listed capability, architecture, scope and common challenge questions. Unknown effort units, costs, lake design, access permissions and delivery criteria remain decisions to obtain, not facts to invent.

## Sources

- Workbook: AIB Life Governance Estimations.xlsx; Option 1 and Option 2, D4:D12; headers E2:U3. All estimate cells are blank.
- Application API: AIB/src/api.js; AIB/backend/api.py; AIB/package.json (Python default, Node alternative).
- Ingestion and storage: AIB/backend/pipeline.py; backend/store.py; backend/engine/extracts.py; backend/slots.py.
- Rules and scoring: AIB/config/sla-schedule.json; backend/engine/engine.py, rules.py, calendar.py, outcome.py, workflows.py.
- Intelligence: AIB/backend/intelligence.py, narrative.py, assistant.py; Node equivalents under AIB/server/.
- API background: https://developer.mozilla.org/en-US/docs/Learn_web_development/Extensions/Client-side_APIs/Introduction
- SharePoint integration reference: https://learn.microsoft.com/en-us/graph/api/driveitem-get-content?view=graph-rest-1.0
- Bedrock integration reference: https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html