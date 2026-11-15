# Reconstrução de ambiente

O módulo recebe vistas de um plano, estima geometria com MoGe-2 ou VGGT e produz uma cena editável Blender/Cycles. O formato comum preserva pixels, coordenadas e câmeras. A reconstrução do vídeo completo continua organizada por planos, cada um com sua origem e escala.

## Instalação

Use Python 3.10–3.12, Git e Blender no PATH. O ambiente de modelos tem suas dependências próprias, em função dos requisitos dos projetos originais.

```bash
python visual_fidelity/install_scene_models.py .venv-scene3d --backend cpu
.venv-scene3d/bin/python -m visual_fidelity scene3d doctor
```

Para a distribuição CUDA 12.4 do PyTorch, selecione `--backend cu124`. No Windows, o executável está em `.venv-scene3d/Scripts/python.exe`. O instalador fixa revisões de MoGe-2, VGGT e utilitários, verifica os imports e registra o ambiente. Os pesos são baixados na primeira inferência. VGGT-1B é substancialmente mais pesado. Escolha a máquina conforme memória e número de vistas.

## Uma imagem com MoGe

```bash
python -m visual_fidelity scene3d prepare quadro.png trabalho/vistas
python -m visual_fidelity scene3d infer trabalho/vistas/views.json trabalho/geometria --model moge --python .venv-scene3d/bin/python --resolution-level 0
python -m visual_fidelity scene3d render trabalho/geometria/geometry.npz trabalho/cena.blend --render trabalho/quadro.png
```

MoGe-2 usa por padrão o checkpoint `Ruicheng/moge-2-vits-normal`. O resultado contém estimativas de profundidade métrica e intrínsecos. `--resolution-level` varia de 0 a 9. `--num-tokens` permite escolher o custo de inferência explicitamente. Os controles pertencem ao MoGe. Cada execução recebe uma imagem. Um resultado monocular representa sobretudo superfícies observadas daquela vista.

## Várias vistas com VGGT

```bash
python -m visual_fidelity scene3d prepare video.mp4 trabalho/plano-01 --start 120 --end 216 --step 12
python -m visual_fidelity scene3d infer trabalho/plano-01/views.json trabalho/geometria-01 --model vggt --device cuda --python .venv-scene3d/bin/python
python -m visual_fidelity scene3d render trabalho/geometria-01/geometry.npz trabalho/plano-01.blend --view 0 --animate-cameras --render trabalho/plano-01.png
```

Os quadros começam em zero e o fim é exclusivo. Escolha uma tomada contínua. As vistas do VGGT compartilham coordenadas mundiais com escala relativa. O adaptador mantém a imagem processada pelo modelo junto de sua matriz de câmera e exclui as bordas de padding da malha. Esse raster pode ter proporção diferente do vídeo original. O campo `content_boxes` informa sua região útil. Reenquadre os passes junto com a câmera ao voltar à montagem.

`--animate-cameras` cria chaves nas amostras de vídeo, com quadro 1 do Blender correspondente à primeira amostra. A interpolação linear entre amostras é uma aproximação. O manifesto registra índice de quadro, FPS nominal e timestamp informado pelo decodificador. Para VFR, conforme o vídeo para CFR preservando o tempo antes de resolver a câmera por quadro.

O Blender recebe por padrão a malha de uma vista. `--all-views` importa as malhas das demais vistas. Superfícies sobrepostas exigem revisão e eventual fusão. O comando não executa fusão multivista. `--stride` controla a amostragem da malha. `--max-edge-ratio` descarta triângulos longos em relação à profundidade. `--min-confidence` filtra a confiança na escala nativa do modelo, documentada no JSON.

## Texto, luz e materiais

```bash
python -m visual_fidelity scene3d render trabalho/geometria/geometry.npz trabalho/cena-pbr.blend --material pbr --objects examples/scene3d-objects.json --samples 64 --render trabalho/pbr.png
```

O arquivo de objetos define texto extrudado e caixas com bevel, posição, rotação e material. As posições seguem as unidades do modelo. Ajuste os valores do exemplo à superfície observada. As rotações são XYZ em graus. O texto aceita `font` com caminho relativo ao JSON para carregar o TTF/OTF. Tipografia, âncoras corporais e máscaras podem ser preparados pelos demais módulos do editor.

No modo `projected`, a cor original fica projetada na superfície para conferir a geometria e a câmera. Essa cor contém a luz já registrada na imagem. No modo `pbr`, há material Principled com rugosidade e luzes de área iniciais. Revise a iluminação e o material antes de comparar acabamento. A reconstrução desses parâmetros por renderização inversa ainda requer uma etapa de ajuste.

A inferência aceita `--mask imagem.png` para excluir pixels de uma única vista já no raster processado. Branco mantém a geometria e preto remove. Máscaras corporais e regiões com texto animado podem ser usadas para remover interferências. Essa exclusão deixa regiões sem geometria quando nenhum outro quadro revela o fundo.

## Artefatos e verificação

`views.json` registra as fontes e quadros. `geometry.npz` contém `points`, `images`, `intrinsics`, `extrinsics`, `valid` e `confidence`. `geometry.json` registra o modelo e as convenções. O `.blend` leva as texturas empacotadas e seu relatório `.report.json` informa quantidades, câmera e limites do render. A saída de inferência é publicada apenas depois de o pacote estar completo.

Os pontos usam convenção OpenCV. As extrínsecas transformam mundo para câmera. Os intrínsecos estão em pixels do raster processado com centros inteiros. O importador transforma eixos e câmera para Blender, respeitando distância focal e principal point. Valide com marcadores e reprojeção antes de avaliar os materiais. Para o teste final do vídeo completo, use `timeline-qa` e revise cada passagem lado a lado.

## Verificação desta integração

A instalação CPU com PyTorch 2.6.0, MoGe-2 e VGGT concluiu, incluindo imports oficiais. Um teste real de MoGe em imagem 180 × 320 produziu 57.600 pontos válidos. A saída atravessou os comandos de inferência e renderização, gerando `.blend` e PNG em Cycles. O teste geométrico de câmera verificou distância focal assimétrica, centro deslocado e rotação. Uma fixture testou exclusão de NaN, máscara, faces atravessando um salto de profundidade e keyframes de câmera.

Os 47 testes Python e três testes de regressão no Blender 4.3.2 passaram. Também houve renders reais com material projetado e PBR, texto extrudado e uma caixa. O helper oficial de pré-processamento do VGGT foi exercitado em retrato e paisagem. A inferência completa de VGGT-1B permanece pendente de validação em máquina com memória suficiente, preferencialmente CUDA. Estes testes verificam instalação, coordenadas e fluxo. A fidelidade de uma nova referência precisa ser avaliada no render dessa referência.

```bash
python -m pytest tests -q
blender --background --factory-startup --python-exit-code 1 --python tests/blender_scene_smoke.py
```

`--checkpoint` aceita um `.pt` ou identificador Hugging Face no MoGe. No VGGT, use o identificador Hugging Face ou um diretório local compatível com o Hub.
