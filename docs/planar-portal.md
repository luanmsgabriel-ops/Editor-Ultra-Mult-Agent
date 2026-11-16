# Portal planar com fontes independentes

`visual_fidelity.planar_portal` 1.0.0 transforma quatro pontos medidos em uma
revelação reproduzível. Recebe os arquivos reais, os relógios e a geometria
autorizada; gera composição MP4 silenciosa ou sequência PNG RGBA. A produção
nativa `operation="planar_portal"` conecta o mesmo render ao projeto persistente.

## Direção e mapeamento

Escolha o mapeamento pela observação do vídeo:

| Modo explícito | Movimento do conteúdo | Uso |
|---|---|---|
| `screen_reveal` | O conteúdo ocupa um retângulo fixo no canvas; o polígono controla sua visibilidade. | Faixa inclinada revelando uma pessoa que permanece ereta. |
| `projective` | A imagem é projetada dos quatro pontos de origem aos quatro pontos de destino. | Imagem aderida a um painel plano que muda de perspectiva. |

O primeiro modo exige `placement=[x,y,largura,altura]`. Esse retângulo é o destino
exato da imagem, com escala horizontal e vertical explícitas; prepare a proporção
correta antes de compor. Não existe crop, contain, zoom ou ajuste automático ao
retângulo envolvente do portal. No segundo modo, `source_quad` pode selecionar uma
região convexa da imagem; o padrão declarado da API é a imagem inteira.

As coordenadas são normalizadas pelas bordas do raster. `(0,0)` é a borda superior
esquerda e `(1,1)` é a borda inferior direita. Os quatro pontos mantêm identidade e
ordem horária nas coordenadas da imagem. Podem ultrapassar o canvas, permitindo
uma abertura final que sai da tela. A sequência deve continuar convexa e sem
auto-interseção em cada quadro interpolado. Uma linha colapsada ou quatro pontos
coincidentes são permitidos somente quando `opacity=0`.

Para inserir uma imagem de 720 × 406 em um canvas de 720 × 1280, iniciando na linha
437, use `placement=[0,437/1280,1,406/1280]` no código que escreve o JSON. JSON
recebe os valores numéricos calculados, e não essas expressões. As coordenadas do
portal continuam pertencendo ao canvas global, incluindo as barras.

## Manifesto `planar-portal/1`

Exemplo de estrutura; os SHA-256 precisam ser calculados dos arquivos reais:

```json
{
  "schema": "planar-portal/1",
  "width": 720,
  "height": 1280,
  "fps": "30/1",
  "frames": 301,
  "base": {
    "kind": "video",
    "path": "assets/base.mp4",
    "sha256": "SHA256_REAL_DA_BASE",
    "origin": "Bruto atual; raster preservado",
    "clock": {"start_frame": 0, "step": 1}
  },
  "insert": {
    "kind": "video",
    "path": "assets/insert.mp4",
    "sha256": "SHA256_REAL_DA_INSERCAO",
    "origin": "Take separado produzido para a revelacao",
    "clock": {"start_frame": 0, "step": 1}
  },
  "mapping": "screen_reveal",
  "placement": [0, 0.34140625, 1, 0.3171875],
  "feather_px": 0,
  "geometry": {
    "keyframes": [
      {
        "frame": 0,
        "quad": [[0.2, 0.5], [0.8, 0.4], [0.8, 0.4], [0.2, 0.5]],
        "opacity": 0,
        "easing": "linear"
      },
      {
        "frame": 120,
        "quad": [[0.1, 0.5], [0.9, 0.35], [0.9, 0.5], [0.1, 0.65]],
        "opacity": 1,
        "easing": "hold"
      },
      {
        "frame": 300,
        "quad": [[-0.1, 0.3], [1.1, 0.3], [1.1, 0.7], [-0.1, 0.7]],
        "opacity": 1,
        "easing": "hold"
      }
    ]
  }
}
```

Cada chave exige `frame`, `quad`, `opacity` e `easing`. O easing pertence ao
intervalo que começa naquela chave. Os modos são `linear`, `hold` e `smoothstep`
(`3t²−2t³`); o último não pode ser presumido apenas para suavizar um movimento
medido. `hold` mantém a chave até a próxima e permite cortes deliberados. As
chaves devem iniciar em zero e terminar em `frames−1`. Também é válido fornecer
uma chave medida para cada quadro. O componente não extrapola as pontas.

### Fontes e relógios

Todos os caminhos relativos partem da pasta do manifesto. Todo arquivo exige um
SHA-256 e cada fonte exige uma descrição `origin`. Base e inserção precisam ter
arquivos e hashes independentes.

- **Vídeo:** `kind="video"`, `path`, `sha256`, `origin` e
  `clock={"start_frame":N,"step":1}`. O FPS e os timestamps de apresentação são
  conferidos contra o relógio do manifesto. Não há repetição, congelamento,
  descarte de frames ou retime automático.
- **Imagem estática:** `kind="image"`, `path`, `sha256`, `origin` e `static=true`.
  Não possui `clock`. O recibo preserva essa condição; uma imagem animada pela
  máscara continua sendo uma imagem estática.
- **Sequência:** `kind="sequence"`, `fps`, `origin`, `clock`, `files` e `sha256`.
  `files` é a lista ordenada de `{"path":...,"sha256":...}`. Calcule o hash da
  sequência com `sequence_sha256(files)`: SHA-256 dos hashes dos quadros unidos
  por `\n`, sem newline final. Cada quadro usa seu próprio arquivo. O consumidor
  confere todos os hashes e a cobertura do intervalo.

A base deve chegar opaca, com o raster final. As fontes aceitam imagens de oito
bits; PNG RGBA da inserção conserva alpha. A dimensão e os canais de uma sequência
não podem mudar durante o render. RGB e alpha são interpolados em representação
premultiplicada, e a camada exportada usa alpha straight.

### Oclusão

O objeto opcional `occlusion` contém:

```json
{
  "source": {
    "kind": "video",
    "path": "assets/hand-matte.mp4",
    "sha256": "SHA256_REAL_DA_MASCARA",
    "origin": "Mascara temporal medida na base atual",
    "clock": {"start_frame": 0, "step": 1}
  },
  "base_sha256": "SHA256_REAL_DA_BASE",
  "coordinate_space": "canvas"
}
```

Branco preserva a base na frente; preto revela a inserção. A máscara precisa ter
o mesmo raster final, ser cinza e acompanhar o início do relógio da base. Uma
base temporal exige máscara temporal. Para bordas exatas, prefira sequência PNG
em tons de cinza; compressão de vídeo pode alterar os valores do matte.

Esse vínculo detecta uma máscara pertencente a outro arquivo, mas não mede a
qualidade do recorte. Mãos, cabelo, bordas rápidas e eventuais perdas de tracking
precisam de revisão no resultado contínuo.

## Execução direta e integração

```bash
python -m visual_fidelity.planar_portal /CAMINHO/portal.json /CAMINHO/portal-v1.mp4
python -m visual_fidelity.planar_portal /CAMINHO/portal.json /CAMINHO/portal-layer-v1 --mode layer
```

A saída precisa ser nova. MP4 recebe recibo `portal-v1.mp4.json`. Uma camada recebe
`frame-000000.png` em diante, `motion-layer.json` compatível com o motor existente
e `portal-render.json`. Quando a base tem relógio temporal, o manifesto da camada
também conserva seu `source_binding`; não reutilize essa camada como rastreamento
de uma pessoa nova.

O render MP4 é silencioso. O áudio deve ser vinculado na timeline responsável,
com trim, duração e revisão explícitos. Um campo `audio` no manifesto é rejeitado
para evitar que uma intenção de áudio seja ignorada.

O projeto persistente usa o adaptador nativo:

```python
from editorial_engine.production import production_request, execute_request

request = production_request(
    "portal-reveal-v1", "planar_portal",
    prompt="Executar a abertura medida e a oclusao do bruto atual.",
    output_kind="video",
    adapter_id="bundled.planar_portal",  # None também seleciona este nativo.
    parameters={"manifest_input": "portal-manifest"},
    inputs=tracked_inputs,
    constraints={"width": 720, "height": 1280,
                 "fps": "30/1", "frame_count": 504},
)
execution = execute_request(request, "/CAMINHO/production-portal-v1")
```

`tracked_inputs` precisa conter o manifesto como `kind="json"` e **cada arquivo**
de base, inserção, oclusão e sequência. Cada entrada fornece `id`, `kind`, `path`
absoluto e `sha256`. Arquivos declarados apenas dentro do manifesto bloqueiam a
produção; caminhos e hashes precisam corresponder aos inputs rastreados. Em um
projeto, registre essa mesma solicitação na fila e execute o fluxo `project
produce` já existente.

O adaptador produz `portal.mp4` na pasta nova da tentativa. Retorna hash, custo
zero e proveniência `simulated=false`, vinculando também o recibo do produtor. O
descritor inclui os hashes de `production.py`, `planar_portal.py` e
`geometric_replay.py`. Uma retomada após alteração dessa implementação bloqueia o
reuso silencioso do resultado anterior; conserve-o e abra outra execução. O
adaptador `bundled.motion` mantém seu contrato.

Também estão disponíveis as funções `evaluate_quad(...)`,
`render_portal_frame(...)` e `render(...)` para adaptadores Python. Uma composição
privada deve consumir essas mesmas primitivas, mantendo a correção reutilizável
no motor. Dados JSON não selecionam comandos de shell nem importações arbitrárias.

## Alcance da verificação

O recibo registra os bytes utilizados, os relógios, o hash dos quadros RGB/RGBA,
o hash do arquivo final e o estado de revisão pendente. Para MP4, o componente
decodifica os timestamps e confere FPS, raster e contagem do arquivo efetivo.

Tracking, segmentação, geração de imagens, clean plate, reparação de regiões
ocultas e seleção de efeito pertencem às etapas anteriores. Um warp planar não
resolve câmera ou volume 3D. Fotografia recuperada de uma referência achatada deve
permanecer identificada na origem, incluindo partes inferidas. Hashes de arquivos
distintos não provam que seu conteúdo foi produzido de forma independente.

Os testes exercitam projeção real, preservação de orientação, alpha premultiplicado,
oclusão, fechamento, extrapolação fora do canvas, dobra entre keyframes,
sequenciamento, proteção dos originais, export RGBA importável e produção MP4
efetiva. Também bloqueiam fonte oculta, hash alterado, FPS incompatível e reuso
após mudança do motor. Esses resultados verificam execução técnica; fidelidade,
playback contínuo, áudio ouvido e aprovação do usuário têm registros separados.
