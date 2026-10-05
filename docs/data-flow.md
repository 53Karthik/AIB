# AIB Life Data Flow

This document explains how the app moves from uploaded BaNCS files to the rendered dashboard, and where the SLA rules, calendar logic, outcomes and counts are applied.

## 1. Short Flow

```text
User uploads files in the Extracts screen
  -> frontend sends FormData to POST /api/extracts
  -> server parses each CSV/XLSX and identifies its extract type from columns
  -> raw uploaded files are stored under data/extracts/
  -> _index.json records which file fills which extract slot
  -> rebuild() re-reads the stored files
  -> engine.evaluate() applies Schedule 23 rules item by item
  -> monthly JSON packs are written under data/analyses/
  -> snapshot.json records the current extract set and totals
  -> React calls /api/bootstrap and /api/analysis/:month
  -> Dashboard, Position, Exceptions and Pack render from those JSON responses
```

## 2. Where Data Is Stored

Writable state defaults to `AIB/data`, unless `DATA_DIR` is set.

The storage paths are defined in [server/store.js](../server/store.js):

```js
export const DATA_DIR = process.env.DATA_DIR ? path.resolve(process.env.DATA_DIR) : path.join(ROOT, 'data');
export const EXTRACTS_DIR = path.join(DATA_DIR, 'extracts');
export const ANALYSES_DIR = path.join(DATA_DIR, 'analyses');
```

Important folders/files:

| Path | Purpose |
|---|---|
| `data/extracts/` | Uploaded BaNCS extract files, stored as `<random-id>.csv` or `<random-id>.xlsx`. |
| `data/extracts/_index.json` | Metadata for the current extract set: original filename, kind, slots covered, row counts. |
| `data/analyses/<month>.json` | One rebuilt governance pack per reporting month. |
| `data/snapshot.json` | Current extract-set summary: extract date, source files, totals, quality flags, month list. |
| `Claude_Data/` | Delivered sample/input extracts. Read-only source used by `Reload delivered extracts` and cold start. |

The raw uploaded file is saved here:

```js
// server/store.js
fs.writeFileSync(path.join(EXTRACTS_DIR, stored), buffer);
```

The stored file is read back during rebuild here:

```js
// server/pipeline.js
for (const e of index) extracts.push(await readExtract(readExtractFile(e.stored), e.filename));
```

## 3. Upload And Import Flow

The frontend upload happens in [src/views/Extracts.jsx](../src/views/Extracts.jsx). The user drops files or browses for them, then `send(files)` calls:

```js
const res = await run(() => api.upload(list));
```

[src/api.js](../src/api.js) packages the files as `FormData`:

```js
upload(files) {
  const form = new FormData();
  for (const f of files) form.append('files', f, f.name);
  return req('/api/extracts', { method: 'POST', body: form });
}
```

The API receives the files in [server/index.js](../server/index.js):

```js
app.post('/api/extracts', upload.array('files', 12), async (req, res) => {
```

Then it passes each uploaded file into the pipeline:

```js
const incoming = req.files.map((f) => ({ originalName: f.originalname, buffer: f.buffer }));
const result = await importExtracts(incoming);
const snapshot = result.added.length ? await rebuild() : readSnapshot();
```

`importExtracts()` in [server/pipeline.js](../server/pipeline.js) does four key things:

1. Parses the file with `readExtract(file.buffer, file.originalName)`.
2. Works out which slot it covers with `slotsOf(parsed)`.
3. Replaces any older file covering the same slot.
4. Saves the raw file and records metadata in `_index.json`.

The save line is:

```js
stored: saveExtractFile(id, file.originalName, file.buffer),
```

## 4. Extract Parsing

Parsing is handled by [server/engine/extracts.js](../server/engine/extracts.js).

The known extract types are listed in `EXTRACT_KINDS`:

| Kind | Feeds |
|---|---|
| `ebq` | `23B_NUL`, `23B_UL_S1` |
| `cancellation` | `23C` |
| `withdrawal` | `23B_UL_S2` |
| `workflow` | `23A`, `23B_UL_S2`, `23B_UL_S3`, `23C`, `23E` |

The parser reads either CSV or XLSX:

```js
export async function readExtract(buffer, filename) {
```

It finds the header by scanning the first rows and matching the expected columns:

```js
const found = locateHeader(grid);
```

Each row becomes a plain JavaScript record:

```js
const rec = { _row: line.row };
fields.forEach((f, i) => {
  if (f) rec[f] = line.cells[i] ?? null;
});
records.push(rec);
```

This is also where the expected-results workbook is rejected, because it is reference material, not a BaNCS extract.

## 5. Config And Rules

Yes, the rule definitions are in `config`.

| File | Purpose |
|---|---|
| [config/sla-schedule.json](../config/sla-schedule.json) | SLA labels, names, targets, calendar holidays, cutoff hour, workflow types, product lists and rule parameters. |
| [config/mapping-23b.json](../config/mapping-23b.json) | Product + transaction mapping for 23B NUL vs 23B UL Step 1. |

They are loaded in [server/engine/engine.js](../server/engine/engine.js):

```js
export const loadSchedule = () => readJson('config/sla-schedule.json');
export const loadMappingRows = () => readJson('config/mapping-23b.json').rows;
```

`engine.evaluate()` then builds a context object containing:

```js
const ctx = {
  extracts,
  workflows,
  asOfDay,
  cal: makeCalendar(schedule.calendar),
  mapping: buildMapping(mappingRows),
  def: (id) => { ... },
};
```

That context is passed into every rule function.

## 6. Main Engine Files

### `rules.js`: Item-Level SLA Logic

[server/engine/rules.js](../server/engine/rules.js) contains one function per Schedule 23 rule:

| Function | What it scores |
|---|---|
| `rule23A()` | Policy issue workflows. |
| `rule23B_EBQ()` | 23B NUL and 23B UL Step 1 from EBQ rows. |
| `rule23B_Step2()` | Withdrawals matched to withdrawal approval workflows. |
| `rule23B_Step3()` | Unit adjustment workflows. |
| `rule23C()` | Cancellations matched to approval workflows, under the 48-hour rule. |
| `rule23E()` | Manual Review workflows mentioning EFT Payment Not Recognised. |

Each rule returns item-level results, for example:

```js
{ sla, key, month, outcome, startedAt, clockStart, beforeCutoff, deadline, completedAt, ...detail }
```

At the bottom, all rule functions are exported as:

```js
export const RULES = [rule23A, rule23B_EBQ, rule23B_Step2, rule23B_Step3, rule23C, rule23E];
```

So `rules.js` answers: for each source row/workflow, which SLA does it belong to, what is its start date, what is its deadline, and what was the outcome?

### `calendar.js`: Business Days, Cutoff And Deadlines

[server/engine/calendar.js](../server/engine/calendar.js) creates the Schedule 23 business calendar:

```js
export function makeCalendar({ holidays = [], cutoffHour = 15 } = {}) {
```

It handles:

| Function | Meaning |
|---|---|
| `isBusinessDay(day)` | False for weekends and configured Irish public holidays. |
| `clockStart(stamp)` | Moves weekend/holiday starts to the next business day and records whether the start was before 15:00. |
| `sameDay(stamp)` | Deadline is the clock-start business day. |
| `nextDay(stamp)` | Deadline is the next business day after the clock start. |
| `cutoffRule(stamp)` | Before 15:00 means same business day; 15:00 or later means next business day. |

The cutoff rule is:

```js
cutoffRule: (stamp) => {
  const c = clockStart(stamp);
  return c.beforeCutoff ? c.day : nextBusinessDay(c.day);
},
```

So yes: this file is where start day, business-day movement, 15:00 cutoff and day-based deadlines are handled.

### `outcome.js`: Met, Missed, Open Overdue

[server/engine/outcome.js](../server/engine/outcome.js) defines the allowed item outcomes:

```js
MET
MISSED
OPEN - PAST DEADLINE
OPEN - NOT YET DUE
EXCLUDED - REJECTED
NO MATCHING WORKFLOW
```

The key judgement function is:

```js
export function judge(completedDay, deadline, asOfDay) {
  if (completedDay) return completedDay <= deadline ? OUTCOME.MET : OUTCOME.MISSED;
  return deadline < asOfDay ? OUTCOME.OPEN_PAST : OUTCOME.OPEN_DUE;
}
```

So yes: this file decides whether a day-based item is met, missed, still open but overdue, or still open and not yet due.

### `engine.js`: Orchestration And Counts

[server/engine/engine.js](../server/engine/engine.js) ties everything together.

It starts by collecting workflows and deriving the extract date:

```js
const workflows = collectWorkflows(extracts);
const derived = deriveAsOf(workflows, extracts);
```

Then it runs every SLA rule:

```js
for (const rule of RULES) {
  const res = rule(ctx);
  items.push(...res.items);
}
```

After item-level outcomes exist, `engine.js` rolls them up into counts and rates:

```js
monthly: rollUp(items, schedule),
totals: rollUpTotals(items, schedule),
```

The rate and pass/fail logic is in `scoreCounts()`:

```js
const completed = counts.met + counts.missed;
const withOpen = completed + counts.openPastDeadline;
const rateCompleted = completed ? counts.met / completed : null;
const rateInclOpen = withOpen ? counts.met / withOpen : null;
```

Status is decided by `rateCompleted` against the target:

```js
status: rateCompleted == null ? 'NO_DATA' : rateCompleted >= def.target - 1e-12 ? 'PASS' : 'FAIL',
```

So yes: `engine.js` is mainly the orchestrator and counter. It does not define the individual SLA rules; it runs them, counts outcomes, calculates rates and marks PASS/FAIL.

### `workflows.js`: Workflow Normalisation And Extract Date

[server/engine/workflows.js](../server/engine/workflows.js) turns open and closed WRKFLWEXT rows into one shared workflow list:

```js
export function collectWorkflows(extracts) {
```

It also groups workflows by policy and finds the latest workflow before an event:

```js
export function latestBefore(list, when) {
```

The extract date is derived here:

```js
export function deriveAsOf(workflows, extracts) {
```

It uses open workflow `Created Date + Pending Since Days`; if that is not available, it falls back to the day after the latest activity in the extracts.

### `datetime.js`: Timestamp Parsing

[server/engine/datetime.js](../server/engine/datetime.js) parses dates from CSV/XLSX formats and converts them into stable day/month strings:

| Function | Purpose |
|---|---|
| `parseStamp()` | Handles Excel dates, Excel serials, `dd/mm/yyyy`, ISO strings and blanks. |
| `dayOf()` | Returns `YYYY-MM-DD`. |
| `monthOf()` | Returns `YYYY-MM`. |
| `hoursBetween()` | Used by 23C for the 48-hour cancellation rule. |

## 7. Rebuild And Monthly Pack Writing

After files are uploaded, [server/pipeline.js](../server/pipeline.js) runs `rebuild()`.

It clears existing monthly analyses:

```js
clearAnalyses();
```

Then it re-reads every current extract from `data/extracts/`:

```js
for (const e of index) extracts.push(await readExtract(readExtractFile(e.stored), e.filename));
```

Then it evaluates all SLA outcomes:

```js
const result = evaluate(extracts);
```

For each reporting month, it filters the item-level results and builds an analysis object:

```js
const items = result.items.filter((i) => i.month === m.month);
```

Then it writes the monthly pack:

```js
writeAnalysis(m.month, analysis);
```

Finally, it writes the overall snapshot:

```js
return writeSnapshot({
```

## 8. How The Dashboard Is Rendered

The app boots from [src/App.jsx](../src/App.jsx).

On load, it calls:

```js
const b = await api.bootstrap();
```

The backend route for that is [server/index.js](../server/index.js):

```js
app.get('/api/bootstrap', (req, res) => {
```

That route returns:

| Field | Source |
|---|---|
| `months` | `data/analyses/*.json`, summarized for the dashboard. |
| `snapshot` | `data/snapshot.json`. |
| `slas` | `config/sla-schedule.json`. |
| `slots` | Expected extract slots. |

The dashboard page is rendered here:

```js
{page === 'dashboard' && <Dashboard boot={boot} onOpenMonth={openMonth} onExtracts={showExtracts} />}
```

[src/views/Dashboard.jsx](../src/views/Dashboard.jsx) groups the returned months by year and renders period cards from the `summary` values already computed by the backend.

When a month is opened, `App.jsx` calls:

```js
api.analysis(month)
```

The backend route reads that month's pack:

```js
app.get('/api/analysis/:month', (req, res) => {
```

Then `App.jsx` renders one of the monthly views:

```js
{page === 'month' && analysis && view === 'position' && <Position analysis={analysis} slas={boot.slas} />}
{page === 'month' && analysis && view === 'exceptions' && <Exceptions analysis={analysis} slas={boot.slas} />}
{page === 'month' && analysis && view === 'pack' && <Pack analysis={analysis} slas={boot.slas} />}
```

The frontend does not recalculate SLA results. It displays the backend-generated JSON.

## 9. The Main Data Contract

The most important object created by the backend is each item-level outcome from `rules.js`.

Typical fields:

| Field | Meaning |
|---|---|
| `sla` | Which SLA/step the item belongs to. |
| `month` | Reporting month. |
| `outcome` | `MET`, `MISSED`, `OPEN - PAST DEADLINE`, etc. |
| `startedAt` | Original start timestamp or date. |
| `clockStart` | Business day the SLA clock starts on. |
| `beforeCutoff` | Whether the start was before the 15:00 cutoff, where relevant. |
| `deadline` | Calculated SLA deadline day. |
| `completedAt` | Completion day, if any. |
| `sourceRow` / `workflowNumber` | Traceability back to the source extract row/workflow. |

Everything visible in the dashboard is ultimately counted from these item-level outcomes.

## 10. Other Files, Very Briefly

| File/folder | Brief purpose |
|---|---|
| [server/index.js](../server/index.js) | Express API routes and startup. |
| [server/env.js](../server/env.js) | Loads `.env` before modules read environment variables. |
| [server/slots.js](../server/slots.js) | Defines the five required extract slots and maps parsed extract kinds to slots. |
| [server/quality.js](../server/quality.js) | Produces data-quality findings shown next to the figures. |
| [server/insights.js](../server/insights.js) | Finds where failures concentrate by handler/product/transaction group. |
| [server/intelligence.js](../server/intelligence.js) | Builds cross-month trend data for the Intelligence panel. |
| [server/narrative.js](../server/narrative.js) | Generates deterministic or Bedrock-assisted executive narrative, guarded against invented/wrong claims. |
| [server/assistant.js](../server/assistant.js) | Q&A over the computed report figures. |
| [src/views/Extracts.jsx](../src/views/Extracts.jsx) | Upload/manage extract files UI. |
| [src/views/Dashboard.jsx](../src/views/Dashboard.jsx) | Landing dashboard with reporting-period cards. |
| [src/views/Position.jsx](../src/views/Position.jsx) | SLA position table, item drilldown, data quality and concentration panels. |
| [src/views/Exceptions.jsx](../src/views/Exceptions.jsx) | Failed service levels and failed/open-overdue item list. |
| [src/views/Pack.jsx](../src/views/Pack.jsx) | Print-ready monthly governance pack. |
| [src/views/Intelligence.jsx](../src/views/Intelligence.jsx) | Cross-month intelligence side panel and Q&A UI. |
| [src/components/](../src/components) | Shared UI pieces: rail, chips, icons, item table, logo, narrative card. |
| [src/lib/format.js](../src/lib/format.js) | Number, date, percentage and display formatting helpers. |
| [src/lib/sources.js](../src/lib/sources.js) | Colours/labels/marks for extract source types. |
| [src/styles.css](../src/styles.css) | All visual styling. |
| [scripts/](../scripts) | Developer/ops commands: load data, reset, verify against workbook, check Bedrock, run dev. |
| `*.test.js` | Regression tests for calendar, extract recognition and narrative guards. |
| [vite.config.js](../vite.config.js) | Frontend dev/build configuration. |
| [package.json](../package.json) | Scripts and dependencies. |
| [render.yaml](../render.yaml) | Hosting/deployment config. |
| [s3-policy.json](../s3-policy.json), [trust-policy.json](../trust-policy.json) | AWS deployment/role policy helpers. |
| [README.md](../README.md) | User-facing overview and run instructions. |
| [DEV_LOG.md](../DEV_LOG.md) | Development history and known decisions/fixes. |
| [CLAUDE.md](../CLAUDE.md) | Project working notes and constraints for future coding agents. |

## 11. One-Sentence Summary

Uploaded files are stored in `data/extracts`, parsed by column shape, scored item-by-item by `rules.js` using config-driven SLA definitions and `calendar.js` deadlines, classified by `outcome.js`, counted and rolled up by `engine.js`, saved as monthly JSON packs in `data/analyses`, and rendered by React without recalculating the SLA logic in the browser.

## 12. Restoring the Original Data and Extending the Reporting Period

Checked on 2026-10-01: the delivered files in `Claude_Data/` match commit
`ba7fa6f`, and both CSV and XLSX sets pass `npm run verify:real` with zero
differences. Their snapshot date is 2026-09-24. The working branch is `Karthik`;
`omkar/Ommkar` points at the same commit. Local `main` and `backup-karthik`
point at `fcb17ec`, which predates the BaNCS integration.

To rebuild the original dashboard data, stop the app, then run:

```powershell
cd "C:\Users\2871417\Desktop\AIB Life\AIB"
npm run data:load
npm run dev
```

`data:load` imports the original five CSVs, replaces the matching uploaded slots,
and rebuilds the monthly packs in the configured `DATA_DIR` (default `data/`).
There is no need to switch branches. Git ignores `data/`, so a hard reset does
not restore deleted extracts or regenerate packs. It can discard tracked code
changes and remove later commits from the current branch instead.

If the source files themselves are changed later and you specifically want to
discard those source-file edits, restore just that folder from the original
commit, then run `npm run data:load`:

```powershell
git restore --source=ba7fa6f -- Claude_Data
```

For the extended demo, use a complete replacement snapshot with activity for
25-30 September and a snapshot date in October. October-originated records will
create an October reporting pack automatically; no engine or dashboard change
is needed. September will have `partial: false`, while October will have
`partial: true` when the snapshot date is in October. A complete reporting
period can still contain missed or overdue records.

The snapshot date is derived from open workflow `Created Date` plus
`Pending Since Days`; a filename change alone does not move it. Merely
increasing pending ages would remove September's incomplete marker without
supplying the missing activity. A genuine later snapshot requires refreshed
extracts and updated statuses, closures, and pending ages across all five slots.
New snapshots must retain earlier history because uploads replace files rather
than append them.

The delivered workbook describes its original data as synthetic, but it is
still the reference dataset for verification. Additional generated demo
records should live in a separate, clearly labelled folder so that the original
CSV/XLSX twins and expected-results workbook continue to agree. The extension
is pending a choice between generated demo records and newer supplied extracts.
