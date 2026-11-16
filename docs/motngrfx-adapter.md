# MOTNGRFX portátil: tipografia volumétrica e composição

O adaptador `editorial_engine.motngrfx` executa em CPU duas operações explícitas:
`rotate` e `hinge_unfold`. Ele exporta uma sequência PNG RGBA, com alpha straight,
relógio racional e manifesto de hashes. Pode também compor a sequência sobre um
vídeo CFR preservando todos os frames e a posição dos cortes, com uma máscara
externa para colocar o texto atrás do sujeito.

Não existe escolha aleatória de módulos nem interpretação de texto por palavras
chave. A direção escolhe o módulo, as curvas, a posição e a ordem das camadas.
O adaptador executa essa escolha e rejeita requisitos impossíveis.

## Código reutilizado e licença

Origem: [okkazoo/MOTNGRFX](https://github.com/okkazoo/MOTNGRFX), commit fixo
[`8c0ddc816616a95f55bddc606eecea3fd5ba5ef1`](https://github.com/okkazoo/MOTNGRFX/commit/8c0ddc816616a95f55bddc606eecea3fd5ba5ef1), Apache-2.0,
copyright 2026 okkazoo. `vendor/motngrfx/LICENSE` e `NOTICE` preservam os avisos.
`UPSTREAM.json` identifica os arquivos, hashes dos snapshots e alterações.

| Origem | Reuso executado |
| --- | --- |
| `tools/mathtype/kit/camera.py` | Curvas por função, matriz de rotação e projeção em perspectiva, especializadas para NumPy. |
| `mograph/modules/words/hinge_unfold.py` e `_depth.py` | Mecânica de cinco fases por letra: inclinar, subir, voltar à posição vertical, descer e avançar em profundidade. |
| `tools/app/overlay_mode.py` | Medição de visibilidade por palavra/glifo através de matte; sem quota, troca de camada ou descarte. |

Os snapshots em `vendor/motngrfx/upstream/` servem à auditoria e não são importados.
`vendor/motngrfx/portable.py` contém as adaptações efetivamente utilizadas.
O rasterizador de malha, contratos de arquivo e validação são implementação do
Editor Ultra. Não foram incorporados modelos, fontes, vídeos, assets privados,
ComfyUI nem o pipeline completo do projeto original.

## O que é o volume renderizado

Cada glifo completo vem da fonte indicada e mantém seus avanços e kerning latino.
O renderizador extruda seus contornos rasterizados, cria faces frontal/traseira,
paredes laterais e cavidades, aplica rotação em três eixos, perspectiva, luz
Lambert e um depth buffer. Isso produz geometria volumétrica em uma câmera
sintética. Os contornos seguem a resolução da rasterização da fonte, portanto
não substituem uma malha vetorial de alta resolução nem bevel/reflexos físicos.

O módulo `hinge_unfold` articula cada glifo sobre sua linha de base e executa as
curvas de volume adaptadas do módulo original. Não inclui seus strands, paletas
fixas ou transições entre palavras. A câmera sintética não é um solve da câmera
da filmagem. Colocar a geometria atrás de uma máscara é uma composição por matte;
aderência a chão, pessoa ou objeto ainda exige recursos medidos do motor espacial.

## Dependências

Python 3.10+, NumPy, Pillow, OpenCV e FontTools; FFmpeg/FFprobe para composição
e prova de vídeo. Não requer torch, CUDA, Blender nem pesos generativos para as
operações portáteis. `probe_motngrfx()` retorna a disponibilidade instalada sem
executar modelos ou apresentar readiness como prova de render.

A fonte deve ser fornecida por caminho. `font_license` registra a declaração do
responsável; o adaptador confere o arquivo/hash e cobertura Unicode, mas não
verifica juridicamente a declaração. Fontes e licenças do projeto devem permanecer
juntas no pacote de mídia. Não há fonte substituta automática. A implementação
por glifo aceita uma linha NFC de até 64 caracteres sem scripts conectados; para
lettering complexo, use o caminho de camada completa do motor.

## Receita executável

Salve esta receita em `type-motion.json`, indique uma fonte realmente disponível
e escolha uma pasta nova para o export:

```json
{
  "schema": "motngrfx-motion/1",
  "text": "AÇÃO",
  "fps": "24/1",
  "frame_count": 48,
  "width": 640,
  "height": 360,
  "font_size": 100,
  "extrusion_px": 22,
  "center": [0.5, 0.5],
  "color": [246, 227, 181],
  "side_color": [104, 53, 27],
  "supersampling": 2,
  "animation": {
    "module": "rotate",
    "easing": "smooth",
    "keyframes": [
      {"frame": 0, "rotation_deg": [-28, 10, -4], "scale": 1.0, "offset_px": [0, 0, 0]},
      {"frame": 47, "rotation_deg": [28, 10, 4], "scale": 1.0, "offset_px": [0, 0, 0]}
    ]
  },
  "read_window": {"start_frame": 0, "end_frame": 48},
  "min_face_cosine": 0.1
}
```

```bash
python -m editorial_engine motion probe
python -m editorial_engine motion render motngrfx type-motion.json /projeto/exports/type-v001 --font /projeto/fontes/Fonte-Regular.ttf --font-license "Licença verificada no pacote de mídia" --asset-id type-acao-v001 --description "Título com extrusão e rotação para ênfase contextual"
```

O wrapper da CLI guarda o manifesto original em `producer/manifest.json` e cria
`motion-layer.json`, `inventory.json` e uma folha de amostras para importação no
fluxo contextual. O inventário não decide onde usar a sequência: essa escolha
continua na proposta editorial ligada à evidência do novo bruto.

Para a articulação por letra, use `animation.module: "hinge_unfold"`,
`animation.hinge_frames: 28` e `animation.stagger_frames: 1`. A janela de leitura
padrão começa após `hinge_frames`; pode ser indicada explicitamente. Rotações são
`[yaw, pitch, roll]` em graus. `offset_px` usa o espaço 3D sintético em pixels,
com Y positivo para cima e Z positivo em direção à câmera. Não é uma trajetória
de tracking da filmagem.

## API Python

```python
from editorial_engine.motngrfx import render_sequence, render_on_video

manifest = render_sequence(
    spec,
    "/projeto/exports/sequence-v001",
    font_path="/projeto/fontes/Fonte-Regular.ttf",
    font_license="SIL OFL 1.1; licença preservada no pacote",
)
report = render_on_video(
    "/projeto/originais/bruto.mkv",
    "/projeto/exports/prova-v001.mkv",
    manifest,
    mode="behind",
    matte="/projeto/mattes/manifest.json",
    cut_frames=[48, 96],
    min_visible=0.70,
    min_occluded=0.01,
    min_glyph_visible=0.50,
)
```

O source da composição completa precisa ter exatamente largura, altura, FPS e
contagem de frames da sequência. Não há retime, crop, reordenação ou repetição de
frames. Seu PTS inicial deve ser zero; um offset exige normalização acompanhada
de um mapeamento de relógio explícito. Para um trecho dentro de um bruto maior, importe a sequência como recurso
`native.motion_layer` ou `native.motion_behind` pelo fluxo contextual, com intervalo
e vínculo de fonte explícitos; não altere os índices para simular correspondência.

`composite_frame(source_rgb, layer_rgba, mode=..., matte=..., min_visible=...,
min_occluded=..., glyph_ids=..., min_glyph_visible=...)` é a primitiva reutilizável.
Recebe rasters uint8, compõe em luz linear e conserva exatamente os pixels fonte
onde o alpha efetivo é zero. Ela retorna o RGB e medições; nunca troca `behind`
por `front`. O alpha original da sequência permanece intacto.

## Manifesto da sequência e matte

`render_sequence` salva `manifest.json` com `schema: "motion-sequence/1"`,
`fps` racional, `frame_count`, `width`, `height`, `alpha: "straight"`,
`color_space: "sRGB"`, receita normalizada, fonte/hash, fingerprints e estado de
revisão. Cada entrada de `frames` contém `index`, `path`, `sha256`,
`glyph_ids_path` e `glyph_ids_sha256`. Os PNGs de IDs permitem conferir a cobertura
de cada glifo, sem inferir letras de um render já ocluído.

A composição direta aceita um manifesto de matte com esta estrutura:

```json
{
  "source_sha256": "SHA256_DOS_BYTES_DO_VIDEO_FONTE",
  "clock": "source",
  "fps": "24/1",
  "frame_count": 48,
  "width": 640,
  "height": 360,
  "frames": [
    {"index": 0, "path": "/projeto/mattes/000000.png", "sha256": "SHA256_DO_PNG"}
  ]
}
```

O exemplo abrevia a lista: a execução exige **todos** os frames, contíguos e na
ordem. Os PNGs devem ser grayscale `L`, com a mesma dimensão da fonte: 255 significa
sujeito opaco. O backend valida hash e relógio; a qualidade da segmentação precisa
de revisão visual. Fonte e recursos existentes nunca são sobrescritos.

Com a CLI, a composição direta usa o manifesto **original** do produtor:

```bash
python -m editorial_engine motion composite-type /projeto/originais/bruto.mkv /projeto/exports/type-v001/producer/manifest.json /projeto/exports/prova-v001.mkv --mode behind --matte /projeto/mattes/manifest.json --cuts 48 96 --min-visible 0.70 --min-occluded 0.01 --min-glyph-visible 0.50
```

## Validação e falhas

- ID/hash de fonte ou matte incompatível, lacuna de frames, relógio divergente,
  VFR, glifo ausente e campo desconhecido bloqueiam a execução.
- Geometry fora do quadro, plano próximo da câmera, face de glifo virada demais
  durante leitura ou letra inteiramente escondida bloqueiam o export.
- `min_visible` mede alpha visível da palavra; `min_glyph_visible`, de cada glifo
  e exige o passe de IDs original quando maior que zero;
  `min_occluded` exige interação real com a máscara no frame. Essa última condição
  é opcional, porque uma passagem atrás pode começar antes da sobreposição.
- Perda de cobertura não puxa texto para frente, não reduz o efeito e não elimina
  frames. O erro identifica a condição para uma revisão editorial explícita.
- `verify_render` decodifica **todos** os frames e compara a composição exigida.
  Assim verifica preservação, ordem e matte no arquivo codificado, incluindo os
  frames de corte informados. Não detecta automaticamente quais cortes são
  semanticamente corretos.
- A prova usa FFV1 em MKV ou H.264 RGB lossless em MP4. O primeiro prioriza
  inspeção; o segundo usa perfil RGB que pode exigir um transcode separado para
  distribuição. Não confunda essa prova com o master de entrega.

O relatório `.review.json` fica vinculado aos bytes do render, fonte, manifesto e
implementação. `technical_status: "passed"` não representa aprovação estética:
movimento perceptivo, áudio ouvido e aprovação do usuário continuam `unverified`
ou `false`. Cobertura de alpha e orientação do glifo não medem compreensão humana,
contraste em toda condição, identidade de marca ou fidelidade a uma referência.

## Pipeline generativo completo opcional

`preflight_comfyui(endpoint, required_nodes=[...], model_files=[{path, sha256}])`
consulta apenas o endpoint explícito `/object_info` e os arquivos locais indicados.
Não baixa modelos, não instala ComfyUI e não submete workflows. Verificar nodes e
bytes locais não demonstra que um servidor remoto acessa os pesos; por isso
`executable_capability` e `ready` permanecem falsos. Não foi executada inferência
do pipeline completo MOTNGRFX nesta integração. Licenças dos modelos continuam
independentes da licença Apache do código.

## Prova automatizada

```bash
python -m pytest tests/test_motngrfx_integration.py -q
```

A prova renderiza letras com volume/rotação e articulação, codifica uma filmagem
sintética com corte e matte, confere oclusão e todos os pixels/frames, e injeta
troca de frames, hashes e relógios inválidos. Usa somente uma fonte instalada no
sistema; não leva fontes nem vídeos privados ao repositório.
