"""Coordena o Sol (Codex CLI) nas tarefas de tools/sol_tasks, uma de cada vez.

Uso (na raiz do repo, no PC com Codex + Blender):
    python tools/delegate.py            # corre todas as tarefas que ainda não passaram
    python tools/delegate.py 03         # corre só a tarefa 03
O Sol escreve código no repo (sandbox workspace-write). Cada relatório fica em
tools/sol_runs/<tarefa>.json; depois revês com `git diff` e fazes commit/push.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / 'tools' / 'sol_tasks'
RUNS = ROOT / 'tools' / 'sol_runs'
MODEL, EFFORT = 'gpt-6.1-sol', 'high'


def first_json(text):
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == '{':
            try:
                return decoder.raw_decode(text[i:])[0]
            except ValueError:
                pass
    return None


def run(task):
    exe = shutil.which('codex.exe') or shutil.which('codex')
    if not exe:
        raise SystemExit('codex CLI não encontrado no PATH')
    RUNS.mkdir(exist_ok=True)
    out = RUNS / (task.stem + '.last.txt')
    prompt = (TASKS / '00_common.md').read_text(encoding='utf-8') + '\n\n' + \
        task.read_text(encoding='utf-8')
    previous = RUNS / (task.stem + '.json')
    if previous.exists():
        prompt += '\n\n## Tentativa anterior (corrige o que ficou por fazer)\n' + \
            previous.read_text(encoding='utf-8')
    command = [exe, 'exec', '-m', MODEL, '-c', f'model_reasoning_effort="{EFFORT}"',
               '-s', 'workspace-write', '--skip-git-repo-check', '--color', 'never',
               '-C', str(ROOT), '-o', str(out), '-']
    print(f'==> Sol: {task.name}', flush=True)
    subprocess.run(command, input=prompt, text=True, encoding='utf-8', cwd=ROOT)
    report = first_json(out.read_text(encoding='utf-8')) if out.exists() else None
    report = report or {'task': task.stem, 'tested': False, 'known_issues': ['sem relatório JSON']}
    previous.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    ok = report.get('tested') and not report.get('known_issues')
    print(f'    tested={report.get("tested")} issues={len(report.get("known_issues") or [])}')
    return ok


def main(argv):
    tasks = sorted(t for t in TASKS.glob('[0-9][0-9]_*.md') if not t.name.startswith('00'))
    if argv:
        tasks = [t for t in tasks if t.name.startswith(tuple(argv))]
    for task in tasks:
        done = RUNS / (task.stem + '.json')
        if not argv and done.exists():
            r = json.loads(done.read_text(encoding='utf-8'))
            if r.get('tested') and not r.get('known_issues'):
                continue
        if not run(task):
            print(f'Parei em {task.name}: vê tools/sol_runs/{task.stem}.json')
            return 1
    print('Todas as tarefas passaram. Revê `git diff`, faz commit e push.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
