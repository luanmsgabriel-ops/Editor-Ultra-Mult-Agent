# Motion Lab legado MIT: autoria, render e telemetria

O adaptador executa cenas declarativas em 2D e 3D, preserva PNGs RGBA e entrega os seus hashes. Os controles de tempo, grupos e exposição reutilizam a última revisão MIT auditada do Motion Lab. A direção editorial escreve o JSON a partir do material e da função da cena; este módulo não interpreta prompts nem escolhe sons por conta própria.

## Origem fixada e código incorporado

Repositório: [AndreXes03/motion-lab](https://github.com/AndreXes03/motion-lab).

Revisão incorporada: [`6a7f1ca62b7b30d534fe181f912606ad4cfc6718`](https://github.com/AndreXes03/motion-lab/tree/6a7f1ca62b7b30d534fe181f912606ad4cfc6718). A [licença MIT dessa revisão](https://github.com/AndreXes03/motion-lab/blob/6a7f1ca62b7b30d534fe181f912606ad4cfc6718/LICENSE) foi preservada em `vendor/motionlab/LICENSE`. Não foi incorporado código das revisões posteriores do Framevolve.

`vendor/motionlab/provenance.json` contém a origem fixa, SHA-256 e SHA-1 de blob Git para cada um dos 18 arquivos preservados sem alteração. A fachada verifica o próprio inventário e os bytes antes de executar. `animation.js`, `animation-groups.js`, `parameter-animation.js`, `procedural.js`, `temporal.js` e `sound-procedural.js` são as peças ativas. Os arquivos de catálogo/configuração restantes satisfazem os imports do snapshot; os presets de demonstração não são aplicados às cenas do usuário.

O adaptador em `editorial_engine/backends/motionlab` é código próprio do Editor Ultra. Ele contém a ponte JSON, o render por CPU, exemplos e a instalação isolada das dependências. O recibo identifica separadamente os hashes desse adaptador e a revisão upstream. Não se copiam vídeos, fontes, música ou outros assets de demonstração do repositório original.

## Instalação e disponibilidade medida

O ambiente de execução precisa de Node.js compatível com imports JSON modernos, Pillow e, para texto TTF/OTF, `fonttools`. A prova desta integração usou Node 24.22.1. O preview MP4 exige `ffmpeg` com `libx264`.

```bash
npm ci --ignore-scripts --no-audit --no-fund --prefix editorial_engine/backends/motionlab
python -m editorial_engine motion probe --output motion-probe.json
```

As dependências diretas são `three@0.180.0` e `@napi-rs/canvas@0.1.100`, com `package-lock.json`. `node_modules` está ignorado pelo Git. Não há download de modelos, serviço pago, GPU ou Chromium no caminho efetivamente usado.

`probe()` desenha uma forma 2D e um volume 3D, codifica os PNGs e verifica pixels visíveis e transparentes. O resultado contém backend, versões, hashes de prova e limitações. Arquivos instalados sem uma prova de execução não produzem um `available: true`.

| Backend | Operação efetiva | Limite declarado |
| --- | --- | --- |
| `motionlab-canvas2d-napi/1` | Grafo Canvas2D upstream sobre Skia/NAPI, formas, caminhos, texto, clips e composição | Sem nós de imagem/vídeo nesta revisão do adaptador |
| `three-cpu-lambert-zbuffer/1` | Geometria Three.js, hierarquia, câmera perspectiva, clipping dos seis planos, z-buffer e luz difusa por pixel | Materiais opacos; sem sombras, reflexos, PBR, antialias espacial ou WebGL |

A instalação local de Chromium não implica WebGL disponível. No ambiente desta implementação, a inicialização de Chromium falhou por restrição de socket. O backend 3D por CPU é uma operação própria, identificada em cada recibo; sua execução foi verificada com geometria e movimento reais.

## Comandos disponíveis

Os exemplos são receitas didáticas, sem configurar o estilo de outros projetos:

```bash
python -m editorial_engine motion render motionlab editorial_engine/backends/motionlab/examples/motion2d.json /tmp/motionlab-2d-v1 --samples 8 --shutter-angle 210 --asset-id movimento-2d
python -m editorial_engine motion render motionlab editorial_engine/backends/motionlab/examples/motion3d.json /tmp/motionlab-3d-v1 --samples 4 --shutter-angle 210 --asset-id volume-3d
python -m editorial_engine motion evaluate editorial_engine/backends/motionlab/examples/motion2d.json --time-s 0.75 --output estado-motion.json
python -m editorial_engine motion sonic-candidates editorial_engine/backends/motionlab/examples/motion2d.json --output eventos-motion.json
```

O diretório de saída de cada render deve ser novo. O comando cria um recibo do produtor, `motion-layer.json`, `inventory.json`, contato visual e os candidatos sonoros. Use o inventário com `prepare --assets` no fluxo contextual. A importação valida novamente o raster, os hashes, a quantidade de frames e o relógio; a existência do asset não é uma decisão para aplicá-lo a qualquer trecho.

Para localizar candidatos sonoros no relógio do bruto:

```bash
python -m editorial_engine motion map-sonic eventos-motion.json bruto.mp4 --source-first-frame 120 --source-last-frame 167 --asset-start-frame 0 --output eventos-no-bruto.json
```

Esse comando mapeia instantes; a escolha de um arquivo SFX, o nível, a duração, o alinhamento do ataque e a validação auditiva continuam com o fluxo de som. Os limites de FPS e intervalo são verificados pelo importador/mapeador, sem retiming implícito.

## Contrato da cena

Campos obrigatórios: `schema_version: "motionlab-scene/1"`, `id`, `mode`, `width`, `height`, `fps`, `frame_count` e `nodes`. FPS é racional textual, como `"24/1"` ou `"30000/1001"`. A duração exata decorre de `frame_count / fps`; um `duration_s` declarado deve coincidir. `background: null` preserva transparência; `"#RRGGBB"` declara um fundo opaco.

```json
{
  "schema_version": "motionlab-scene/1",
  "id": "revelar-comparacao",
  "mode": "2d",
  "width": 640,
  "height": 360,
  "fps": "24/1",
  "frame_count": 48,
  "background": null,
  "nodes": [
    {"id": "barra", "type": "rect", "x": 40, "y": 140,
     "width": 100, "height": 40, "fill": "#3180ed"}
  ],
  "tracks": [
    {"target": "barra", "property": "x", "keys": [
      {"t": 0, "value": 40, "ease": "inOut"},
      {"t": 2, "value": 480}
    ]}
  ]
}
```

Os nós têm IDs estáveis, filhos opcionais e janela de ativação `start_s <= tempo < end_s`. Para desabilitar propostas de som de um nó ou grupo, use `sound: false`. A geometria e sua função narrativa devem ser autoradas pelo diretor; o motor não as deduz a partir de nomes de arquivo ou palavras da fala.

| Modo/tipo | Geometria ou conteúdo | Controles |
| --- | --- | --- |
| 2D `group` | Hierarquia em `children` | `x`, `y`, `rotation`, `scaleX`, `scaleY`, `opacity`, clip/blend |
| 2D `rect` | `width`, `height`, `cornerRadius` opcional | Transformações 2D, fill/stroke e animação de dimensões |
| 2D `circle` | `radius` | Transformações 2D, fill/stroke e raio animado |
| 2D `path` | `commands` M/L/Q/C/A/Z | Transformações 2D, fill/stroke e clip |
| 2D `text` | `text`, `font_id`, `font_size` | Texto em uma linha, fonte real, alinhamento e baseline |
| 3D `group` | Hierarquia em `children` | `position`, `rotation`, `scale` como vetores de três números |
| 3D `box`, `plane` | `size`, vetor de três ou dois números | Transformações 3D e material |
| 3D `sphere`, `torus` | `radius`, `tube` no torus, subdivisões opcionais | Transformações 3D e material |
| 3D `text3d` | `text`, `font_id`, `font_size`, `depth` | Extrusão real com Three TextGeometry e fonte typeface explícita |

Rotações são radianos. Coordenadas 2D são pixels; retângulos começam no canto local `(0,0)` e círculos são centrados ali. As unidades 3D são as da cena autorada. Escalas 3D devem ser positivas.

Material 3D aceita `color`, `unlit` e `side: "front" | "double"`. Luzes `ambient`, `directional` e `point` recebem cor/intensidade explícitas. `directional.direction` aponta da superfície em direção à luz. A luz pontual calcula a direção por pixel, sem simular queda física com a distância. Parâmetros como `roughness`, transparência de material ou sombra são rejeitados, pois o backend não os executa.

Cenas 3D exigem `camera.position` e `camera.target`. `fov`, `near` e `far` controlam a perspectiva; os defaults técnicos são 50 graus, 0,1 e 1000. Posição, alvo e FOV podem ser animados. A câmera não pode coincidir com seu alvo, inclusive após animação.

## Animação absoluta e grupos independentes

Uma track escolhe `target`, `property`, `keys` e, opcionalmente, `group`. Cada key tem `t`, `value`, `ease` e coordenadas `bezier` quando pertinentes. Valores podem ser escalares ou vetores. Easing aceito: `smooth`, `linear`, `hold`, `in`, `out`, `inOut`, `bezier`. Duas tracks não podem controlar a mesma propriedade do mesmo nó.

A função `evaluate()` sempre parte do JSON e do instante absoluto. Pedir os tempos 0,7 → 0,2 → 0,7 não acumula transformação nem depende da ordem da reprodução.

```json
{
  "groups": {
    "objeto-lento": {
      "start": 0, "end": 2, "rate": 0.5,
      "keys": [{"t": 0, "value": 0}, {"t": 2, "value": 1}]
    }
  }
}
```

`group.keys` usam tempo local da janela e progresso de 0 a 1. O grupo remapeia somente as tracks que o nomeiam, sem mudar duração do filme, FPS ou áudio. Fora da janela, o upstream volta ao relógio absoluto da cena; o autor precisa compor esse retorno se não quiser uma mudança brusca. Use `evaluate()` para conferir os tempos de cada grupo no instante crítico.

## Exposição, cortes e alpha

`samples` aceita 1–64; `shutter_angle`, 0–360 graus; o perfil é `cosine` ou `box`. A lista `cuts` contém tempos de corte em segundos da cena. O upstream amostra a exposição centrada no frame e a recorta aos limites do plano. No instante do corte, somente o plano novo contribui. A lista de cortes não muda os nós automaticamente: o autor declara ativações, valores em hold ou a mudança de cena correspondente.

Os subframes são calculados a partir do tempo absoluto. O adaptador acumula luz linear com RGB premultiplicado pelo alpha e converte a saída para RGBA **straight** em sRGB. Isso conserva a cor nas bordas borradas ao inserir a camada sobre o vídeo. Cada frame guarda os tempos e pesos realmente utilizados na exposição.

O MP4 solicitado pelo CLI é um preview opaco, sem áudio. Em cenas transparentes, seu fundo de inspeção é preto, declarado separadamente em `preview.flatten_background`. Esse fundo não entra nos PNGs da camada. A API Python aceita outro `preview_background`. A composição contextual deve consumir os PNGs e o manifesto, preservando a transparência.

## Fontes e assets

Toda fonte é declarada em `fonts` com `id`, `path`, `sha256` e `format`. `format: "font"` usa TTF/OTF em 2D; `"three-typeface"` usa JSON compatível com Three FontLoader para extrusão 3D. O autor fornece arquivos e direitos de uso; não há fonte substituta embutida.

O validador verifica o hash, o parse da fonte e a presença dos caracteres antes de renderizar. Falta de acento ou outro glifo bloqueia o texto, sem aceitar fallback silencioso do sistema. Texto em várias linhas exige nós separados, preservando controles independentes. Fontes e imagens do usuário permanecem fora do código vendorizado.

O legado incorporado não fornece um nó JSON de imagem/vídeo neste adaptador. A importação de filmagem, matte, textura, tracking, câmera reconstruída e oclusão humana continua nos componentes próprios do Editor Ultra. Uma câmera 3D autorada não constitui, por si, evidência de matchmove do bruto.

## Candidatos sonoros e evidências

`sonic_candidates()` usa o estado animado para medir posição, tamanho, rotação, aparição e acomodação. O planejador de candidatos vem do upstream MIT. A amostragem reinicia em cada plano, impedindo que um salto no corte pareça uma travessia rápida.

O resultado contém `clock: "scene_seconds"`, FPS, quantidade de frames, hash da cena normalizada e uma lista `candidates`. Cada candidato registra `time_s`, `duration_s`, `source_node`, `event_kind`, `intensity`, `pan` e `evidence_ids`. A intensidade é a heurística de ganho derivada do movimento no upstream, não uma medição de loudness nem um nível de mix aprovado. As evidências mantêm o estado anterior/posterior e o intervalo amostrado. `sound_asset` permanece `null` e `semantic_selection` permanece `false`.

Em 2D a visibilidade é aproximada por caixas do grafo; em 3D são caixas da geometria projetada. Isso não prova oclusão por pixel nem adequação de um som. O resultado declara `visibility_is_pixel_verified: false`. O diretor e o agente de som cruzam candidatos com intenção, voz, música, bibliotecas autorizadas e ataque audível. Para usar a camada começando no frame K dentro do trecho de fonte, mapeie explicitamente esse relógio antes de propor `native.sfx`.

## API Python e recibo

```python
from editorial_engine.motionlab import probe, evaluate, render, sonic_candidates

availability = probe()
state = evaluate(scene, time_s=0.75)
receipt = render(scene, "/tmp/motion-v2/preview.mp4", samples=8, shutter_angle=210)
sonic = sonic_candidates(scene, rate=60, density=0.5)
```

`render` devolve `frames_dir`, `frames: [{index, path, sha256, time_s, exposure}]`, `frame_manifest`, seu hash, FPS racional, `frame_count`, dimensões, alpha, faixa de alpha, opacidade medida, recibo, cena normalizada e preview opcional. `scene_sha256` é o mesmo nas funções de render e telemetria quando recebem a mesma receita. Os hashes dos arquivos da fonte e do adaptador acompanham o resultado.

Campos desconhecidos, fonte ausente, hash divergente, geometria não implementada, FPS incoerente, ID inventado, keyframes fora da duração e sobrescrita de artefatos são erros explícitos. O limite atual é 500 nós, 10000 keys, 18000 frames, 600 segundos e raster de até 3840×2160 pixels no total. O custo efetivo também depende de triângulos e subframes; render por CPU é uma execução offline.

## Verificação e revisão

```bash
python -m pytest tests/test_motionlab_integration.py -q
```

Os testes incluem identidade da revisão MIT, rejeição de contratos inválidos, fonte real e glifo ausente, texto 3D extrudado, ordem independente da avaliação, grupos separados, alpha straight no blur, corte sem contaminação, z-buffer, luz, frames realmente distintos e contagem/FPS do MP4 codificado. Também verificam que eventos derivados não escolhem arquivo sonoro e que um salto de corte não cria um glide fictício.

O recibo começa com revisão perceptiva `unverified` e aprovação do usuário falsa. Render bem formado, hashes e testes não comprovam fidelidade à referência nem qualidade visual. Depois da composição no bruto, mantenha a revisão do plano, do movimento, do áudio ouvido e dos bytes finais no fluxo contextual. A aprovação de uma referência anterior não se transfere a uma nova cena.
