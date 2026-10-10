"""Deterministic Blender geometry, shading, rendering and rig utilities."""
import argparse
import json
import math
import os
import sys
import traceback
from pathlib import Path
import bpy
import bmesh
import numpy as np
from mathutils import Vector

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOL_ROOT))
from pipeline.spec import load_spec, PRIMITIVES, EXPRESSIONS


def arguments(extra=None):
    p = argparse.ArgumentParser()
    p.add_argument('--spec',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--blend',type=Path)
    if extra:
        extra(p)
    args = p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    args.out = args.out.resolve()
    args.out.mkdir(parents=True,exist_ok=True)
    return args,load_spec(args.spec)


def entry(func):
    try:
        result = func()
        print('RESULT:'+json.dumps({'ok':True,**(result or {})}),flush=True)
    except Exception as e:
        traceback.print_exc()
        print('RESULT:'+json.dumps({'ok':False,'error':str(e)}),flush=True)
        # --python-exit-code also catches this, including direct script invocation.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)


def clean_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for data in list(bpy.data.materials):
        bpy.data.materials.remove(data)
    bpy.context.scene.unit_settings.system = 'METRIC'
    bpy.context.scene.unit_settings.scale_length = 1


def active(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def apply(obj, modifier):
    active(obj)
    bpy.ops.object.modifier_apply(modifier=modifier.name)


def linear_color(hexcolor):
    rgb = [int(hexcolor[i:i+2],16)/255 for i in (1,3,5)]
    return tuple(c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in rgb)+(1,)


def toon(name,color,shadow=None,outline=False,hair=False):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = linear_color(color)
    mat.use_nodes = True
    mat['base_color'] = list(mat.diffuse_color)
    nodes,links = mat.node_tree.nodes,mat.node_tree.links
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    emit = nodes.new('ShaderNodeEmission')
    if outline:
        emit.inputs['Color'].default_value = mat.diffuse_color
        mat.use_backface_culling = True
        links.new(emit.outputs[0],output.inputs['Surface'])
        return mat
    diffuse = nodes.new('ShaderNodeBsdfDiffuse')
    diffuse.inputs['Color'].default_value = (1,1,1,1)
    rgb = nodes.new('ShaderNodeShaderToRGB')
    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.name = 'ToonSteps'
    ramp.color_ramp.interpolation = 'CONSTANT'
    ramp.color_ramp.elements[0].position = .0
    ramp.color_ramp.elements[0].color = linear_color(shadow) if shadow else tuple(c*.75 for c in mat.diffuse_color[:3])+(1,)
    ramp.color_ramp.elements[1].position = .42
    ramp.color_ramp.elements[1].color = mat.diffuse_color
    links.new(diffuse.outputs[0],rgb.inputs[0])
    links.new(rgb.outputs[0],ramp.inputs[0])
    source = ramp.outputs[0]
    if hair:
        attr = nodes.new('ShaderNodeVertexColor')
        attr.layer_name = 'HairColor'
        multiply = nodes.new('ShaderNodeMixRGB')
        multiply.blend_type = 'MULTIPLY'
        multiply.inputs[0].default_value = 1
        # Ramp represents illumination; HairColor holds the actual palette gradient.
        for el in ramp.color_ramp.elements:
            el.color = ((.72,.72,.72,1) if el.position<.4 else (1,1,1,1))
        links.new(source,multiply.inputs[1])
        links.new(attr.outputs['Color'],multiply.inputs[2])
        source = multiply.outputs[0]
    links.new(source,emit.inputs['Color'])
    links.new(emit.outputs[0],output.inputs['Surface'])
    return mat


def mesh(name,verts,faces,material,category='Skin_Face',part=None,smooth=True):
    data = bpy.data.meshes.new(name)
    data.from_pydata(verts,[],faces)
    data.update()
    obj = bpy.data.objects.new(name,data)
    bpy.context.collection.objects.link(obj)
    if material:
        data.materials.append(material)
    obj['category'] = category
    obj['part'] = part or name
    for f in data.polygons:
        f.use_smooth = smooth
    return obj


def sphere(name,loc,scale,material,category='Skin_Face',segments=20,rings=12,deform=None):
    # Quad latitude loops with triangle pole fans, no duplicate pole vertices.
    verts = [(0,0,-1)]
    for j in range(1,rings):
        el = -math.pi/2+j*math.pi/rings
        for i in range(segments):
            az = 2*math.pi*i/segments
            verts.append((math.cos(el)*math.sin(az),-math.cos(el)*math.cos(az),math.sin(el)))
    verts.append((0,0,1))
    faces = [(0,1+(i+1)%segments,1+i) for i in range(segments)]
    for j in range(rings-2):
        a,b = 1+j*segments,1+(j+1)*segments
        for i in range(segments):
            k = (i+1)%segments
            faces.append((a+i,a+k,b+k,b+i))
    top = len(verts)-1
    a = 1+(rings-2)*segments
    faces.extend((a+i,a+(i+1)%segments,top) for i in range(segments))
    points = []
    for x,y,z in verts:
        if deform:
            x,y,z = deform(x,y,z)
        points.append(tuple(Vector(loc)+Vector((x*scale[0],y*scale[1],z*scale[2]))))
    obj = mesh(name,points,faces,material,category)
    recalc(obj)
    return obj


def box(name,loc,scale,material,category,bevel=0):
    bpy.ops.mesh.primitive_cube_add(size=2,location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    active(obj)
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    obj.data.materials.append(material)
    obj['category']=category
    obj['part']=name
    if bevel:
        m = obj.modifiers.new('Soft corners','BEVEL')
        m.width = bevel
        m.segments = 2
        apply(obj,m)
    return obj


def recalc(obj,merge=0):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    if merge:
        bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=merge)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def group(obj,name,indices=None):
    vg = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
    vg.add(list(indices) if indices is not None else list(range(len(obj.data.vertices))),1,'REPLACE')
    return vg


def outline(obj,material,width):
    obj.data.materials.append(material)
    m = obj.modifiers.new('Inverted hull outline','SOLIDIFY')
    m.thickness = width
    m.offset = 1
    m.use_flip_normals = True
    m.material_offset = len(obj.data.materials)-1
    m.material_offset_rim = len(obj.data.materials)-1
    m.use_rim = False
    obj['outline_width'] = width


def dimensions(spec):
    p = spec['proportions']
    h = p['total_height_m']/p['height_heads']
    head_z = p['total_height_m']-.5*h
    neck_z = head_z-.5*h-p['neck']['length']*h
    hip_z = neck_z-p['torso']['length']*h
    shoulder_z = neck_z-.12*h
    shoulder_x = p['torso']['shoulder_width']*.5*h
    elbow = (shoulder_x+p['arms']['length']*.42*h,0,shoulder_z-.35*p['arms']['length']*h)
    wrist = (shoulder_x+p['arms']['length']*.78*h,0,shoulder_z-.65*p['arms']['length']*h)
    return {'H':h,'head_z':head_z,'neck_z':neck_z,'hip_z':hip_z,
            'shoulder_z':shoulder_z,'shoulder_x':shoulder_x,'elbow':elbow,'wrist':wrist}


def head_deform(spec,x,y,z):
    hp = spec['proportions']['head']
    lower = max(0,-z)
    x *= 1-hp['jaw_taper']*.55*lower
    x *= 1+hp['cheek_puff']*.2*math.exp(-((z+.18)/.32)**2)
    y *= 1-hp['chin_point']*.16*lower
    return x,y,z


def face_y(spec,x,z):
    d = dimensions(spec)
    h = d['H']
    hp = spec['proportions']['head']
    nz = (z-d['head_z'])/(.5*h)
    factor = 1-hp['jaw_taper']*.55*max(0,-nz)
    factor *= 1+hp['cheek_puff']*.2*math.exp(-((nz+.18)/.32)**2)
    nx = x/(hp['width']*.5*h*factor)
    return -hp['depth']*.5*h*math.sqrt(max(.015,1-nx*nx-nz*nz))*(1-hp['chin_point']*.16*max(0,-nz))


def decal(name,coords,faces,material,spec,head,offset=.007):
    h = dimensions(spec)['H']
    obj = mesh(name,[(x,face_y(spec,x,z)-offset*h,z) for x,z in coords],faces,material,part=name)
    group(obj,name)
    m = obj.modifiers.new('Project to head','SHRINKWRAP')
    m.target = head
    m.wrap_method = 'NEAREST_SURFACEPOINT'
    m.wrap_mode = 'OUTSIDE'
    m.offset = offset*h
    apply(obj,m)
    # Geometry is intentionally front-facing; do not recalc disconnected decals after join.
    return obj


def disc(name,cx,cz,rx,rz,material,spec,head,tilt=0,shape='round',offset=.008):
    n = 32
    angle = math.radians(tilt)
    coords=[(cx,cz)]
    for i in range(n):
        t=2*math.pi*i/n
        x,z=rx*math.cos(t),rz*math.sin(t)
        if shape=='almond':
            z*=abs(math.sin(t))**.35
        elif shape=='sharp':
            z*=.8
            z+=x*.22
        coords.append((cx+x*math.cos(angle)-z*math.sin(angle),cz+x*math.sin(angle)+z*math.cos(angle)))
    return decal(name,coords,[(0,1+i,1+(i+1)%n) for i in range(n)],material,spec,head,offset)


def strip(name,coords,width,material,spec,head,offset=.018):
    verts=[]
    for i,(x,z) in enumerate(coords):
        direction=Vector(coords[min(len(coords)-1,i+1)])-Vector(coords[max(0,i-1)])
        direction.normalize()
        normal=Vector((-direction.y,direction.x))*width/2
        verts.extend([(x+normal.x,z+normal.y),(x-normal.x,z-normal.y)])
    return decal(name,verts,[(2*i,2*i+1,2*i+3,2*i+2) for i in range(len(coords)-1)],material,spec,head,offset)


def body_skeleton(spec,material):
    d=dimensions(spec)
    h=d['H']; p=spec['proportions']
    verts=[]; edges=[]; radii=[]
    def v(pos,r,parent=None):
        idx=len(verts); verts.append(pos); radii.append(r)
        if parent is not None:
            edges.append((parent,idx))
        return idx
    hip=v((0,0,d['hip_z']),(.31*p['torso']['hip_width']*h,.45*p['torso']['chest_depth']*h))
    spine=v((0,0,d['hip_z']+.25*p['torso']['length']*h),(.34*h,.19*h),hip)
    chest=v((0,0,d['neck_z']-.23*h),(.34*p['torso']['shoulder_width']*h,.48*p['torso']['chest_depth']*h),spine)
    neck=v((0,0,d['neck_z']+.06*h),(p['neck']['thickness']*h/2,)*2,chest)
    for side in [1,-1]:
        s=v((side*d['shoulder_x']*.8,0,d['shoulder_z']),(.13*h,)*2,chest)
        s=v((side*d['shoulder_x'],0,d['shoulder_z']),(.12*h,)*2,s)
        e=Vector(d['elbow']); e.x*=side
        w=Vector(d['wrist']); w.x*=side
        prev=s
        for factor in [.15,.85,1]:
            start=Vector(verts[s])
            prev=v(tuple(start.lerp(e,factor)),(p['arms']['thickness']*h/2,)*2,prev)
        for factor in [.15,.85,1]:
            prev=v(tuple(e.lerp(w,factor)),(p['arms']['thickness']*h/2*.85,)*2,prev)
        knee=Vector((side*p['torso']['hip_width']*.28*h,0,d['hip_z']*.52))
        ankle=Vector((knee.x,0,.13*h))
        a=v((side*p['torso']['hip_width']*.25*h,0,d['hip_z']-.06*h),(.16*h,)*2,hip)
        prev=a
        for factor in [.15,.85,1]:
            prev=v(tuple(Vector(verts[a]).lerp(knee,factor)),(p['legs']['thickness']*.5*h,)*2,prev)
        for factor in [.15,.85,1]:
            prev=v(tuple(knee.lerp(ankle,factor)),(p['legs']['thickness']*.45*h,)*2,prev)
    data=bpy.data.meshes.new('BodySkeleton'); data.from_pydata(verts,edges,[])
    obj=bpy.data.objects.new('Body',data); bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material); obj['category']='Skin_Face'; obj['part']='Body'
    skin=obj.modifiers.new('Joint loops','SKIN')
    bpy.context.view_layer.update()
    for i,r in enumerate(radii):
        obj.data.skin_vertices[0].data[i].radius=r
    obj.data.skin_vertices[0].data[0].use_root=True
    apply(obj,skin)
    sub=obj.modifiers.new('Soft body','SUBSURF'); sub.levels=1
    apply(obj,sub)
    recalc(obj)
    for poly in obj.data.polygons:
        poly.use_smooth=True
    return obj


def shell(body,name,predicate,material,h,offset=.025):
    bm=bmesh.new(); bm.from_mesh(body.data)
    rejected=[v for v in bm.verts if not predicate(v.co)]
    bmesh.ops.delete(bm,geom=rejected,context='VERTS')
    data=bpy.data.meshes.new(name); bm.to_mesh(data); bm.free()
    obj=bpy.data.objects.new(name,data); bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material); obj['category']='Outfit'; obj['part']=name
    if not len(data.polygons):
        raise ValueError('Empty clothing shell: '+name)
    # Push along normals, preserving the inherited body topology.
    data.update()
    for v in data.vertices:
        v.co += v.normal*offset*h
    solid=obj.modifiers.new('Clothing thickness','SOLIDIFY'); solid.thickness=.018*h
    apply(obj,solid)
    recalc(obj)
    return obj


def ribbon(name,points,width,material,h):
    # Bevel with a thin rectangular curve profile, then convert to a skinnable mesh.
    profile=bpy.data.curves.new(name+'_profile','CURVE'); profile.dimensions='2D'
    ps=profile.splines.new('POLY'); ps.points.add(3)
    for pt,co in zip(ps.points,[(-width/2,-.008*h,0,1),(width/2,-.008*h,0,1),
                              (width/2,.008*h,0,1),(-width/2,.008*h,0,1)]):
        pt.co=co
    ps.use_cyclic_u=True
    po=bpy.data.objects.new(name+'_profile',profile); bpy.context.collection.objects.link(po)
    data=bpy.data.curves.new(name,'CURVE'); data.dimensions='3D'; data.resolution_u=6
    sp=data.splines.new('BEZIER'); sp.bezier_points.add(len(points)-1)
    for pt,co in zip(sp.bezier_points,points):
        pt.co=co; pt.handle_left_type='AUTO'; pt.handle_right_type='AUTO'
    data.bevel_mode='OBJECT'; data.bevel_object=po; data.use_fill_caps=True
    obj=bpy.data.objects.new(name,data); bpy.context.collection.objects.link(obj)
    active(obj); bpy.ops.object.convert(target='MESH')
    bpy.data.objects.remove(po,do_unlink=True)
    obj.data.materials.append(material); obj['category']='Outfit'; obj['part']='ScarfTail'
    recalc(obj)
    return obj


def hair_clump(spec,c,material,low=False):
    d=dimensions(spec); h=d['H']; hp=spec['proportions']['head']
    az,el=math.radians(c['root_az']),math.radians(c['root_el'])
    unit=Vector((math.sin(az)*math.cos(el),-math.cos(az)*math.cos(el),math.sin(el)))
    scale=Vector((hp['width']*.5*h,hp['depth']*.5*h,.5*h))
    # Roots overlap the cap by a small amount; cap and clumps share the same volume.
    root=Vector((unit.x*scale.x,unit.y*scale.y,unit.z*scale.z))*(spec['hair']['base_volume']-.015)
    root.z+=d['head_z']
    normal=Vector((unit.x/scale.x,unit.y/scale.y,unit.z/scale.z)).normalized()
    direction=Vector(c['dir']).normalized()
    length=c['length']*h; bend=Vector(c['bend'])*length
    p0=root; p1=root+direction*length*.5; p2=root+direction*length+bend
    cross=direction.cross(normal)
    if cross.length<.01:
        cross=direction.cross(Vector((0,1,0)))
    if cross.length<.01:
        cross=direction.cross(Vector((1,0,0)))
    cross.normalize()
    rings,sides=(5,6) if low else (9,8)
    verts=[]; colors=[]; faces=[]
    for j in range(rings):
        t=j/rings
        center=(1-t)**2*p0+2*(1-t)*t*p1+t*t*p2
        tangent=(2*(1-t)*(p1-p0)+2*t*(p2-p1)).normalized()
        flat=(cross-tangent*cross.dot(tangent)).normalized()
        wide=tangent.cross(flat).normalized()
        twist=math.radians(c['twist_deg'])*t
        a=wide*math.cos(twist)+flat*math.sin(twist)
        b=flat*math.cos(twist)-wide*math.sin(twist)
        radius=c['root_width']*h*.5*((1-t)**.75 if c['tip']=='sharp' else 1-.65*t)
        for i in range(sides):
            theta=2*math.pi*i/sides
            verts.append(tuple(center+radius*(a*math.cos(theta)+b*math.sin(theta)*(1-.86*c['flatten']))))
            base=np.array(linear_color(spec['hair']['color']))
            tip=np.array(linear_color(spec['hair']['tip_color']))
            high=np.array(linear_color(spec['hair']['highlight_color']))
            color=base*(1-t*.75)+tip*(t*.75)
            band=math.exp(-((t-.38)/.10)**2)*.65
            colors.append(tuple(color*(1-band)+high*band))
    faces.append(tuple(reversed(range(sides))))
    for j in range(rings-1):
        for i in range(sides):
            faces.append((j*sides+i,j*sides+(i+1)%sides,(j+1)*sides+(i+1)%sides,(j+1)*sides+i))
    if c['tip']=='sharp':
        verts.append(tuple(p2)); colors.append(linear_color(spec['hair']['tip_color']))
        end=len(verts)-1
        faces.extend(((rings-1)*sides+i,(rings-1)*sides+(i+1)%sides,end) for i in range(sides))
    else:
        faces.append(tuple((rings-1)*sides+i for i in range(sides)))
    obj=mesh('Hair_'+c['name'],verts,faces,material,'Hair',c['region'])
    attr=obj.data.color_attributes.new(name='HairColor',type='FLOAT_COLOR',domain='POINT')
    for item,color in zip(attr.data,colors):
        item.color=color
    recalc(obj)
    obj['chain_points']=json.dumps([tuple(p0),tuple(p1),tuple(p2)])
    return obj


def build_character(spec,low=False):
    clean_scene()
    d=dimensions(spec); h=d['H']; p=spec['proportions']; palette=spec['palette']
    skin=toon('Skin',palette['skin'],palette.get('skin_shadow'))
    hairmat=toon('Hair',spec['hair']['color'],hair=True)
    omat=toon('Outline',palette['outline'],outline=True)
    head=sphere('Head',(0,0,d['head_z']),(p['head']['width']*.5*h,p['head']['depth']*.5*h,.5*h),
                skin,segments=24 if low else 40,rings=16 if low else 24,
                deform=lambda x,y,z:head_deform(spec,x,y,z))
    group(head,'HeadSurface')
    if low:
        body=sphere('Body',(0,0,(d['hip_z']+d['neck_z'])/2),(.36*h,.22*h,(d['neck_z']-d['hip_z'])/2),skin)
        for side in [1,-1]:
            elbow=Vector(d['elbow']); elbow.x*=side
            wrist=Vector(d['wrist']); wrist.x*=side
            for name,start,end,radius in [
                ('Arm',(side*d['shoulder_x'],0,d['shoulder_z']),wrist,p['arms']['thickness']*h/2),
                ('Leg',(side*p['torso']['hip_width']*.28*h,0,d['hip_z']),
                 (side*p['torso']['hip_width']*.28*h,0,.13*h),p['legs']['thickness']*h/2)]:
                start,end=Vector(start),Vector(end)
                obj=sphere(name+str(side),(start+end)/2,(radius,radius,(end-start).length/2+radius),skin,segments=12,rings=8)
                # Sphere coordinates are baked; rotate around its center using a matrix.
                center=(start+end)/2; rot=(end-start).to_track_quat('Z','Y').to_matrix()
                for v in obj.data.vertices:
                    v.co=center+rot@(v.co-center)
    else:
        body=body_skeleton(spec,skin)
    for side,label in [(1,'L'),(-1,'R')]:
        wrist=Vector(d['wrist']); wrist.x*=side
        center=wrist+Vector((side*.10*h,-.015*h,-.08*h))
        sphere('Mitten_'+label,center,(p['arms']['hand_size']*.36*h,.07*h,p['arms']['hand_size']*.5*h),skin)
        sphere('Thumb_'+label,center+Vector((-side*.07*h,-.055*h,.035*h)),(.035*h,.045*h,.07*h),skin,segments=12,rings=8)
        sphere('Ear_'+label,(side*p['head']['width']*.49*h,0,d['head_z']-.04*h),
               (spec['face']['ears']['size']*.45*h,.06*h,spec['face']['ears']['size']*.7*h),skin,segments=16,rings=10)
    # Cap is a partial ellipsoid; leave forehead and eyes visible.
    n=32; rows=10; capverts=[]; capfaces=[]
    cutoff=spec['hair']['hairline_height']*2
    bottom=math.asin(max(-.99,min(.95,cutoff)))
    for j in range(rows):
        el=bottom+(math.pi/2-bottom)*j/rows
        for i in range(n):
            az=2*math.pi*i/n
            z=math.sin(el)
            # Lower cap at the back and sides, keeping a high front hairline.
            back=(1-math.cos(az))*.5
            adjusted=el-back*.52*(1-j/rows)
            capverts.append((math.sin(az)*math.cos(adjusted)*p['head']['width']*.5*h*spec['hair']['base_volume'],
                -math.cos(az)*math.cos(adjusted)*p['head']['depth']*.5*h*spec['hair']['base_volume'],
                d['head_z']+math.sin(adjusted)*.5*h*spec['hair']['base_volume']))
    capverts.append((0,0,d['head_z']+.5*h*spec['hair']['base_volume']))
    for j in range(rows-1):
        for i in range(n):
            capfaces.append((j*n+i,j*n+(i+1)%n,(j+1)*n+(i+1)%n,(j+1)*n+i))
    capfaces.extend(((rows-1)*n+i,(rows-1)*n+(i+1)%n,len(capverts)-1) for i in range(n))
    cap=mesh('Hair_Cap',capverts,capfaces,hairmat,'Hair','Cap')
    attr=cap.data.color_attributes.new(name='HairColor',type='FLOAT_COLOR',domain='POINT')
    for item in attr.data:
        item.color=linear_color(spec['hair']['color'])
    recalc(cap)
    for c in spec['hair']['clumps']:
        hair_clump(spec,c,hairmat,low)
    eyes=spec['face']['eyes']; brows=spec['face']['brows']; mouth=spec['face']['mouth']
    sclera=toon('Sclera',eyes['sclera_color']); iris=toon('Iris',eyes['iris_color'])
    dark=toon('FaceLines',eyes['line_color']); bright=toon('EyeHighlight','#FFFFFF')
    browmat=toon('Brows',brows['color']); mouthmat=toon('Mouth',mouth['color'])
    for side,label in [(1,'L'),(-1,'R')]:
        x=side*eyes['spacing']*.5*h; z=d['head_z']+eyes['height']*h
        rx=eyes['size']*.5*h; rz=rx*(1 if eyes['shape']=='round' else .75)
        disc('FaceEye_'+label,x,z,rx,rz,sclera,spec,head,side*eyes['tilt_deg'],eyes['shape'],.009)
        disc('FaceIris_'+label,x,z,rx*eyes['iris_ratio'],rz*eyes['iris_ratio'],iris,spec,head,offset=.014)
        disc('FacePupil_'+label,x,z,rx*eyes['iris_ratio']*eyes['pupil_ratio'],rz*eyes['iris_ratio']*.9,dark,spec,head,offset=.019)
        if eyes['highlight']:
            disc('FaceHighlight_'+label,x-rx*.27,z+rz*.32,rx*.19,rz*.18,bright,spec,head,offset=.024)
        pts=[]
        for i in range(17):
            t=math.pi*i/16
            xx=rx*math.cos(t); zz=rz*math.sin(t)
            angle=math.radians(side*eyes['tilt_deg'])
            pts.append((x+xx*math.cos(angle)-zz*math.sin(angle),z+xx*math.sin(angle)+zz*math.cos(angle)))
        strip('FaceLash_'+label,pts,.024*h,dark,spec,head,.03)
        bz=z+rz+brows['height_above_eye']*h
        pts=[(x+(i/8-.5)*brows['length']*h,bz+(i/8-.5)*side*math.sin(math.radians(brows['angle_deg']))*brows['length']*h) for i in range(9)]
        strip('FaceBrow_'+label,pts,brows['thickness']*h,browmat,spec,head,.03)
    nose=spec['face']['nose']
    if nose['style']=='dot':
        disc('FaceNose',0,d['head_z']-.21*h,nose['size']*h/2,nose['size']*h/2,mouthmat,spec,head)
    elif nose['style']=='line':
        strip('FaceNose',[(-.008*h,d['head_z']-.19*h),(.008*h,d['head_z']-.22*h)],nose['size']*.35*h,mouthmat,spec,head)
    mz=d['head_z']+mouth['height']*h
    disc('FaceMouth',0,mz,mouth['width']*.5*h,.009*h,mouthmat,spec,head,offset=.025)
    # The inner dark area always exists, opening from a thin neutral strip.
    disc('FaceMouthInner',0,mz,mouth['width']*.39*h,.003*h,dark,spec,head,offset=.03)
    for i,piece in enumerate(spec['outfit']['pieces']):
        typ=piece['type']; params=piece['params']; mat=toon(f'Outfit_{i}_{typ}',piece['color'])
        puff=params.get('puff',.03)
        if low and typ in ['jacket','shirt','tunic','shorts','pants','belt']:
            if typ in ['shorts','pants']:
                loc=(0,0,d['hip_z']-.12*h); scale=(.36*h,.23*h,.20*h if typ=='shorts' else .42*h)
            elif typ=='belt':
                loc=(0,0,d['hip_z']+.06*h); scale=(.38*h,.24*h,.04*h)
            else:
                loc=(0,0,(d['hip_z']+d['neck_z'])/2); scale=((.39+puff)*h,.25*h,.42*h)
            box(typ,loc,scale,mat,'Outfit',.02*h)
        elif typ in ['jacket','shirt','tunic']:
            low_z=d['neck_z']-params.get('length',p['torso']['length'])*h
            arm_x=d['shoulder_x'] + (p['arms']['length']*.75*h if params.get('sleeve')=='long' else .18*h)
            open_front=params.get('open_front',False)
            shell(body,typ,lambda co: low_z<co.z<d['neck_z']+.025*h and abs(co.x)<arm_x and
                not (open_front and co.y<-.06*h and abs(co.x)<.08*h),mat,h,.025+puff*.3)
        elif typ in ['shorts','pants']:
            bottom=.14*h if typ=='pants' else d['hip_z']-params.get('length',.35)*h
            shell(body,typ,lambda co:bottom<co.z<d['hip_z']+.1*h,mat,h,.03+puff*.3)
        elif typ=='belt':
            shell(body,typ,lambda co:abs(co.z-(d['hip_z']+.08*h))<max(.04,params.get('width',.06))*h,mat,h,.055)
            if params.get('pouch'):
                box('BeltPouch',(.3*h,-.22*h,d['hip_z']),(.09*h,.05*h,.11*h),mat,'Outfit',.02*h)
        elif typ=='boots':
            for side in [1,-1]:
                chunk=params.get('chunk',1); height=params.get('height',.42)*h
                x=side*p['torso']['hip_width']*.28*h
                box('Boot_'+str(side),(x,-.045*h,height*.5),(.115*h*chunk,p['legs']['foot_size']*.45*h,height*.5),mat,'Outfit',.035*h)
                if params.get('cuff_color'):
                    cuff=toon('BootCuff',params['cuff_color'])
                    box('BootCuff_'+str(side),(x,0,height),(.125*h*chunk,.145*h,.035*h),cuff,'Outfit',.015*h)
        elif typ=='gloves':
            for side in [1,-1]:
                wrist=Vector(d['wrist']); wrist.x*=side
                sphere('Glove_'+str(side),wrist+Vector((side*.04*h,0,-.035*h)),(.10*h,.082*h,.11*h),mat,'Outfit',segments=16,rings=10)
        elif typ=='scarf':
            thickness=params.get('thickness',.1)*h
            sphere('ScarfCollar',(0,0,d['neck_z']+.015*h),(.26*h,.24*h,thickness),mat,'Outfit',segments=24,rings=10)
            side=1 if params.get('tail_side','left')=='left' else -1 if params.get('tail_side')=='right' else 0
            length=params.get('tail_length',.9)*h
            pts=[(.12*side*h,.12*h,d['neck_z']),(.34*side*h,.25*h,d['neck_z']-.2*length),
                 (.55*side*h,.30*h,d['neck_z']-.75*length),(.60*side*h,.38*h,d['neck_z']-length)]
            tail=ribbon('ScarfTail',pts,.14*h,mat,h)
            tail['chain_points']=json.dumps([pts[0],pts[2],pts[3]])
        elif typ=='cape':
            ribbon('Cape',[(0,.23*h,d['neck_z']),(0,.4*h,d['hip_z']+.2*h),(0,.50*h,d['hip_z']-.3*h)],.70*h,mat,h)
    acc=spec['accessory']
    if acc['type']!='none':
        mat=toon('AccessoryMetal',acc['color']); params=acc['params']
        handle=toon('AccessoryHandle',params.get('handle_color',palette['dark']))
        attach=acc['attach']
        origin=Vector({'hip_back':(.22*h,.27*h,d['hip_z']), 'back':(0,.3*h,d['neck_z']-.3*h),
                       'hip_l':(.4*h,0,d['hip_z']), 'hip_r':(-.4*h,0,d['hip_z']),
                       'hand_r':(-d['wrist'][0],-.1*h,d['wrist'][2])}[attach])
        length=params.get('blade_length',.45)*h
        if low:
            box('Accessory',origin+Vector((0,0,-length/2)),(.045*h,.035*h,length/2),mat,'Accessory')
        elif acc['type']=='staff':
            obj=sphere('Staff',origin,(.028*h,.028*h,max(.8*h,length)),handle,'Accessory',segments=12,rings=12)
            sphere('StaffGem',origin+Vector((0,0,max(.8*h,length))),(.09*h,)*3,mat,'Accessory')
        else:
            width=(.055 if acc['type']=='dagger' else .085)*h
            curve=params.get('curve',0)*length
            points=[tuple(origin+Vector(co)) for co in [(-width,0,0),(width,0,0),
                (width+curve,0,-length*.8),(curve,0,-length),(-width+curve,0,-length*.8)]]
            obj=mesh('Blade',points,[(0,1,2,3,4)],mat,'Accessory',smooth=False)
            solid=obj.modifiers.new('Blade thickness','SOLIDIFY'); solid.thickness=.025*h; apply(obj,solid)
            box('WeaponHandle',origin+Vector((0,0,.08*h)),(.027*h,.035*h,.08*h),handle,'Accessory',.01*h)
            if params.get('guard','round')!='none':
                box('WeaponGuard',origin,(width*1.5,.04*h,.024*h),mat,'Accessory',.016*h)
    for obj in list(bpy.context.scene.objects):
        if obj.type=='MESH' and not obj.name.startswith('Face'):
            outline(obj,omat,.008*h)
    bpy.context.scene['character_spec']=json.dumps(spec)
    bpy.context.scene['H']=h
    return {'H':h,'objects':len([o for o in bpy.context.scene.objects if o.type=='MESH'])}


def engine(scene):
    values=[i.identifier for i in scene.render.bl_rna.properties['engine'].enum_items]
    for choice in ['BLENDER_EEVEE','BLENDER_EEVEE_NEXT']:
        if choice in values:
            scene.render.engine=choice
            return choice
    raise RuntimeError('EEVEE engine unavailable: '+str(values))


def setup_render(size=512):
    scene=bpy.context.scene
    engine(scene)
    scene.render.resolution_x=scene.render.resolution_y=size
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    scene.render.film_transparent=False
    scene.view_settings.view_transform='Standard'
    scene.world=bpy.data.worlds.new('Neutral Studio')
    scene.world.use_nodes=True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.28,.28,.28,1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value=.6
    for obj in list(scene.objects):
        if obj.type in ['CAMERA','LIGHT']:
            bpy.data.objects.remove(obj,do_unlink=True)
    for name,pos,power,size in [('Key',(-3,-4,5),350,4),('Rim',(3,2,4),450,3)]:
        data=bpy.data.lights.new(name,'AREA'); data.energy=power; data.shape='DISK'; data.size=size
        obj=bpy.data.objects.new(name,data); scene.collection.objects.link(obj); obj.location=pos
        obj.rotation_euler=(Vector((0,0,.8))-obj.location).to_track_quat('-Z','Y').to_euler()
    data=bpy.data.cameras.new('TurnaroundCamera'); data.type='ORTHO'
    camera=bpy.data.objects.new('TurnaroundCamera',data); scene.collection.objects.link(camera)
    scene.camera=camera
    return scene,camera


def mesh_bounds():
    points=[o.matrix_world@Vector(corner) for o in bpy.context.scene.objects if o.type=='MESH'
            and not o.hide_render for corner in o.bound_box]
    if not points:
        raise ValueError('No visible meshes')
    low=Vector([min(p[i] for p in points) for i in range(3)])
    high=Vector([max(p[i] for p in points) for i in range(3)])
    return low,high


def camera_view(camera,target,direction,scale):
    camera.location=Vector(target)+Vector(direction).normalized()*5
    camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.data.ortho_scale=scale


def render_png(path):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    bpy.context.scene.render.filepath=str(path)
    bpy.ops.render.render(write_still=True)
    image=bpy.data.images.load(str(path),check_existing=False)
    pixels=np.empty(len(image.pixels),dtype=np.float32)
    image.pixels.foreach_get(pixels)
    result=pixels.reshape(image.size[1],image.size[0],4).copy()
    bpy.data.images.remove(image)
    return result


def save_pixels(path,pixels):
    height,width,_=pixels.shape
    image=bpy.data.images.new(Path(path).stem,width=width,height=height,alpha=True)
    image.pixels.foreach_set(np.ascontiguousarray(pixels,dtype=np.float32).ravel())
    image.filepath_raw=str(path); image.file_format='PNG'; image.save()
    bpy.data.images.remove(image)


def tile_images(images,path,cols):
    height=max(i.shape[0] for i in images); width=max(i.shape[1] for i in images)
    rows=math.ceil(len(images)/cols)
    sheet=np.ones((rows*height,cols*width,4),dtype=np.float32)*.28
    sheet[:,:,3]=1
    for i,pixels in enumerate(images):
        # Blender pixels start at the bottom: first row of the sheet is the top row.
        row=rows-1-i//cols; col=i%cols
        sheet[row*height:row*height+pixels.shape[0],col*width:col*width+pixels.shape[1]]=pixels
    save_pixels(path,sheet)


def save_blend(path):
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=str(path))


def tris(obj,evaluated=False):
    data=obj.data
    if evaluated:
        deps=bpy.context.evaluated_depsgraph_get(); ev=obj.evaluated_get(deps)
        data=ev.to_mesh()
    data.calc_loop_triangles()
    count=len(data.loop_triangles)
    if evaluated:
        ev.to_mesh_clear()
    return count


def join_objects(objects,name):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active=objects[0]
    bpy.ops.object.join()
    obj=bpy.context.object; obj.name=name
    return obj
