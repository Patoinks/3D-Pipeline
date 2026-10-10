import argparse
import copy
import hashlib
import json
import random
import re
import sys
from pathlib import Path
from .spec import ROOT, SpecError, deep_merge, load_spec, validate_spec
from .runtime import (STAGES, Project, AwaitingDirector, create_project, detect_blender,
                      director_answer, director_backend, handoff, model_answer, read_json,
                      role_text, run_process, write_json)

REVIEW_SCHEMA = {'type':'object','required':['verdict','issues','spec_patch'],
    'additionalProperties':False,'properties':{'verdict':{'type':'string','enum':['approve','revise']},
    'issues':{'type':'array','items':{'type':'string'}},'spec_patch':{'type':'object'}}}
SELECT_SCHEMA = {'type':'object','additionalProperties':False,
    'properties':{'variant_id':{'type':'string'},'spec':{'type':'object'},
                  'merge':{'type':'object'},'provenance':{'type':'string'}}}
VARIANT_SCHEMA = {'type':'object','required':['variants'],'additionalProperties':False,
    'properties':{'variants':{'type':'array','minItems':1,'maxItems':100,
    'items':{'type':'object','required':['id','label','theme','rationale','spec_patch'],
    'additionalProperties':False,'properties':{**{k:{'type':'string'} for k in
    ['id','label','theme','rationale']},'spec_patch':{'type':'object'}}}}}}
TECH_SCHEMA = {'type':'object','required':['diagnosis','settings_patch','retry','needs_director'],
    'additionalProperties':False,'properties':{'diagnosis':{'type':'string'},
    'settings_patch':{'type':'object'},'retry':{'type':'boolean'},
    'needs_director':{'type':['null','string']}}}


def mock_variants(spec, count, themes):
    seed = int(hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:16],16)
    rng = random.Random(seed)
    variants = []
    for i in range(count):
        hair = copy.deepcopy(spec['hair'])
        for c in hair['clumps']:
            c['length'] = min(1.4,max(.05,c['length']*rng.uniform(.78,1.24)))
            c['root_az'] = min(180,max(-180,c['root_az']+rng.uniform(-12,12)))
            c['twist_deg'] = rng.uniform(-35,35)
        if i % 3 == 1 and len(hair['clumps']) > 4:
            hair['clumps'] = [c for c in hair['clumps'] if c['region'] != 'back'] or hair['clumps'][:4]
        variants.append({'id':f'v{i:02}', 'label':f'Exploration {i+1}',
            'theme':themes[i%len(themes)],'rationale':'Distinct crest flow and head/body silhouette.',
            'spec_patch':{'hair':hair,'proportions':{'height_heads':round(rng.uniform(2.9,4.0),3)}}})
    return variants


class Pipeline:
    def __init__(self, config):
        self.config = config
        self.output = Path(config['output_root'])
        if not self.output.is_absolute():
            self.output = (ROOT / self.output).resolve()

    def project(self, ident):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',ident):
            raise SpecError('Invalid project id')
        folder = self.output / ident
        if not (folder / 'project.json').exists():
            raise SpecError(f'Unknown project: {ident}')
        return Project(folder)

    def director(self, p, stage):
        """Callable that asks Claude automatically, or None to wait for a manual answer.
        Automatic review rounds per stage are capped so Claude cannot loop forever."""
        if director_backend(self.config) != 'claude':
            return None
        rounds = sum(h['reason'].startswith(f'Director {stage} revision')
                     for h in p.state['spec_history'])
        if rounds >= self.config.get('director', {}).get('max_rounds', 3):
            print(f'Director reached max_rounds on {stage}; waiting for a manual answer')
            return None
        print(f'Director (Claude) working on {stage}...', flush=True)
        return lambda prompt, schema, images: director_answer(p, self.config, prompt, schema, images)

    def blender(self, p, script, *args, spec=None, out=None, check=True):
        return run_process(p,[detect_blender(self.config),'-b','--factory-startup',
            '--python-exit-code','1','--python',ROOT / 'blender' / script,'--',
            '--spec',spec or p.spec_path,'--out',out or p.folder,*args],
            Path(script).stem,check=check)

    def style(self,p):
        if p.done('style-bible'):
            return
        schema = read_json(ROOT / 'schema/character_spec.schema.json')
        answer = handoff(p,'style-bible',f'Create CharacterSpec with id {p.state["id"]}.\nRules: '
            + p.state['rules'],schema,p.state['inspiration'],self.director(p,'style-bible'))
        if answer['id'] != p.state['id']:
            raise SpecError('Director spec id must match project id')
        p.version(answer,'Director style bible')
        p.status('style-bible','done')

    def variants(self,p,count=10,themes='cute,heroic,mischievous',request='',mock=False,dry_run=False):
        self.style(p)
        themes = [t.strip() for t in themes.split(',') if t.strip()] or ['cute']
        prompt = role_text('explorer') + '\nCurrent spec:\n' + json.dumps(p.spec,indent=2) + \
                 f'\nGenerate {count} variants. Themes: {themes}. Request: {request}\n'
        prompt_path = p.folder / 'handoff/explorer.prompt.md'
        prompt_path.write_text(prompt,encoding='utf-8')
        if dry_run:
            p.status('variants','dry_run',prompt=str(prompt_path))
            print(prompt_path)
            return
        answer = {'variants':mock_variants(p.spec,count,themes)} if mock else \
                 model_answer(p,self.config,'explorer',prompt,VARIANT_SCHEMA)
        self.process_variants(p,answer['variants'],render=True)

    def process_variants(self,p,variants,render):
        accepted, rejected, seen = [], [], set()
        for v in variants:
            try:
                ident = v['id']
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',ident) or ident in seen:
                    raise SpecError('Unsafe/duplicate variant id')
                seen.add(ident)
                merged = deep_merge(p.spec,v['spec_patch'])
                for path in [('id',),('brief','originality_limits'),('game_constraints',),('expressions',)]:
                    a,b = p.spec,merged
                    for key in path:
                        a,b = a[key],b[key]
                    if a != b:
                        raise SpecError(f'Explorer changed protected field {".".join(path)}')
                validate_spec(merged)
                directory = p.folder / 'variants' / ident
                write_json(directory / 'spec.json',merged)
                accepted.append({**v,'spec_path':str(directory / 'spec.json'),
                                 'sheet':str(directory / 'renders/turnaround.png')})
            except (ValueError,KeyError,TypeError) as e:
                rejected.append({'id':v.get('id','?'),'reason':str(e)})
        write_json(p.folder / 'variants/index.json',{'variants':accepted,'rejected':rejected})
        if not accepted:
            raise SpecError('No valid variants; see variants/index.json')
        if render:
            for v in accepted:
                folder = Path(v['spec_path']).parent
                self.blender(p,'build_blockout.py',spec=v['spec_path'],out=folder)
                self.blender(p,'render_sheet.py','--blend',folder / 'blockout.blend',spec=v['spec_path'],out=folder)
            self.blender(p,'render_sheet.py','--contact',*[v['sheet'] for v in accepted])
            p.state['artifacts']['contact_sheet'] = str(p.folder / 'renders/contact_sheet.png')
        p.invalidate_after('variants')
        p.status('variants','done',count=len(accepted),rejected=len(rejected))

    def select(self,p):
        if p.done('select'):
            return
        if not p.done('variants'):
            raise SpecError('Run variants first')
        variants = read_json(p.folder / 'variants/index.json')['variants']
        context = 'Select champion: variant_id OR full spec OR merge patch; include provenance.\n' + \
            json.dumps(variants,indent=2) + '\nCurrent spec:\n' + json.dumps(p.spec,indent=2)
        answer = handoff(p,'select',context,SELECT_SCHEMA,[p.folder / 'renders/contact_sheet.png'],
                         self.director(p,'select'))
        choices = [k for k in ['variant_id','spec','merge'] if k in answer]
        if len(choices) != 1:
            raise SpecError('Select exactly one of variant_id, spec, merge')
        if 'variant_id' in answer:
            v = next((v for v in variants if v['id']==answer['variant_id']),None)
            if not v:
                raise SpecError('Unknown variant_id')
            spec = load_spec(v['spec_path'])
        elif 'spec' in answer:
            spec = answer['spec']
        else:
            if not answer.get('provenance'):
                raise SpecError('Merge requires provenance notes')
            spec = deep_merge(p.spec,answer['merge'])
        if spec['id'] != p.state['id']:
            raise SpecError('Champion id must match project')
        p.version(spec,'Director champion: '+answer.get('provenance',answer.get('variant_id','spec')))
        p.invalidate_after('select')
        p.status('select','done')

    def review(self,p,stage,image):
        answer = handoff(p,stage,'Review geometry/expressions.\nCurrent spec:\n'+json.dumps(p.spec,indent=2),
                         REVIEW_SCHEMA,[image],self.director(p,stage))
        if answer['verdict']=='approve':
            if answer['spec_patch']:
                raise SpecError('Approve must have an empty spec_patch; use revise for changes')
            p.status(stage,'done')
            return True
        if not answer['spec_patch']:
            raise SpecError('Revise requires a concrete spec_patch')
        spec = deep_merge(p.spec,answer['spec_patch'])
        if spec['id'] != p.state['id']:
            raise SpecError('Revision cannot change project id')
        p.version(spec,f'Director {stage} revision: {answer["issues"]}')
        p.status('base','pending')
        p.invalidate_after('base')
        return False

    def base(self,p):
        self.select(p)
        if p.done('base'):
            return
        record = p.state['stages']['base']
        if record.get('built_spec') != p.state['spec_path']:
            p.status('base','running')
            self.blender(p,'build_base.py')
            self.blender(p,'render_sheet.py','--blend',p.folder / 'base.blend')
            p.state['artifacts'].update(base=str(p.folder/'base.blend'),
                                       base_sheet=str(p.folder/'renders/turnaround.png'))
            p.status('base','built',built_spec=p.state['spec_path'])
        if not self.review(p,'base',p.folder / 'renders/turnaround.png'):
            self.base(p)

    def production(self,p,retries=2):
        self.base(p)
        if p.done('production'):
            return
        settings = p.folder / 'production_settings.json'
        if not settings.exists():
            write_json(settings,read_json(ROOT/'production_settings.json'))
        for attempt in range(retries+1):
            p.status('production','running',attempt=attempt)
            result = self.blender(p,'production.py','--settings',settings,check=False)
            validation = self.blender(p,'validate.py','--phase','production',check=False) if result.returncode==0 else None
            if result.returncode==0 and validation.returncode==0:
                p.state['artifacts']['production'] = str(p.folder/'production.blend')
                p.status('production','done')
                return
            if attempt == retries:
                p.status('production','failed')
                raise RuntimeError('Production retries exhausted; see reports and logs')
            report = read_json(p.folder/'reports/validation.json') if validation else {'build_failed':True}
            prompt = role_text('technician')+'\nReport:\n'+json.dumps(report,indent=2)+\
                '\nSettings:\n'+settings.read_text(encoding='utf-8')+'\nLogs:\n'+\
                result.stdout[-12000:]+result.stderr[-6000:] + (validation.stdout[-6000:] if validation else '')
            (p.folder/'handoff/technician.prompt.md').write_text(prompt,encoding='utf-8')
            answer = model_answer(p,self.config,'technician',prompt,TECH_SCHEMA)
            write_json(p.folder/f'logs/technician_attempt_{attempt}.json',answer)
            if answer['needs_director'] or not answer['retry']:
                p.status('production','needs_director',reason=answer['needs_director'] or answer['diagnosis'])
                raise AwaitingDirector('Technician needs Director: '+str(answer['needs_director'] or answer['diagnosis']))
            write_json(settings,deep_merge(read_json(settings),answer['settings_patch']))

    def face(self,p,retries=2):
        self.production(p,retries)
        if p.done('face'):
            return
        record = p.state['stages']['face']
        if record.get('built_spec') != p.state['spec_path']:
            self.blender(p,'face_rig.py')
            p.state['artifacts']['expressions_sheet'] = str(p.folder/'renders/expressions_sheet.png')
            p.status('face','built',built_spec=p.state['spec_path'])
        if not self.review(p,'face',p.folder/'renders/expressions_sheet.png'):
            self.face(p,retries)

    def export(self,p,retries=2):
        self.face(p,retries)
        if p.done('export'):
            return
        p.status('export','running')
        self.blender(p,'export_fbx.py')
        self.blender(p,'validate.py','--phase','export')
        p.state['artifacts'].update(fbx=str(p.folder/f'export/{p.state["id"]}.fbx'),
                                   validation=str(p.folder/'reports/validation.json'))
        p.status('export','done')

    def approve(self,p):
        pending = [h for h in p.state['handoffs'] if h['status']=='pending' and
                   not (p.folder/h['response']).exists()]
        if not pending:
            if p.done('variants') and not p.done('select'):
                try:
                    self.select(p)
                except AwaitingDirector:
                    pass
                return self.approve(p)
            print('No pending handoff')
            return
        entry = pending[-1]
        if entry['stage']=='style-bible':
            raise SpecError('approve cannot invent a style bible; use --from-spec or Director response')
        answer = {'variant_id':read_json(p.folder/'variants/index.json')['variants'][0]['id'],
                  'provenance':'Smoke helper: variant 0'} if entry['stage']=='select' else \
                 {'verdict':'approve','issues':[],'spec_patch':{}}
        write_json(p.folder/entry['response'],answer)
        print('Smoke/test approval written (NOT a real Director review): '+str(p.folder/entry['response']))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Anime/Chibi pipeline (stdlib orchestrator)')
    parser.add_argument('--config',type=Path,default=ROOT/'pipeline_config.json')
    parser.add_argument('--output-root',type=Path)
    sub = parser.add_subparsers(dest='command',required=True)
    for name in ['new','style-bible','variants','select','base','production','face','export','run','status','approve']:
        s = sub.add_parser(name)
        s.add_argument('id')
        if name=='new':
            s.add_argument('--from-spec',type=Path)
            s.add_argument('--inspiration',nargs='+',default=[])
            s.add_argument('--rules',default='')
        if name=='variants':
            s.add_argument('--count',type=int,default=10)
            s.add_argument('--themes',default='cute,heroic,mischievous')
            s.add_argument('--request',default='')
            mode = s.add_mutually_exclusive_group()
            mode.add_argument('--mock',action='store_true')
            mode.add_argument('--dry-run',action='store_true')
        if name in ['production','face','export','run']:
            s.add_argument('--max-retries',type=int,default=2)
    args = parser.parse_args(argv)
    try:
        config = read_json(args.config)
        if args.output_root:
            config['output_root'] = str(args.output_root.resolve())
        pipe = Pipeline(config)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',args.id):
            raise SpecError('Invalid project id')
        if args.command=='new':
            for image in args.inspiration:
                if not Path(image).is_file():
                    raise SpecError(f'Inspiration missing: {image}')
            p = create_project(pipe.output/args.id,args.id,
                load_spec(args.from_spec) if args.from_spec else None,args.inspiration,args.rules)
            print(p.folder)
            return 0
        p = pipe.project(args.id)
        if args.command=='style-bible':
            pipe.style(p)
        elif args.command=='variants':
            if not 1 <= args.count <= 100:
                raise SpecError('count must be 1..100')
            pipe.variants(p,args.count,args.themes,args.request,args.mock,args.dry_run)
        elif args.command=='status':
            for stage in STAGES:
                print(f'{stage:14} {p.state["stages"][stage].get("status","pending"):20} '
                      f'{p.state["stages"][stage].get("timestamp","")}')
        elif args.command=='run':
            pipe.style(p)
            if not p.done('variants'):
                pipe.variants(p)
            pipe.export(p,args.max_retries)
        elif args.command in ['production','face','export']:
            if args.max_retries < 0:
                raise SpecError('max-retries must be nonnegative')
            getattr(pipe,args.command)(p,args.max_retries)
        else:
            getattr(pipe,args.command)(p)
        return 0
    except AwaitingDirector as e:
        print(e)
        return 3
    except (OSError,ValueError,RuntimeError,KeyError) as e:
        print(f'ERROR: {e}',file=sys.stderr)
        return 1
