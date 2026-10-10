# Contexto comum (lê antes de cada tarefa)

Repositório: AnimeChibiPipeline. Orquestrador stdlib em `pipeline/`, Blender em `blender/`.
Faltam 4 scripts que o `pipeline/cli.py` já chama. NÃO alteres `pipeline/`, `schema/`,
`roles/` nem `examples/`; só crias/editas ficheiros em `blender/` (e `.gitignore`).

## Regras de código
- Cada script segue o padrão de `blender/build_base.py`: `sys.path.insert` + `from chibi_lib import *`,
  `args,spec = arguments(extra)` e `entry(main)`; `main()` devolve um dict curto (vai para a linha `RESULT:`).
- Helpers novos e reutilizáveis vão para `blender/chibi_lib.py`; não dupliques o que já lá está
  (`toon`, `outline`, `tris`, `join_objects`, `setup_render`, `camera_view`, `render_png`, `tile_images`...).
- Determinístico: sem aleatoriedade não-semeada, sem dependências fora do Blender (bpy, bmesh, numpy).
- Falhas = exceção com mensagem clara (o `entry` dá exit 1).
- Cada objeto de malha tem `obj['category']` ∈ {Skin_Face, Hair, Outfit, Accessory} e `obj['part']`.
- Lê `spec['game_constraints']` (tri_budget, max_bones, texture_size, materials_max) e, na produção,
  o `production_settings.json` passado em `--settings`.

## Como o pipeline chama (de `pipeline/cli.py`)
`blender -b --factory-startup --python-exit-code 1 --python blender/<script> -- --spec <spec.json> --out <pasta do projeto> [extra]`
A pasta do projeto contém `base.blend` (saída do `build_base.py`), `reports/`, `renders/`, `textures/`, `export/`.

## Teste obrigatório antes de terminares
Usa uma pasta `_sol_test/` na raiz (já ignorada no git). Gera a base com:
`blender -b --factory-startup --python blender/build_base.py -- --spec examples/hyota.spec.json --out _sol_test`
Depois corre o teu script na mesma pasta e confirma que a linha `RESULT:` tem `"ok": true`.
Se não conseguires correr o Blender no sandbox, diz isso claramente no relatório final; não finjas resultados.

## Relatório final (a tua última mensagem)
Escreve-o só em JSON: {"task": "...", "files_changed": [...], "tested": true|false,
"test_output": "<linhas RESULT relevantes>", "known_issues": [...]}
