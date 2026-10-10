# Tarefa 2: `blender/validate.py`

Extra arg: `--phase production|export`. Escreve SEMPRE `<out>/reports/validation.json` antes de sair:
`{"phase":..., "ok": bool, "checks":[{"name","ok","value","limit","detail"}]}` e depois lança exceção se `ok` for false.

- production: abre `<out>/production.blend`. export: cena limpa + importa `<out>/export/<id>.fbx`.
- Verificações: total de tris ≤ tri_budget; nº de materiais ≤ materials_max; nº de ossos ≤ max_bones;
  ossos Humanoid obrigatórios presentes; todas as malhas com UV e com todos os vértices com peso;
  cabelo/rosto ligados ao Head; nenhuma malha com escala não aplicada; texturas referenciadas existem.
- Só na fase export: as 16 shape keys de `PRIMITIVES` (pipeline/spec.py) existem na malha da cabeça.
- O `detail` deve servir a quem corrige (a Astra lê este ficheiro): diz QUE objeto e QUANTO falta/sobra.
