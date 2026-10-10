"""Reproducible schema derivation; run only when deliberately updating the format."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.spec import PRIMITIVES, EXPRESSIONS

ROOT = Path(__file__).resolve().parents[1]
sample = json.loads((ROOT / 'examples/hyota.spec.json').read_text(encoding='utf-8'))


def derive(v):
    if isinstance(v, bool):
        return {'type': 'boolean'}
    if isinstance(v, dict):
        return {'type': 'object', 'required': list(v), 'additionalProperties': False,
                'properties': {k: derive(x) for k, x in v.items()}}
    if isinstance(v, list):
        return {'type': 'array', 'minItems': 1, 'maxItems': 32, 'items': derive(v[0]) if v else {}}
    if isinstance(v, str):
        s = {'type': 'string', 'minLength': 1, 'maxLength': 4000}
        if v.startswith('#'):
            s['pattern'] = '^#[0-9a-fA-F]{6}$'
        return s
    return {'type': 'integer' if isinstance(v, int) else 'number', 'minimum': 0, 'maximum': 5}


schema = derive(sample)
schema.update({'$schema': 'http://json-schema.org/draft-07/schema#', 'title': 'CharacterSpec'})


def at(path):
    node = schema
    for part in path.split('.'):
        node = node['items'] if part == '*' else node['properties'][part]
    return node


def limits(path, lo, hi):
    at(path).update(minimum=lo, maximum=hi)
    if path != 'version' and not path.startswith('game_constraints.') and path != 'brief.apparent_age':
        at(path)['type'] = 'number'


at('id').update(pattern='^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$', maxLength=64)
limits('version', 1, 100000)
limits('brief.apparent_age', 5, 100)
limits('proportions.total_height_m', .5, 2.5)
limits('proportions.height_heads', 2.5, 4.5)
for section, keys in {'head': ['width','depth'], 'neck': ['length','thickness'],
                      'torso': ['length','shoulder_width','hip_width','chest_depth'],
                      'arms': ['length','thickness','hand_size'],
                      'legs': ['length','thickness','foot_size']}.items():
    for key in keys:
        limits(f'proportions.{section}.{key}', .04, 2.)
for key in ['jaw_taper','cheek_puff','chin_point']:
    limits('proportions.head.' + key, 0, 1)
limits('proportions.torso.taper', 0, .6)
limits('face.eyes.size', .12, .34)
limits('face.eyes.spacing', .18, .65)
limits('face.eyes.height', -.25, .2)
limits('face.eyes.tilt_deg', -35, 35)
limits('face.eyes.iris_ratio', .2, .95)
limits('face.eyes.pupil_ratio', .1, .75)
limits('face.brows.thickness', .01, .09)
limits('face.brows.length', .08, .35)
limits('face.brows.angle_deg', -40, 40)
limits('face.brows.height_above_eye', .02, .25)
limits('face.nose.size', .005, .06)
limits('face.mouth.width', .04, .3)
limits('face.mouth.height', -.45, -.15)
limits('face.ears.size', .06, .3)
limits('hair.base_volume', 1, 1.5)
limits('hair.hairline_height', -.05, .45)
at('hair.clumps').update(minItems=4, maxItems=16)
at('hair.clumps.*.name').update(pattern='^[a-zA-Z0-9_]+$', maxLength=64)
limits('hair.clumps.*.root_az', -180, 180)
limits('hair.clumps.*.root_el', -50, 90)
limits('hair.clumps.*.length', .05, 1.4)
limits('hair.clumps.*.root_width', .025, .65)
limits('hair.clumps.*.twist_deg', -180, 180)
limits('hair.clumps.*.flatten', 0, 1)
for key in ['dir', 'bend']:
    at('hair.clumps.*.' + key).update(minItems=3, maxItems=3, items={'type':'number','minimum':-2,'maximum':2})
for path, values in {
    'face.eyes.shape': 'round almond sharp', 'face.nose.style': 'dot line none',
    'face.ears.style':'human elf', 'face.mouth.default':'small_smile neutral frown',
    'hair.clumps.*.tip':'sharp round',
    'hair.clumps.*.region':'crown top front bangs side_l side_r back ahoge',
    'outfit.pieces.*.type':'jacket shirt tunic scarf belt shorts pants boots gloves cape',
    'outfit.pieces.*.material':'cloth leather metal',
    'accessory.type':'sword dagger staff none', 'accessory.attach':'back hip_back hip_l hip_r hand_r',
}.items():
    at(path)['enum'] = values.split()
at('outfit.pieces').update(minItems=0, maxItems=16)
at('outfit.pieces.*.params').update(required=[], additionalProperties=False, properties={
    k: {'type':'number','minimum':0,'maximum':2} for k in
    ['length','puff','thickness','tail_length','width','cuff','height','chunk']})
at('outfit.pieces.*.params')['properties'].update({
    'sleeve':{'type':'string','enum':['none','short','long']},
    'collar':{'type':'string','enum':['none','low','high']},
    'tail_side':{'type':'string','enum':['left','right','back']},
    **{k:{'type':'boolean'} for k in ['open_front','pouch','fingerless']},
    'cuff_color':{'type':'string','pattern':'^#[0-9a-fA-F]{6}$'}})
at('accessory.params').update(required=[], properties={
    'blade_length':{'type':'number','minimum':.1,'maximum':3},
    'curve':{'type':'number','minimum':0,'maximum':1},
    'guard':{'type':'string','enum':['round','straight','none']},
    'handle_color':{'type':'string','pattern':'^#[0-9a-fA-F]{6}$'}})
at('palette')['required'] = ['skin','primary','secondary','accent','dark','outline']
for k in ['primary','secondary','accent','dark','hair']:
    at('palette')['properties'][k+'_shadow'] = {'type':'string','pattern':'^#[0-9a-fA-F]{6}$'}
schema['properties']['expressions'] = {
    'type':'object','required':EXPRESSIONS,'additionalProperties':False,
    'properties':{name:{'type':'object','additionalProperties':False,
        'properties':{p:{'type':'number','minimum':0,'maximum':1} for p in PRIMITIVES}}
        for name in EXPRESSIONS}}
limits('game_constraints.tri_budget', 2000, 100000)
limits('game_constraints.max_bones', 33, 128)
limits('game_constraints.materials_max', 1, 4)
at('game_constraints.texture_size').update(enum=[256,512,1024,2048,4096], maximum=4096)
(ROOT / 'schema/character_spec.schema.json').write_text(json.dumps(schema, indent=2)+'\n', encoding='utf-8')
