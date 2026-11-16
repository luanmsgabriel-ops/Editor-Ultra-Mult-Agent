# Integração de OpenKatana, Motion Lab MIT e MOTNGRFX

O Editor Ultra mantém um diretor contextual e acrescenta três executores locais.
O diretor decide função, conteúdo, posição, duração e intensidade a partir do
bruto e da referência. Os executores produzem a montagem ou camadas animadas
editáveis; o compositor aplica as camadas ao bruto sob o mesmo relógio, e o QC
confere os bytes exportados. Não há seleção por nomes de arquivo ou aplicação
aleatória de efeitos.

## Escopo implementado

| Componente | Execução incorporada | Fronteira explícita |
| --- | --- | --- |
| OpenKatana | Medição de referência e áudio; timeline, efeitos e prévias pelo engine Canvas original em Node; pontes explícitas Chromium/WebGL e Blender | Medições são estimativas. Retiming exige mapa. WebGL precisa de um navegador funcional; disponibilidade não é presumida. |
| Motion Lab legado MIT | Grafo 2D, tracks absolutos e grupos independentes, amostragem temporal, geometria/câmera 3D e candidatos sonoros por telemetria | Render 3D local é CPU com z-buffer/Lambert. Não declara sombras, reflexos, PBR nem câmera resolvida na filmagem. |
| MOTNGRFX portátil | Tipografia extrudada, rotação e articulação por glifo, visibilidade por palavra/letra e composição frente/atrás | Reuso seletivo. Não executa o pipeline generativo completo de ComfyUI nem baixa modelos. |
| Composição contextual | `native.motion_layer` e `native.motion_behind`, manifestos RGBA, proteção por alpha, oclusão e mapeamento de quadros | Exige o FPS do bruto e cobertura integral. Não repete, congela, retima ou reordena frames para ocultar uma lacuna. |
| Direção | Cartas de opções, metadata de recursos, amostras de motion e eventos candidatos de som | O agente/humano continua responsável pela interpretação. Folhas de frames não comprovam movimento contínuo. |

Guias específicos: [OpenKatana](openkatana-adapter.md), [Motion Lab](motionlab-adapter.md),
[MOTNGRFX](motngrfx-adapter.md) e [direção contextual](contextual-editing.md).

## Instalação e disponibilidade

Na raiz de uma cópia do repositório:

```sh
python -m pip install -r requirements-motion.txt
npm ci --ignore-scripts --prefix editorial_engine/backends/motionlab
npm ci --ignore-scripts --prefix vendor/openkatana/adapter-node
python -m editorial_engine motion probe --output out/motion-probe.json
```

FFmpeg e FFprobe devem estar no PATH. Node 22+ é a referência do bridge; as
dependências Node estão fixadas em lockfiles. Instalação de navegador, Blender,
pesos e modelos é separada. O probe distingue análise, Canvas, WebGL, Blender,
2D/3D CPU e tipografia portátil. Um recurso indisponível não vira outro renderer
silenciosamente. Consulte os recibos do ambiente atual antes de planejar.

## Fluxo de criação e aplicação

### 1. Medir e dirigir

```sh
python -m editorial_engine motion reference /projeto/referencia.mp4 /projeto/analise-referencia --duration-s 10
python -m editorial_engine motion audio /projeto/trilha.wav /projeto/analise-musical
python -m editorial_engine motion guidance --output /projeto/motion-guidance.json
```

OpenKatana mede cadência, cortes candidatos, aparência e curvas de transição.
O clock de análise de 60 fps pode repetir frames de fontes mais lentas. O DSP
musical estima uma grade constante, ataques e seções; ambiguidades não devem ser
transformadas em cortes obrigatórios. O diretório e o hash do material medido
permanecem no relatório.

As cartas de `motion_guidance` descrevem finalidades, evidências e requisitos.
Elas não são um classificador por palavras-chave nem um estilo imposto. Para
novas cenas, o agente escreve uma receita declarativa usando o brief e a
referência. Receitas não renderizadas ainda não são assets disponíveis no plano.

### 2. Renderizar o componente escolhido

As [receitas de prova](../examples/motion_integration/) são executáveis e não
incluem mídia privada ou fontes. Escolha sempre uma pasta nova:

```sh
python -m editorial_engine motion render motionlab examples/motion_integration/motionlab-2d.json /projeto/exports/motion-2d-v001 --samples 4
python -m editorial_engine motion render motionlab examples/motion_integration/motionlab-3d.json /projeto/exports/motion-3d-v001 --samples 4
python -m editorial_engine motion render motngrfx examples/motion_integration/type-volume.json /projeto/exports/type-v001 --font /projeto/fontes/Fonte-Regular.ttf --font-license "Termos da fonte preservados no pacote" --asset-id title-volume
python -m editorial_engine motion preview /projeto/bruto.mp4 /projeto/exports/effect-v001 --effect local_rgb_split --params examples/motion_integration/rgb-split.json --duration-s 2
```

Motion Lab exporta PNGs RGBA e um MP4 achatado apenas para prévia. MOTNGRFX
exporta PNGs RGBA e passes com o ID de cada glifo. O wrapper gera:

- `run.json`: receita, produtor e escopo real da execução.
- `motion-layer.json`: relógio local, resolução, alpha straight e hashes dos frames.
- `inventory.json`: recurso consumível por `prepare --assets`.
- `motion-contact.png`: amostras identificadas; não é revisão de playback.
- `sonic-candidates.json`, quando produzido: candidatos de som no clock local da cena.

Um render de timeline opaco do OpenKatana permanece uma montagem independente.
Não se inventa transparência para cadastrá-lo como overlay. Pontes WebGL/Blender
usam rotas explícitas; scripts autorais exigem a opção de confiança documentada.

```sh
python -m editorial_engine motion render openkatana /projeto/timeline-com-clockmap.json /projeto/exports/timeline-v001 --project /projeto
python -m editorial_engine motion render openkatana3d /projeto/cena3d.json /projeto/exports/webgl-v001 --project /projeto
python -m editorial_engine motion render-blender /projeto/cena.blend /projeto/exports/blender-v001 --engine CYCLES
```

Uma cena WebGL com código autoral ou um script Python do Blender exige
`--trusted-script`. A execução desses scripts não fornece uma garantia de
ausência de chamadas externas: o recibo mantém esse escopo como desconhecido.
O modo padrão usa apenas a receita declarativa ou o arquivo Blender informado.

### 3. Preparar o bruto com a camada renderizada

```sh
python -m editorial_engine prepare /projeto/bruto.mp4 /projeto/preparado-v001 --assets /projeto/exports/type-v001/inventory.json --protection /projeto/protection.json --mattes /projeto/mattes
python -m editorial_engine request /projeto/preparado-v001/analysis.json /projeto/preparado-v001/catalog.json --brief-file /projeto/brief.txt --output /projeto/request.json
```

Proteção, matte, pose e tracking pertencem ao bruto atual, com sua identidade e
seu relógio. O pedido inclui amostras reais da animação e dados do recurso. O
diretor fornece `direction.json` com evidências, propósito e parâmetros. Os
efeitos prontos continuam exigindo uma capacidade verificada:

| Efeito | Bindings | Parâmetros próprios |
| --- | --- | --- |
| `native.motion_layer` | `asset: motion_asset` | `asset_start_frame`, animação de entrada opcional |
| `native.motion_behind` | `asset: motion_asset`, `matte: subject_mask` | `asset_start_frame`, `min_visible_fraction`, `min_glyph_visible_fraction`, entrada opcional |

O intervalo da decisão usa segundos da fonte. `asset_start_frame` usa quadros
locais da sequência. O mapeamento é um-para-um: o frame inicial da decisão recebe
o frame declarado do asset. Uma sequência vinculada a uma fonte específica não
pode ser transferida de pessoa ou de tempo sem refazer seu vínculo.

A composição conserva proporção e mede o alpha pela mesma transformação usada
no render. Rostos e mãos protegidos não podem ser cobertos pela parte visível.
Uma exigência de visibilidade por letra precisa de IDs de glifos reais. Um
problema de oclusão não traz o título para a frente nem descarta frames.

```sh
python -m editorial_engine plan /projeto/preparado-v001/analysis.json /projeto/preparado-v001/catalog.json /projeto/direction.json --output /projeto/bundle.json
python -m editorial_engine render /projeto/bundle.json --output /projeto/final-v001.mp4
```

Siga `review` e `patch` do fluxo contextual para a revisão vinculada ao render.
O novo compositor não remove o responsável único pelo plano nem reinicia limites
de correção. A preservação de arquivos e frames é prova técnica, não julgamento
editorial ou confirmação do usuário.

### 4. Relacionar movimento e SFX

```sh
python -m editorial_engine motion sonic-candidates /projeto/scene.json --output /projeto/sonic.json
python -m editorial_engine motion map-sonic /projeto/sonic.json /projeto/bruto.mp4 --source-first-frame 48 --source-last-frame 96 --asset-start-frame 0 --output /projeto/sonic-source.json
```

Esse exemplo requer uma animação de 48 frames com o mesmo FPS do bruto e pelo
menos 96 frames na fonte. Os candidatos passam ao clock da fonte e a amostras de
48 kHz com erro de quantização registrado. Eventos fora do trecho ficam listados;
um arredondamento que saia do intervalo é rejeitado.

O resultado não escolhe um arquivo SFX, não confere ataque ouvido nem aprova a
mixagem. O diretor de som cruza esses marcos com fala e música, consulta a
biblioteca, revisa o ataque e propõe `native.sfx` com um `audio_asset` verificado.
O render de áudio existente conserva trim, pré-roll, cauda, ganho e orçamento.

## Licenças e versões

| Origem | Revisão usada | Tratamento |
| --- | --- | --- |
| OpenKatana | `b9282bf0740a7df5b5a8862b5e289ef4cd642641` | Subconjunto Apache-2.0 com LICENSE/NOTICE e termos de terceiros. |
| Motion Lab | `6a7f1ca62b7b30d534fe181f912606ad4cfc6718` | Apenas código da revisão MIT fixada. Contribuições proprietárias posteriores não foram incorporadas. |
| MOTNGRFX | `8c0ddc816616a95f55bddc606eecea3fd5ba5ef1` | Snapshots Apache-2.0 e adaptações identificadas em `UPSTREAM.json`. |

Fontes, vídeos, músicas e modelos não recebem automaticamente a licença do
motor. Não há pesos nem acervo privado no Git. Hashes atestam integridade, e a
declaração de direitos dos assets permanece separada.

## Validação

Consulte [o registro de validação desta integração](validation-motion-integration.md)
para os testes executados, provas de vídeo, limitações do ambiente e escopo de
revisão visual. Testes sintéticos não demonstram generalização editorial, tracking
automático de qualquer pessoa nem fidelidade global a qualquer referência.
