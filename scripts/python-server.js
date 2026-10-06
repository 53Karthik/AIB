import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const child = spawn(process.env.PYTHON_BIN || 'python', ['-m', 'backend.server'], {
  cwd: root,
  stdio: 'inherit',
});

child.on('error', (error) => {
  console.error(`Could not start Python: ${error.message}. Install backend/requirements.txt and set PYTHON_BIN if needed.`);
  process.exitCode = 1;
});
child.on('exit', (code) => { process.exitCode = code ?? 1; });
process.on('SIGINT', () => child.kill('SIGINT'));
process.on('SIGTERM', () => child.kill('SIGTERM'));
