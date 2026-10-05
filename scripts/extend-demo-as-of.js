import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SOURCE = path.join(ROOT, 'Claude_Data', 'WRKFLWEXT_7431728022023_1781324092026.csv');
const DAYS_TO_ADVANCE = 7;
const MARKER = 'Synthetic extension: as of 01/10/2026';

function parseRow(line) {
  const cells = [];
  let value = '';
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quoted && ch === '"' && line[i + 1] === '"') {
      value += '"';
      i++;
    } else if (ch === '"') quoted = !quoted;
    else if (ch === ',' && !quoted) {
      cells.push(value);
      value = '';
    } else value += ch;
  }
  cells.push(value);
  return cells;
}

function csvCell(value) {
  const text = String(value ?? '');
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

const lines = fs.readFileSync(SOURCE, 'utf8').replace(/^\uFEFF/, '').split(/\r?\n/);
if (lines[0].includes(MARKER)) {
  fs.writeFileSync(SOURCE, lines.join('\n'));
  console.log('Demo extract is already extended to 1 October 2026.');
  process.exit(0);
}

const headers = parseRow(lines[1]);
const pendingIndex = headers.indexOf('Pending Since Days');
if (pendingIndex < 0) throw new Error('Pending Since Days column not found');

let changed = 0;
for (let i = 2; i < lines.length; i++) {
  if (!lines[i]) continue;
  const cells = parseRow(lines[i]);
  const pending = Number(cells[pendingIndex]);
  if (!Number.isFinite(pending)) continue;
  cells[pendingIndex] = pending + DAYS_TO_ADVANCE;
  lines[i] = cells.map(csvCell).join(',');
  changed++;
}

lines[0] = lines[0].replace('Workflow extract', `Workflow extract - ${MARKER}`);
fs.writeFileSync(SOURCE, lines.join('\n'));
console.log(`Advanced ${changed} open workflows by ${DAYS_TO_ADVANCE} days.`);
