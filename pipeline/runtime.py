"""Persistence, process logging and file handoffs."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from .spec import ROOT, SpecError, deep_merge, validate_json, validate_spec

STAGES = ['style-bible', 'variants', 'select', 'base', 'production', 'face', 'export']


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(path)


class AwaitingDirector(Exception):
    pass


def role_text(role):
    text = (ROOT / 'roles' / f'{role}.md').read_text(encoding='utf-8')
    return re.sub(r'\A---\s*\n.*?\n---\s*\n', '', text, count=1, flags=re.S)


class Project:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.path = self.folder / 'project.json'
        self.state = read_json(self.path)

    def save(self):
        self.state['updated_at'] = now()
        write_json(self.path, self.state)

    @property
    def spec_path(self):
        return self.folder / self.state['spec_path']

    @property
    def spec(self):
        return validate_spec(read_json(self.spec_path))

    def status(self, stage, status, **extra):
        self.state['stages'].setdefault(stage, {}).update(status=status, timestamp=now(), **extra)
        self.save()

    def done(self, stage):
        return self.state['stages'].get(stage, {}).get('status') == 'done'

    def version(self, spec, reason):
        validate_spec(spec)
        n = len(self.state['spec_history']) + 1
        name = f'specs/v{n:03}.json'
        write_json(self.folder / name, spec)
        self.state['spec_path'] = name
        self.state['spec_history'].append({'path': name, 'reason': reason, 'timestamp': now()})
        self.save()

    def invalidate_after(self, stage):
        for later in STAGES[STAGES.index(stage)+1:]:
            self.state['stages'][later] = {'status':'pending'}
        self.save()


def create_project(folder, ident, spec=None, inspiration=None, rules=''):
    folder = Path(folder)
    if folder.exists() and any(folder.iterdir()):
        raise SpecError(f'Project already exists: {folder}')
    folder.mkdir(parents=True, exist_ok=True)
    for name in ['specs','handoff','logs','variants','renders','textures','export','reports']:
        (folder / name).mkdir(exist_ok=True)
    state = {'id':ident, 'created_at':now(), 'stages':{s:{'status':'pending'} for s in STAGES},
             'spec_history':[], 'spec_path':None, 'handoffs':[], 'artifacts':{},
             'inspiration':[str(Path(p).resolve()) for p in inspiration or []], 'rules':rules}
    write_json(folder / 'project.json', state)
    project = Project(folder)
    if spec:
        spec = deep_merge(spec, {'id':ident})
        project.version(spec, 'provided --from-spec')
        project.status('style-bible','done', source='from-spec')
    return project


def handoff(project, stage, context, schema, images=()):
    """One request per context fingerprint. Old responses cannot approve new geometry."""
    payload = {'context':context,'schema':schema,'images':[str(Path(p).resolve()) for p in images]}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    entry = next((h for h in reversed(project.state['handoffs'])
                  if h['stage']==stage and h['fingerprint']==fingerprint), None)
    if entry is None:
        num = len(project.state['handoffs'])+1
        stem = f'{num:02}_{stage}'
        entry = {'stage':stage,'fingerprint':fingerprint,'prompt':f'handoff/{stem}.prompt.md',
                 'response':f'handoff/{stem}.response.json','schema':schema,'status':'pending'}
        prompt = (role_text('director') + '\n\n## Stage: ' + stage + '\n\n' + context +
                  '\n\n## Images (absolute paths; inspect each)\n' +
                  '\n'.join(str(Path(p).resolve()) for p in images) +
                  '\n\n## Exact JSON response schema\n```json\n' + json.dumps(schema,indent=2) +
                  '\n```\nWrite JSON only to: ' + str(project.folder / entry['response']) + '\n')
        (project.folder / entry['prompt']).write_text(prompt,encoding='utf-8')
        project.state['handoffs'].append(entry)
        project.save()
    response = project.folder / entry['response']
    if not response.exists():
        project.status(stage,'awaiting_director',prompt=entry['prompt'])
        raise AwaitingDirector(f'Awaiting Director: {project.folder / entry["prompt"]}')
    answer = read_json(response)
    validate_json(answer, schema)
    entry['status'] = 'consumed'
    entry['consumed_at'] = now()
    project.save()
    return answer


def run_process(project, command, label, input_text=None, check=True):
    logs = project.folder / 'logs'
    logs.mkdir(exist_ok=True)
    stamp = f'{time.time_ns()}_{label}'
    start = time.monotonic()
    result = subprocess.run([str(c) for c in command], cwd=project.folder,
                            input=input_text, capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    (logs / (stamp + '.stdout.log')).write_text(result.stdout,encoding='utf-8')
    (logs / (stamp + '.stderr.log')).write_text(result.stderr,encoding='utf-8')
    write_json(logs / (stamp + '.json'), {'command':[str(c) for c in command],
        'cwd':str(project.folder),'duration_s':round(time.monotonic()-start,3),
        'exit_code':result.returncode,'timestamp':now()})
    summaries = [line for line in result.stdout.splitlines() if line.startswith('RESULT:')]
    for line in summaries:
        print(line, flush=True)
    if check and result.returncode:
        raise RuntimeError(f'{label} failed ({result.returncode}); logs: {logs / stamp}\n'
                           + result.stdout[-2500:] + result.stderr[-2500:])
    return result


def detect_blender(config):
    if config['blender_path'] != 'auto':
        path = Path(config['blender_path'])
        if not path.is_file():
            raise SpecError(f'Blender not found: {path}')
        return str(path)
    foundation = Path(os.environ.get('ProgramFiles','C:/Program Files')) / 'Blender Foundation'
    candidates = list(foundation.glob('Blender*/blender.exe'))
    if candidates:
        return str(max(candidates, key=lambda p:tuple(int(x) for x in re.findall(r'\d+',p.parent.name))))
    path = shutil.which('blender')
    if not path:
        raise SpecError('Blender not found; set blender_path in pipeline_config.json')
    return path


def first_json(text):
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == '{':
            try:
                return decoder.raw_decode(text[i:])[0]
            except ValueError:
                pass
    raise SpecError('No JSON object found in model response')


def model_answer(project, config, role, prompt, schema):
    exe = shutil.which('codex.exe') or shutil.which('codex')
    if not exe:
        raise SpecError('codex CLI not found')
    help_result = run_process(project,[exe,'exec','--help'],'codex_help')
    response_path = project.folder / 'logs' / f'{role}_{time.time_ns()}.response.json'
    schema_path = response_path.with_suffix('.schema.json')
    write_json(schema_path, schema)
    command = [exe,'exec','-m',config['models'][role],'-s','read-only','--skip-git-repo-check',
               '-c',f'model_reasoning_effort="{config["reasoning_effort"][role]}"',
               '--color','never']
    if '--output-schema' in help_result.stdout:
        command += ['--output-schema',str(schema_path)]
    if '--output-last-message' in help_result.stdout:
        command += ['-o',str(response_path)]
    command += config.get('codex_extra_args',[]) + ['--','-']
    result = run_process(project,command,role,input_text=prompt)
    answer = first_json(response_path.read_text(encoding='utf-8') if response_path.exists() else result.stdout)
    validate_json(answer,schema)
    return answer
