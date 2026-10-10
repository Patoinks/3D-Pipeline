# Tarefa 1: `blender/production.py`

Extra arg: `--settings <production_settings.json>`. Abre `<out>/base.blend`, grava `<out>/production.blend`.

1. Merge by distance (`merge_distance`) e normais recalculadas por objeto.
2. Orçamento: alvo = min(settings.target_tris, spec.game_constraints.tri_budget). Decimate por
   categoria com `decimate_ratios`; se ainda passar o alvo, reduz Hair/Accessory primeiro,
   nunca Skin_Face abaixo de 0.85. O rosto (olhos/boca/sobrancelhas) nunca é decimado.
3. Consolida materiais: no máximo `materials_max` (Hyota = 4), um por categoria
   (`M_Skin_Face`, `M_Hair`, `M_Outfit`, `M_Accessory`). As cores originais passam para uma textura
   baked (paleta/atlas) em `textures/<id>_<categoria>.png`; tamanho = `texture_size` da spec quando
   `bake_size == "spec"`. Material toon (sombra de 1 degrau, rim = `rim_strength`, brilho estilizado no cabelo).
   O outline invertido (`outline_width_h` × altura) não pode ser um 5.º material no FBX: usa um
   modificador Solidify que reutiliza o slot do próprio material com backface culling
   (o shader toon do Unity faz o outline), e não o apliques.
4. UVs: ilha do rosto com densidade de texel × `face_texel_priority`, cabelo separado, margem `uv_margin`.
5. Rig: armature com nomes compatíveis com Unity Humanoid (Hips, Spine, Chest, Neck, Head, LeftShoulder,
   LeftUpperArm, LeftLowerArm, LeftHand, ... pernas, LeftFoot, LeftToes, idem Right), número de ossos
   ≤ `max_bones`, posicionados a partir de `dimensions(spec)`. Pesos automáticos no corpo/roupa;
   cabelo, olhos, boca e sobrancelhas 100% no osso Head.
6. Grava `reports/production.json` (tris por categoria, materiais, ossos, ficheiros de textura).
