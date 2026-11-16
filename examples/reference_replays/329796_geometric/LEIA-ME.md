# Referência 329796 — moto e máscaras geométricas

Reconstrução de 14,233333 s, 427 quadros a 30 fps. Raster de trabalho 1280×720, obtido girando 90°anti-horário o arquivo 720×1280 fornecido. Não há tipografia nesta referência.

## O que este pacote reconstrói

O render é uma **recomposição de camadas fotográficas recuperadas do MP4 final**. Preserva os pixels observáveis da filmagem; não recria a fotografia por geração, não recupera as tomadas originais completas e não é uma reconstrução independente de cada câmera. As máscaras geométricas, os tempos, a composição e a oclusão são executados novamente por código. `render.py` não abre o MP4 de referência.

As regiões não observáveis são preenchidas com uma chapa fotográfica limpa ou extensão da textura visível. Esses preenchimentos são aproximações e não devem aparecer ao alterar a geometria sem revisar os assets. A comparação com o original mede esta recomposição, não prova generalização. `Prova-Reaplicacao.mp4` troca os vínculos por sete fotografias limpas e conserva a geometria/timeline; comprova a execução independente das máscaras, mas não substitui um teste futuro com novos brutos e novos recortes de pessoa.

## Arquivos e encaixe

| Arquivo | Papel |
|---|---|
| `timeline.json` | 21 cenas, 427 vínculos, formas normalizadas, parâmetros e ordem de camadas |
| `engine/visual_fidelity/geometric_replay.py` | Componente reutilizável 1.0.1: máscaras, keyframes, relógio, alpha e composição |
| `assets/base.mp4` | Camada fotográfica de base recuperada; regiões ocultas aproximadas |
| `assets/insert.mp4` | Fotografias das inserções; suporte fora da máscara é inferido |
| `assets/foreground.mp4` | RGB do recorte que passa à frente; fora do suporte é preto |
| `assets/subject_masks/0000.png` etc. | Alpha da pessoa/moto; 199 máscaras, usar apenas as referidas pela timeline |
| `assets/cyan_masks/` | Alpha do flash ciano, separado da fotografia |
| `assets/confidence/` | 0 não observado/preenchido; 85 base observada; 170 insert observado; 255 pessoa observada |
| `assets/plates/` | Fotografias limpas curtas e mosaico de floresta, com proveniência |
| `audio/reference.wav` | Mix extraído, limitado a 683.200 amostras no render, sem mudar velocidade |
| `analysis/` | Decupagem, medições, relatórios e limitações |
| `media/reference.mp4` | Original preservado para auditoria/reextração; não usado pelo render final |

## Ordem de camadas por cena

Intervalos `[início,fim)`, em quadros a 30 fps.

| Quadros | Composição |
|---|---|
|0–97 | Base → banda horizontal crescente → pessoa/moto recortada |
|97–106 | Fotografia → preenchimento ciano com alpha do corpo |
|106–111 | Tomada limpa |
|111–154 | Base → união de duas faixas diagonais em X; passa SOBRE a pessoa |
|154–168 | Fundo com troca rápida → pessoa recortada |
|168–216 | Costa → foto superior com transição suave → pessoa pequena à frente |
|216–221 | Tomada industrial limpa |
|221–226 | Industrial → segundo piloto recortado |
|226–268 | Base → duas faixas horizontais em sentidos opostos |
|268–285 | Microplanos limpos, cadência original preservada |
|285–336 | Base → duas faixas giratórias; opacidade de entrada ajustada manualmente |
|336–350 | Base → inserção limitada ao contorno móvel da viseira |
|350–394 | Floresta → duas faixas verticais em sentidos opostos |
|394–427 | Base → banda horizontal → pessoa recortada |

## Reproduzir

Python 3.12; dependências `numpy`, `opencv-python`, `scipy`, `Pillow`; FFmpeg com libx264 no PATH. Versões usadas em `requirements-lock.txt`.

```bash
python code/render.py
python code/render.py --proof
python -m unittest discover -s tests -p 'test_geometric_replay.py'
```

Os comandos são executados a partir da raiz do pacote. Os dois renders usam o mesmo módulo do motor e a mesma timeline. O código usa alpha premultiplicado na composição; os arquivos RGB são straight. Cor Rec.709 codificada, sem nova gradação aplicada ao master.

Para reextrair os materiais, conservar os caminhos, executar o script de placas, `code/extract_foreground.py --video media/reference.mp4`, `code/build_manifest.py` e `code/prepare_layers.py`. As medições normalizadas já estão incluídas; não é necessário repetir o ajuste geométrico.

## Aplicar posteriormente a outro vídeo

1. Preparar novos planos limpos de base e inserção. Fixar seus relógios e reenquadramentos, sem repetir material silenciosamente.
2. Reutilizar os tipos de máscara e trajetórias da timeline. Manter separados o desenho da máscara, a imagem que passa por ela e o tempo de troca da imagem.
3. Nos trechos com pessoa à frente, gerar alpha do NOVO sujeito. As máscaras do motociclista desta referência não servem para uma pessoa diferente.
4. Reposicionar a máscara da viseira para o novo objeto; suas coordenadas atuais pertencem ao capacete desta filmagem.
5. Ajustar o intervalo e velocidade dos keyframes, renderizar e comparar em movimento. Não usar a foto final como fundo e acrescentar novamente o mesmo efeito.

API mínima:

```python
from visual_fidelity.geometric_replay import mask, compose
coverage = mask({"kind":"strip","center":[0.5,0.5],"angle":32,"width":0.14},1280,720)
frame = compose(base_rgb, insert_rgb, coverage, foreground=subject_rgba)
```

A entrada pode ser qualquer fotografia ou quadro de vídeo do mesmo raster; nenhuma imagem da moto está hardcoded no motor. A prova de reaplicação usa esta mesma composição com fontes substituídas.

## Limitações registradas

- Bordas preto sobre preto, antenas e vãos da moto podem exigir retoque fino. Partes já ocultas no MP4 não foram inventadas como recuperadas.
- O flash ciano e a zona suave da colagem são aproximações fotométricas; máscaras duras têm ajuste subpixel/por quadro documentado.
- A viseira é um polígono denso interpolado, não um modelo 3D nem um solve de câmera.
- A fonte musical é o mix da referência fornecida para este teste; nenhuma licença de publicação foi inferida.
- O status visual permanece pendente até avaliação do usuário. Testes de código e métricas não equivalem a aprovação estética.

## Correção incorporada ao motor

A revisão detectou uma emenda vertical clara na paisagem durante a colagem
(quadros 180 e 195). A causa era o recorte de valores de cor fora da faixa
na solução inversa do alpha. O motor 1.0.1 inclui `decompose_observed`, usado
pelo extrator deste projeto e coberto por teste de recomposição. Os valores
de base ocultos são ajustados para permitir a inserção sem saturação artificial.
Isso conserva a aparência observada, mas não torna a solução fotográfica única.
