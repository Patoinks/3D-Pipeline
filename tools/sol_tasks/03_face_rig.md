# Tarefa 3: `blender/face_rig.py`

Abre `<out>/production.blend`, grava `<out>/face.blend` (não reescrevas o production.blend).

1. Cria as 16 shape keys de `PRIMITIVES` (pipeline/spec.py) como deformações reais: pálpebras que
   fecham, sobrancelhas que sobem/rodam, boca que abre/sorri/franze. Se olhos/boca/sobrancelhas forem
   objetos separados, junta-os à malha da cabeça (ou dá-lhes as mesmas shape keys com o mesmo nome)
   para o FBX ficar com um só conjunto de blendshapes no Head.
2. Expressões = combinações de `spec['expressions']` (pesos por primitiva). Não cries shape keys por
   expressão; essas ficam como dados.
3. Renderiza `renders/expressions_sheet.png`: as 8 expressões de `EXPRESSIONS` por esta ordem,
   vista frontal enquadrada na cabeça, 4×2, com o nome de cada expressão escrito/legível
   (se não der para texto, grava também `renders/expressions_sheet.json` com a ordem).
4. Devolve no RESULT a lista de shape keys criadas.
