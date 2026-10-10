# Tarefa 4: `blender/export_fbx.py`

Abre `<out>/face.blend` e exporta `<out>/export/<id>.fbx` para Unity:
eixos -Z forward / Y up, `apply_scale_options='FBX_SCALE_ALL'`, `add_leaf_bones=False`,
`bake_anim=False`, shape keys incluídas, só malhas + armature (sem câmaras/luzes/outlines de render),
modificadores aplicados exceto Armature. Copia as texturas usadas para `<out>/export/textures/`.
Depois corre `blender/validate.py --phase export` na mesma pasta e confirma que passa.
No fim, corre o fluxo completo no `_sol_test`: build_base → production → face_rig → export_fbx → validate.
