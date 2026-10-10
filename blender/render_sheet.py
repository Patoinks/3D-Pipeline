import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from chibi_lib import *

def main():
    args,spec=arguments(lambda p:p.add_argument('--contact',nargs='+',type=Path))
    render_dir=args.out/'renders'; render_dir.mkdir(exist_ok=True)
    if args.contact:
        sheets=[]
        for path in args.contact:
            img=bpy.data.images.load(str(path.resolve()),check_existing=False)
            pixels=np.empty(len(img.pixels),dtype=np.float32); img.pixels.foreach_get(pixels)
            sheets.append(pixels.reshape(img.size[1],img.size[0],4).copy())
            bpy.data.images.remove(img)
        output=render_dir/'contact_sheet.png'
        tile_images(sheets,output,cols=1)
        (render_dir/'contact_sheet.json').write_text(json.dumps({'rows':[
            {'row':i,'label':p.parent.parent.name,'sheet':str(p.resolve())} for i,p in enumerate(args.contact)]},indent=2))
        return {'contact':str(output),'count':len(sheets)}
    bpy.ops.wm.open_mainfile(filepath=str((args.blend or args.out/'base.blend').resolve()))
    scene,camera=setup_render()
    low,high=mesh_bounds(); center=(low+high)/2
    # A-pose can be wider than it is tall; use a common scale across all views.
    scale=max(high.z-low.z,high.x-low.x,high.y-low.y)*1.22
    views=[('front',(0,-1,0)),('left',(1,0,0)),('three_quarter',(1,-1,0)),('back',(0,1,0))]
    pixels=[]
    for name,direction in views:
        camera_view(camera,center,direction,scale)
        pixels.append(render_png(render_dir/(name+'.png')))
    black=toon('Silhouette','#000000',outline=True); black.use_backface_culling=False
    scene.view_layers[0].material_override=black
    camera_view(camera,center,(0,-1,0),scale)
    pixels.append(render_png(render_dir/'silhouette.png'))
    scene.view_layers[0].material_override=None
    output=render_dir/'turnaround.png'; tile_images(pixels,output,5)
    (render_dir/'turnaround.json').write_text(json.dumps({'views':[v[0] for v in views]+['silhouette'],
        'size_per_view':512,'ortho_scale':scale,'target':list(center)},indent=2))
    return {'sheet':str(output),'engine':scene.render.engine}

if __name__=='__main__':
    entry(main)
