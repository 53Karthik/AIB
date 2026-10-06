#!/usr/bin/env node
/** Runs the API and the Vite dev server together, so `npm run dev` is the only command. */
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const npx = process.platform === 'win32' ? 'npx.cmd' : 'npx';

const children = [
  process.argv.includes('--node-backend')
    ? spawn(process.execPath, ['server/index.js'], { cwd: ROOT, stdio: 'inherit' })
    : spawn(process.env.PYTHON_BIN || 'python', ['-m', 'backend.server'], { cwd: ROOT, stdio: 'inherit' }),
  spawn(npx, ['vite'], { cwd: ROOT, stdio: 'inherit', shell: process.platform === 'win32' }),
];

const shutdown = (code = 0) => {
  for (const c of children) if (!c.killed) c.kill();
  process.exit(code);
};
process.on('SIGINT', () => shutdown());
process.on('SIGTERM', () => shutdown());
for (const child of children) {
  child.on('exit', (code) => shutdown(code ?? 1));
  child.on('error', (error) => {
    console.error(`Could not start development process: ${error.message}`);
    shutdown(1);
  });
}
