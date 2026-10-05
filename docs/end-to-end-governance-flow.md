# AIB Life SLA Governance: end-to-end data flow

This guide follows one file and one transaction all the way from the **Extracts** screen to a calculated SLA result, a stored monthly pack, and the governance screens shown in the presentation.

It is written for two audiences at once:

- a business or governance reader who wants to understand what the system does; and
- a developer or auditor who needs to find the exact function that does it.

The most important point is this:

> The browser does not calculate SLA results. The Node.js backend parses the source files, applies deterministic rules, stores the resulting packs, and sends already-calculated JSON to React for display.

## 1. The whole journey in one picture

```text
USER / BROWSER                         NODE.JS BACKEND                         DISK

Select or drop CSV/XLSX
        |
        | multipart/form-data
        v
POST /api/extracts  -----------------> Multer holds file bytes in memory
                                         |
                                         v
                                      readExtract()
                                      - parse CSV or XLSX
                                      - identify kind from headers
                                      - make plain JS row objects
                                         |
                                         v
                                      importExtracts()
                                      - work out slot(s)
                                      - replace old same-slot file  -------> data/extracts/<id>.<ext>
                                      - write metadata index       -------> data/extracts/_index.json
                                         |
                                         v
                                      rebuild()
                                      - re-read current extract set
                                      - evaluate(extracts)
                                         |
                        +----------------+------------------+
                        |                                   |
                        v                                   v
                 collectWorkflows()                 load JSON config
                 deriveAsOf()                       SLA definitions, mapping,
                                                   holidays, target percentages
                        \                                   /
                         +---------------+------------------+
                                         v
                                   each RULE function
                                   creates item outcomes
                                         |
                                         v
                                   monthly roll-up
                                   counts, rates, PASS/FAIL
                                         |
                         +---------------+-------------------+
                         |                                   |
                         v                                   v
                data/analyses/YYYY-MM.json          data/snapshot.json
                         |                                   |
                         +---------------+-------------------+
                                         |
                                         | application/json
                                         v
React screens <-------------------- GET /api/bootstrap
                                    GET /api/analysis/:month
                                    GET /api/items/:month
                                    GET /api/intelligence
```

There are four different data forms in this journey:

| Stage | Form | Example |
|---|---|---|
| Upload | Raw binary bytes inside `multipart/form-data` | the original `.csv` or `.xlsx` file |
| Parsing and calculation | In-memory JavaScript objects and arrays | `{ policy: 'A90002283', created: Date, ... }` |
| Persistence | JSON files, plus the untouched uploaded source file | `data/analyses/2025-02.json` |
| Browser API | JSON over HTTP | the response from `/api/analysis/2025-02` |

So the answer to “are source values moved as JSON packets before the rules compare them?” is **no**. They become JavaScript values in server memory first. The rules operate on those values. JSON is used before calculation for configuration, and after calculation for persistence and browser transport.

## 2. What the five upload slots mean

The source snapshot is not one file per month. It is one current set of five extracts containing records from many reporting months.

| Slot | Recognised kind | Main use |
|---|---|---|
| EBQ Correspondence | `ebq` | 23B NUL and 23B UL Step 1 |
| Cancellation tracker | `cancellation` | 23C |
| Withdrawal extract | `withdrawal` | 23B UL Step 2 |
| Workflow open | `workflow` | open evidence for 23A, 23B Steps 2–3, 23C and 23E |
| Workflow closed | `workflow` | completed evidence for the same workflow-based SLAs |

The slot definitions are in `server/slots.js` (`EXTRACT_SLOTS` and `slotsOf`). Open and closed workflow files have the same columns, so `slotsOf()` distinguishes them from their content: open rows have no Close Date; closed rows do.

One file is current per slot. Uploading a newer EBQ file replaces the existing EBQ file; it does not append another copy. That prevents the CSV and XLSX twins from being counted twice.

## 3. Step-by-step: from upload to stored source

### Step 1 — the Extracts screen collects files

The user drops or selects files in `src/views/Extracts.jsx`.

`send(files)` calls:

```js
const res = await run(() => api.upload(list));
```

`api.upload()` in `src/api.js` creates a browser `FormData` object:

```js
upload(files) {
  const form = new FormData();
  for (const f of files) form.append('files', f, f.name);
  return req('/api/extracts', { method: 'POST', body: form });
}
```

This request is **multipart form data, not JSON**. That is the normal way to send files without converting their bytes into text.

### Step 2 — Express receives bytes

The route is `app.post('/api/extracts', ...)` in `server/index.js`.

```js
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 50 * 1024 * 1024, files: 12 },
});

app.post('/api/extracts', upload.array('files', 12), async (req, res) => {
  const incoming = req.files.map((f) => ({
    originalName: f.originalname,
    buffer: f.buffer,
  }));
  const result = await importExtracts(incoming);
  const snapshot = result.added.length ? await rebuild() : readSnapshot();
  res.json(...);
});
```

Multer exposes every file as a Node `Buffer`. The route serialises imports with `exclusive()` so two uploads cannot rebuild the same packs simultaneously.

### Step 3 — the parser identifies the file from content

`importExtracts()` in `server/pipeline.js` calls:

```js
parsed = await readExtract(file.buffer, file.originalName);
```

`readExtract()` in `server/engine/extracts.js` does the real parsing:

1. permits only `.csv` or `.xlsx`;
2. calls `readGrid()`;
3. scans the first ten rows with `locateHeader()`;
4. matches the columns against `EXTRACT_KINDS`;
5. normalises headers with `fieldName()`; and
6. creates one plain object per data row, retaining `_row` for audit traceability.

The core row conversion is:

```js
const rec = { _row: line.row };
fields.forEach((f, i) => {
  if (f) rec[f] = line.cells[i] ?? null;
});
records.push(rec);
```

For example, a withdrawal spreadsheet row becomes an in-memory object resembling:

```js
{
  _row: 213,
  'policy number': 'A90002283',
  'product name': 'Personal Retirement Savings Account Non-Standard',
  'transaction status': 'Complete',
  'transaction type': 'Partial Withdrawal',
  'date and time of last status': '25/02/2025 17:29:58'
}
```

The filename is used only to determine `.csv` versus `.xlsx` and to retain the original name. Classification is based on columns, not the filename.

CSV is parsed by the local `parseCsv()` implementation. XLSX is parsed with ExcelJS. Only the first worksheet is treated as the extract because BaNCS exports are single-sheet. The expected-results workbook is explicitly rejected.

### Step 4 — the file is assigned to a slot and stored

Back in `importExtracts()`:

```js
const covers = slotsOf(parsed);
```

Any old entry covering the same slot is removed. The new source bytes are saved unchanged by `saveExtractFile()` in `server/store.js`:

```js
fs.writeFileSync(path.join(EXTRACTS_DIR, stored), buffer);
```

Metadata is stored in `data/extracts/_index.json`, including:

- generated ID;
- stored and original filenames;
- detected kind and slot;
- byte size;
- upload time;
- header row and column count; and
- parsed record count.

The raw source file is therefore persisted. The temporary parsed row objects are not stored at this point; the rebuild reads and parses the current raw set again.

## 4. Rebuild: preparing the evidence for the rules

`rebuild()` in `server/pipeline.js` is the bridge from stored files to governance packs.

### Step 5 — re-read the authoritative current set

```js
const extracts = [];
for (const e of index) {
  extracts.push(await readExtract(readExtractFile(e.stored), e.filename));
}

const result = evaluate(extracts);
```

Re-reading matters because the calculation is always made from the same bytes that were persisted as the current extract set.

### Step 6 — normalise open and closed workflows

`evaluate()` in `server/engine/engine.js` first calls:

```js
const workflows = collectWorkflows(extracts);
const derived = deriveAsOf(workflows, extracts);
```

`collectWorkflows()` in `server/engine/workflows.js` unions the two workflow files into one list and gives each row a common structure:

```js
{
  number, type, policy, product,
  created, closeDay, status, open,
  description, assignee, pendingDays, sourceRow
}
```

Dates are parsed by `parseStamp()` in `server/engine/datetime.js`. Calculation values are real JavaScript `Date` objects or canonical strings such as `2025-02-19`; they are not JSON strings being repeatedly compared.

### Step 7 — derive the snapshot date

Open workflows contain `Created Date` and `Pending Since Days`. `deriveAsOf()` adds them together for every usable open row and chooses the most common answer:

```text
Created day + pending days = candidate extract day
most common candidate day = as-of date
```

The delivered set gives 24 September 2026, with all 231 open workflows agreeing. If this evidence is unavailable, the fallback is the day after the latest source activity.

The as-of date is critical for open records: it decides whether an uncompleted item is already overdue or still has time.

### Step 8 — load the rule configuration

`evaluate()` loads two JSON configuration files:

- `config/sla-schedule.json`: targets, SLA wording, workflow types, eligible products, 48-hour limit, 15:00 cutoff and Irish holidays;
- `config/mapping-23b.json`: Product + Transaction mappings to `NUL` or `UL` for 23B.

```js
export const loadSchedule = () => readJson('config/sla-schedule.json');
export const loadMappingRows = () => readJson('config/mapping-23b.json').rows;
```

This is a place where JSON is involved **before** calculation. It provides rule parameters; source rows themselves are still the parsed in-memory objects.

`evaluate()` then builds a shared context:

```js
const ctx = {
  extracts,
  workflows,
  asOfDay,
  cal: makeCalendar(schedule.calendar),
  mapping: buildMapping(mappingRows),
  def: (id) => defs.get(id),
};
```

## 5. Worked example: 23B UL Step 2

This real generated item appears in the current `data/analyses/2025-02.json` pack:

| Field | Value |
|---|---|
| Withdrawal source row | 213 |
| Policy | `A90002283` |
| Transaction | Partial Withdrawal |
| Withdrawal status | Complete |
| Last-status time | 25 February 2025, 17:29:58 |
| Matched workflow | `7101283` |
| Workflow created | 19 February 2025, 13:32:45 |
| SLA outcome | MISSED |

### 5.1 Select the Step 2 inputs

`rule23B_Step2(ctx)` in `server/engine/rules.js` takes:

- all withdrawal records; and
- all workflows whose type equals `Workflow for Withdrawal Approval`, grouped by policy using `byPolicy()`.

```js
const approvals = byPolicy(ctx.workflows, def.params.workflowType);
const withdrawals = ctx.extracts
  .filter((e) => e.kind === 'withdrawal')
  .flatMap((e) => e.records);
```

### 5.2 Join the two extracts

The withdrawal’s policy number is read as text by `idOf()`. `latestBefore()` chooses the latest approval workflow on that policy that was created at or before the withdrawal event:

```js
const wf = latestBefore(approvals.get(policy), last);
```

This is not a database or JSON join. It is an in-memory lookup in JavaScript `Map` and array structures. Request ID is deliberately not used because long Excel IDs have lost precision.

For this item, workflow `7101283` is the one matching policy `A90002283`.

### 5.3 Calculate the business deadline

The shared calendar comes from `makeCalendar()` in `server/engine/calendar.js`.

```js
const clock = ctx.cal.clockStart(wf.created);
const deadline = ctx.cal.cutoffRule(wf.created);
```

For the example:

1. `19 February 2025` is checked against weekends and configured Irish holidays.
2. `13:32:45` is before the configured 15:00 cutoff.
3. `cutoffRule()` therefore makes the same business day the deadline: `2025-02-19`.

If creation were at exactly 15:00 or later, the deadline would be the next business day. A weekend/holiday creation is moved to the next business day and treated as before cutoff.

### 5.4 Decide whether completion exists

Step 2 only treats the transaction as completed if its status normalises to the configured `Complete` value:

```js
const completedAt = norm(status) === complete ? dayOf(last) : null;
```

Here, status is `Complete`, so `completedAt` is `2025-02-25`.

### 5.5 Judge the item

`judge()` in `server/engine/outcome.js` implements the common day-based decision:

```js
if (completedDay) return completedDay <= deadline ? OUTCOME.MET : OUTCOME.MISSED;
return deadline < asOfDay ? OUTCOME.OPEN_PAST : OUTCOME.OPEN_DUE;
```

For this example:

```text
completed day 2025-02-25 <= deadline 2025-02-19 ? no
therefore outcome = MISSED
```

The item object emitted by the rule contains the evidence needed for audit:

```json
{
  "sla": "23B_UL_S2",
  "sourceRow": 213,
  "policy": "A90002283",
  "workflowNumber": "7101283",
  "startedAt": "2025-02-19T13:32:45",
  "clockStart": "2025-02-19",
  "beforeCutoff": true,
  "deadline": "2025-02-19",
  "completedAt": "2025-02-25",
  "outcome": "MISSED",
  "month": "2025-02"
}
```

This block is shown as JSON because that is how it is eventually persisted. While the rule runs, it is an ordinary JavaScript object.

### 5.6 Place the item in a reporting month

Step 2 uses the matched workflow’s created month:

```js
month: monthOf(wf.created)
```

That puts this item in February 2025. Different SLAs have different documented month bases:

- EBQ: transaction start month;
- workflow rules: workflow created month;
- unmatched withdrawal: last-status month.

## 6. What every other rule does

All rule functions live in `server/engine/rules.js` and return the same auditable item shape.

| SLA | Function | Scope and calculation |
|---|---|---|
| 23A | `rule23A()` | Policy-issue workflow type; Created to Close; before 15:00 due same business day, otherwise next business day |
| 23B NUL | `rule23B_EBQ()` | EBQ Product + Transaction maps to NUL; merged by end of next business day |
| 23B UL Step 1 | `rule23B_EBQ()` | same mapping maps to UL; merged the same business day; EBQ contains no time, so no 15:00 decision |
| 23B UL Step 2 | `rule23B_Step2()` | withdrawal joined to latest eligible approval workflow by policy; 15:00 rule |
| 23B UL Step 3 | `rule23B_Step3()` | Unit Adjustment workflow; Created to Close; 15:00 rule |
| 23C | `rule23C()` | eligible protection cancellation joined to approval workflow; elapsed time must be strictly under 48 hours |
| 23E | `rule23E()` | workflow type begins Manual Review and description contains the British spelling “EFT Payment Not Recognised”; close by next business day |

`RULES` defines the functions that `evaluate()` runs:

```js
export const RULES = [
  rule23A,
  rule23B_EBQ,
  rule23B_Step2,
  rule23B_Step3,
  rule23C,
  rule23E,
];
```

For every rule result, `evaluate()` appends `res.items` to one item-level evidence list. This is the population from which all counts are produced.

## 7. From item outcomes to rates and PASS/FAIL

`rollUp()` in `server/engine/engine.js` groups items by their `month` and then by `sla`. `tally()` increments one of six counters:

- met;
- missed;
- open past deadline;
- open not yet due;
- excluded; or
- no matching workflow.

`scoreCounts()` calculates:

```text
completed          = met + missed
rate completed     = met / completed
with open overdue  = completed + open past deadline
rate incl. open    = met / with open overdue

PASS when rate completed >= target
FAIL when rate completed < target
NO_DATA when no item is completed
```

The actual code is:

```js
const completed = counts.met + counts.missed;
const withOpen = completed + counts.openPastDeadline;
const rateCompleted = completed ? counts.met / completed : null;
const rateInclOpen = withOpen ? counts.met / withOpen : null;

status: rateCompleted == null
  ? 'NO_DATA'
  : rateCompleted >= def.target - 1e-12 ? 'PASS' : 'FAIL'
```

Open overdue items do not enter the contractual completed rate, but they do reduce the second operational rate. Excluded and unmatched records remain visible for governance and traceability but enter neither rate.

### 23B UL overall calculation

The configuration declares that `23B_UL` consists of three parts:

```json
"parts": ["23B_UL_S1", "23B_UL_S2", "23B_UL_S3"]
```

`scoreAll()` sums the counters of those three parts before calling `scoreCounts()`. It does **not** average the three step percentages. From the presentation’s complete-history example:

```text
Step 1 met 1,962, missed 52
Step 2 met   442, missed 12
Step 3 met   371, missed  9
--------------------------------
Overall met 2,775, missed 73
Completed = 2,848
Rate completed = 2,775 / 2,848 = 97.44%
Target = 98.00%
Verdict = FAIL
```

This pooling means a high-volume step correctly has more influence than a low-volume step.

## 8. What is stored after calculation

`rebuild()` creates one `analysis` object for each month and calls:

```js
writeAnalysis(m.month, analysis);
```

`writeJson()` in `server/store.js` performs the conversion to JSON text:

```js
fs.writeFileSync(p, JSON.stringify(value) + '\n');
```

### `data/analyses/<month>.json`

Each monthly pack contains:

| Field | Purpose |
|---|---|
| `reporting_month`, `label` | period identity |
| `generated_at`, `as_of`, `partial` | freshness and completeness |
| `results` | calculated SLA counts, rates, targets and status |
| `summary` | headline pass/fail and volume counts |
| `quality`, `quality_summary` | evidence and data-quality findings |
| `drivers` | calculated failure concentrations |
| `sources` | source-file provenance |
| `items` | every item-level outcome and its trace fields |

The result is therefore genuinely stored, not recalculated in the browser.

### `data/snapshot.json`

This is the current extract-set summary across all months:

- source files and five-slot status;
- as-of date and how it was derived;
- total source records and measured items;
- overall SLA totals;
- out-of-scope counts;
- set-wide quality findings; and
- the list of generated months.

### `data/extracts/_index.json` and raw uploads

The index stores current-set metadata. `data/extracts/<id>.<ext>` stores the actual uploaded bytes. The `stored` internal filename is removed from public API entries so the browser does not receive an internal disk path.

### What is not stored

- React component state is temporary browser memory.
- Dashboard formatting such as `97.44%` is produced from stored decimal `0.9744...` by frontend formatting helpers.
- The print/PDF file is not produced or saved by the backend; `Pack.jsx` calls `window.print()`, and the user chooses a PDF printer or physical printer.
- A Bedrock response may be cached under `data/narratives`, but it is explanatory text only. It does not supply any SLA number.

## 9. JSON: every place it enters the design

| Boundary | JSON? | Detail |
|---|---|---|
| Browser uploads CSV/XLSX | No | `FormData` / multipart request containing file bytes |
| Multer to parser | No | Node `Buffer` objects |
| Parsed rows to rules | No serialization | JavaScript objects and arrays in the same backend process |
| SLA definitions and mapping | Yes | configuration loaded from `config/*.json` |
| Rebuilt packs on disk | Yes | JavaScript results serialized by `JSON.stringify()` |
| Backend reads packs | Yes | disk text parsed by `JSON.parse()` |
| Backend sends API response | Yes | Express `res.json(...)` serializes the response |
| Frontend reads API response | Yes | `fetch(...); res.json()` creates browser JavaScript objects |
| Q&A question | Yes | `{ scope, question }` is sent with `Content-Type: application/json` |
| Rule comparison itself | No JSON packet | direct comparisons of numbers, strings, dates and Maps in memory |

The presentation’s phrase “native JSON handling” should be understood as easy conversion between JavaScript objects and JSON. There is still real serialization when packs are written or HTTP responses are sent.

## 10. API responses and how React renders them

`src/api.js` is the single frontend API wrapper. Its `req()` function calls `fetch()`, parses the JSON response, and throws on a non-success status.

### Initial application load

`App.jsx` calls `api.bootstrap()`, which requests `GET /api/bootstrap`.

The route returns:

```js
{
  months,                // small summary for each pack
  snapshot,              // current set summary, with large totals/sources omitted
  slas,                  // rule labels and targets from schedule config
  slots                   // five expected upload slots
}
```

This supplies the rail, period navigation, dashboard cards, extract date and labels.

### Opening a month

When the URL becomes, for example, `#2025-02/position`, `App.jsx` calls:

```js
api.analysis('2025-02')
```

`GET /api/analysis/2025-02` reads the stored pack and deliberately removes the full `items` array from this main response. It returns all monthly content plus:

- `exceptions`: only MISSED and OPEN - PAST DEADLINE items; and
- `itemCount`: total item count.

That keeps the normal monthly screen response smaller.

### Opening an item drill-down

`Position.jsx` calls:

```js
api.items(month, { sla: slaId })
```

`GET /api/items/:month` reads the same stored pack and filters `a.items`. When the requested SLA is the overall 23B UL line, the server expands it to the three configured parts. The browser receives the trace records only when requested.

## 11. Every governance feature shown in the presentation

### Dashboard — `src/views/Dashboard.jsx`

Source: the `months` and `snapshot` fields from `/api/bootstrap`.

It shows:

- reporting periods grouped by year;
- how many of the five headline SLAs passed or failed;
- measured volume;
- open-overdue backlog; and
- an incomplete-period flag when the month equals the extract as-of month.

It renders backend summaries. It does not loop through source rows or re-score anything.

### Extract slot engine — `src/views/Extracts.jsx`

Source: `GET /api/extracts`.

It shows:

- whether all five expected slots are filled;
- detected source kind, record count and filename;
- the derived as-of date;
- upload, remove, rebuild and reload-delivered-extract controls; and
- set-level quality findings.

After any mutation it reloads both extract data and bootstrap data, so the navigation and dashboard reflect the newly rebuilt packs.

### SLA position — `src/views/Position.jsx`

Source: `/api/analysis/:month`, plus `/api/items/:month` on drill-down.

`SlaTable` displays for each rule:

- target;
- met and missed;
- open overdue and open not yet due;
- completed rate;
- rate including overdue open items;
- gap to target; and
- PASS, FAIL or NO_DATA.

`orderedResults()` nests the three 23B UL step rows under the overall row. `SlaItems` loads the audit records for the selected SLA. `DriversPanel` and `QualityPanel` render backend-computed concentrations and findings.

### Exceptions — `src/views/Exceptions.jsx`

Source: `analysis.results` and `analysis.exceptions`.

It lists only headline service levels below target and item records whose outcome is MISSED or OPEN - PAST DEADLINE. Filters change which already-calculated exceptions are displayed. `ItemTable` shows source reference, policy/product, clock start to deadline, completion, owner and outcome.

### Governance pack — `src/views/Pack.jsx`

Source: the same monthly analysis response.

This is a print layout containing:

- period and evidence date;
- executive summary;
- SLA table;
- exception details;
- data-quality findings;
- failure drivers; and
- evidence/source files.

The export action is browser-native:

```js
window.print()
```

Print CSS creates the formal PDF/print layout. There is no separate PDF calculation pipeline.

### Intelligence — `server/intelligence.js` and `src/views/Intelligence.jsx`

The frontend calls `GET /api/intelligence?scope=...`. `buildIntelligence()` reads all stored monthly packs and computes:

- each SLA’s monthly trend against target;
- passed and failed month counts;
- latest full month, strongest and weakest months;
- failure concentrations from `missDrivers()`;
- overdue backlog by SLA and originating month; and
- headline history totals.

`missDrivers()` in `server/insights.js` groups measured item outcomes by assignee, EBQ user, product, workflow type and transaction type. A group is called a concentration only if it has enough evidence and fails at least 1.25 times the SLA’s own failure rate. These are descriptive counts, not forecasts.

`Intelligence.jsx` renders trend charts, service-level records, failure drivers, backlog, narrative and report Q&A from that JSON response.

### Data-quality governance — `server/quality.js`

Quality findings sit beside the figures rather than silently changing them. They include:

- a missing extract slot;
- an incomplete current period;
- open records already past deadline;
- withdrawal/workflow matching gaps;
- excluded rejected EBQ records;
- EBQ pairs missing from the mapping;
- normalised mapping quirks;
- unreliable long Request IDs;
- literal `nan` placeholders; and
- multiple candidate workflows.

Each finding has severity, title, detail and affected SLA IDs. `rebuild()` stores these findings in the monthly pack and snapshot; the frontend simply renders them.

### Guarded narrative and Q&A

`server/narrative.js` and `server/assistant.js` receive computed intelligence objects, never raw files. Amazon Bedrock is optional.

If configured, the model is asked to phrase a compact JSON context. Two guards check the output:

- `unsupportedFigures()` rejects a number absent from the supplied computed payload;
- `contradictedClaims()` rejects reversed PASS/FAIL or other contradicted claims.

If credentials are unavailable or a guard fails, deterministic local text is used. The LLM does not calculate deadlines, counts, percentages or verdicts.

## 12. Data lineage for an auditor

For a displayed failed Step 2 item, the lineage is:

```text
Exceptions/Position row
  -> GET /api/analysis/:month or /api/items/:month
  -> data/analyses/<month>.json item
  -> rule23B_Step2() item object
  -> sourceRow in WITHDRAWALEXT
  + workflowNumber/sourceRow in WRKFLWEXT
  -> deadline from calendar.cutoffRule()
  -> outcome from judge()
```

The fields `sourceRow`, `workflowNumber`, `policy`, `startedAt`, `deadline`, `completedAt`, `outcome` and `month` are the chain of evidence. The stored source metadata identifies the exact uploaded files used for the rebuild.

## 13. Failure and replacement behaviour

- Unsupported or unrecognised files are reported in `skipped` and are not calculated.
- If no file is successfully added, the existing snapshot is retained.
- A successful same-slot upload removes the former current file and then rebuilds every month.
- Rebuild clears old analyses first and writes the months derived from the current complete set.
- Imports/rebuilds are serialised by `exclusive()` to avoid concurrent writers.
- Removing an extract also rebuilds, so missing evidence becomes visible as NO_DATA or a quality finding.
- On a cold start with no runtime packs, `ensureData()` loads the bundled CSV files unless `SKIP_BOOTSTRAP_DATA=1` is set.

## 14. Where to read the implementation

| Question | File / function |
|---|---|
| How is a file uploaded? | `src/views/Extracts.jsx` → `src/api.js: upload()` |
| Which endpoint receives it? | `server/index.js: POST /api/extracts` |
| How is CSV/XLSX parsed? | `server/engine/extracts.js: readGrid(), readExtract()` |
| How is its type identified? | `EXTRACT_KINDS`, `locateHeader()` |
| How are slots/replacements decided? | `server/slots.js`, `server/pipeline.js: importExtracts()` |
| Where are files and JSON saved? | `server/store.js` |
| How are workflows joined? | `server/engine/workflows.js: byPolicy(), latestBefore()` |
| How is the extract date derived? | `deriveAsOf()` |
| Where are holidays and 15:00 handled? | `server/engine/calendar.js: makeCalendar()` |
| Where is each SLA calculated? | `server/engine/rules.js` |
| Where is MET/MISSED/OPEN decided? | `server/engine/outcome.js: judge()` |
| Where are rates and PASS/FAIL calculated? | `server/engine/engine.js: scoreCounts(), scoreAll()` |
| Where are monthly packs built? | `server/pipeline.js: rebuild()` |
| Where are governance APIs exposed? | `server/index.js` |
| How is each frontend screen selected? | `src/App.jsx` |
| How are trends/backlog built? | `server/intelligence.js` |
| How are failure concentrations built? | `server/insights.js: missDrivers()` |
| How is narrative grounded? | `server/narrative.js`, `server/assistant.js` |

## 15. Final mental model

Think of the system as a compiler for governance evidence:

1. **Input:** the five current BaNCS extracts.
2. **Parse:** files become typed JavaScript row objects.
3. **Interpret:** configuration supplies the contractual rule parameters.
4. **Evaluate:** rule functions turn each in-scope row or joined record into an auditable item outcome.
5. **Aggregate:** item outcomes become monthly counts, percentages and verdicts.
6. **Persist:** raw evidence, metadata, monthly packs and the current snapshot are stored.
7. **Serve:** Express converts stored results to JSON API responses.
8. **Present:** React formats those results into dashboard, SLA position, exceptions, printable pack and intelligence views.

The single source of truth for any number on screen is therefore the backend’s stored item outcomes and roll-ups, not a frontend calculation and not an AI-generated answer.
