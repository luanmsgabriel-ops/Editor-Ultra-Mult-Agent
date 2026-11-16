# OpenKatana no Editor Ultra

O adaptador `editorial_engine.openkatana` executa medição de vídeo, análise musical, prévias de efeitos, timelines Canvas e cenas autorais. A direção editorial continua no Editor Ultra: uma medição não decide, sozinha, qual efeito comunica a fala ou acompanha um gesto.

## Código incorporado e licença

| Item | Revisão e evidência |
| --- | --- |
| Projeto de origem | [rk0neki/OpenKatana](https://github.com/rk0neki/OpenKatana) |
| Pin | [`b9282bf0740a7df5b5a8862b5e289ef4cd642641`](https://github.com/rk0neki/OpenKatana/tree/b9282bf0740a7df5b5a8862b5e289ef4cd642641), versão 0.1.3 |
| Licença principal | [Apache-2.0](https://github.com/rk0neki/OpenKatana/blob/b9282bf0740a7df5b5a8862b5e289ef4cd642641/LICENSE), preservada em `vendor/openkatana/LICENSE` |
| Avisos preservados | `NOTICE`, `THIRD_PARTY_NOTICES.md`, licenças MIT anteriores e licenças dos componentes Three.js/cannon-es |
| Manifesto | `vendor/openkatana/VENDOR-MANIFEST.json`: SHA-256, Git blob SHA-1 e tamanho de cada arquivo |
| Integridade do manifesto | SHA-256 `32e45b972e17b21ff37b3f90e1e52a6505200aafa3ca007c253aa9a4f6183599`, fixado no adaptador |
| Runtime Canvas adicional | `@napi-rs/canvas` 0.1.100, MIT, com `package.json` e lock próprios |

O subconjunto contém 95 arquivos de texto originais, verificados contra os blobs do commit. Os arquivos upstream permanecem sem alterações. A ponte Python/Node, seus testes e esta documentação são adições do Editor Ultra. O pacote não inclui pesos, fontes binárias, arquivos de mídia, Studio completo ou serviços externos. Os avisos upstream descrevem a distribuição original mais ampla; um aviso de fonte/modelo não significa que esse ativo tenha sido incorporado aqui.

Módulos incorporados que sustentam as operações:

- [`reference_measure.py`](https://github.com/rk0neki/OpenKatana/blob/b9282bf0740a7df5b5a8862b5e289ef4cd642641/openkatana/reference_measure.py): medidas extraídas dos pixels da referência.
- [`audio_analysis.py`](https://github.com/rk0neki/OpenKatana/blob/b9282bf0740a7df5b5a8862b5e289ef4cd642641/openkatana/audio_analysis.py): energia, onsets, tempo, batidas e diagnóstico de ambiguidade.
- [`contracts.py`](https://github.com/rk0neki/OpenKatana/blob/b9282bf0740a7df5b5a8862b5e289ef4cd642641/openkatana/contracts.py) e módulos de validação: estrutura e requisitos da timeline.
- [`web/engine.js`](https://github.com/rk0neki/OpenKatana/blob/b9282bf0740a7df5b5a8862b5e289ef4cd642641/openkatana/web/engine.js), efeitos e transições: renderização Canvas por quadro.
- [`render.py`](https://github.com/rk0neki/OpenKatana/blob/b9282bf0740a7df5b5a8862b5e289ef4cd642641/openkatana/render.py): codificação FFmpeg e caminho Chromium opcional.
- [`scene3d.py`](https://github.com/rk0neki/OpenKatana/blob/b9282bf0740a7df5b5a8862b5e289ef4cd642641/openkatana/scene3d.py): cenas WebGL declaradas.
- [`blender_bridge.py`](https://github.com/rk0neki/OpenKatana/blob/b9282bf0740a7df5b5a8862b5e289ef4cd642641/openkatana/blender_bridge.py) e `blender_worker.py`: execução por um Blender instalado separadamente.

## Instalação e disponibilidade

As operações de análise requerem Python com NumPy/Pillow/OpenCV e os executáveis FFmpeg/FFprobe. A codificação de vídeo requer `libx264`. Para Canvas, instale a dependência fixada, a partir da raiz do repositório:

```bash
npm ci --ignore-scripts --prefix vendor/openkatana/adapter-node
```

Não são executados scripts de ciclo de instalação. Os binários nativos opcionais do Canvas vêm dos pacotes de plataforma fixados no lock. `node_modules` não é versionado. A instalação foi exercitada com o cache local por `npm ci --ignore-scripts --offline --prefix vendor/openkatana/adapter-node`.

O adaptador procura o Canvas nesta ordem: caminho explícito em `EDITOR_ULTRA_OPENKATANA_CANVAS_MODULE`; instalação própria acima; instalação compartilhada de `editorial_engine/backends/motionlab/node_modules/@napi-rs/canvas`. O nome e a versão 0.1.100 são verificados e o caminho absoluto é passado ao Node. A operação não depende de `NODE_PATH`. `EDITOR_ULTRA_NODE` permite selecionar um executável Node instalado.

```python
from editorial_engine.openkatana import probe_openkatana
report = probe_openkatana()
print(report["capabilities"])
```

O probe não instala dependências, baixa modelos nem chama APIs. O teste Canvas desenha e lê um pixel. O teste Blender verifica um arquivo executável e sua resposta real a `--version`; uma variável de ambiente preenchida não basta. O probe Chromium tenta iniciar o navegador e criar os contextos necessários. `check_browser=False` mantém o navegador como desconhecido e as capacidades que o requerem bloqueadas.

Nesta implementação foram executados Canvas em Node e Blender/Cycles em CPU. O Chromium deste ambiente foi bloqueado na inicialização de IPC/socket; portanto, o caminho WebGL permanece bloqueado aqui. O runtime `node-canvas` é um executor Canvas local separado, com declaração própria no relatório. Não há afirmação de igualdade de pixels com Chromium nem conversão automática de uma solicitação WebGL/3D em 2D.

## API de análise

```python
from editorial_engine.openkatana import analyze_reference, analyze_audio

reference = analyze_reference(
    "referencia.mp4", "resultados/referencia-v1",
    start_s=0, duration_s=12,
    measures=("cuts", "cadence", "look", "textures", "transitions"),
)
music = analyze_audio(
    "musica.wav", "resultados/musica-v1",
    start_s=0, duration_s=30, fps="30000/1001", beats_per_bar=4,
)
```

Cada diretório de saída deve ser novo. Os originais são preservados e seus hashes são conferidos depois da execução. A análise de referência usa o relógio de análise upstream a 60 fps, separado do FPS e do deslocamento da fonte. Uma fonte mais lenta pode ter quadros repetidos na análise; isso não recupera movimento ausente. Estimativas numéricas indisponíveis aparecem como `null` no recibo estrito; arquivos upstream brutos são mantidos.

A análise musical é DSP local sobre o áudio real. A grade de batidas é uma estimativa de tempo constante; ambiguidade de oitava e confiança do downbeat permanecem nos resultados. O deslocamento `start_s` fica no `clockmap`. Nenhuma operação registra audição ou aprovação estética como concluídas.

## Prévia individual

```python
from editorial_engine.openkatana import preview_effect

preview = preview_effect(
    "bruto.mp4", "resultados/rgb-split-v1",
    effect="local_rgb_split", params={"amount": 80},
    start_frame=30, frame_count=60,
    renderer="node-canvas", include_audio=False,
)
print(preview["path"], preview["sha256"])
```

Também existem `start_s` e `duration_s`, desde que correspondam exatamente a quadros inteiros da fonte. A prévia não arredonda um pedido subframe. O intervalo deve existir na fonte CFR e ter no máximo 3.600 quadros. Material HDR, com rotação de contêiner ou pixels não quadrados exige conformação explícita antes desta operação.

O efeito é uma escolha explícita do chamador, não uma escolha automática. `spatial_mode` aceita somente `screen`: a prévia não demonstra âncora planar, rastreamento de mão, oclusão ou integração 3D. O áudio é omitido por padrão; `include_audio=True` extrai o mesmo intervalo quando a fonte possui áudio. O relatório registra se foi incluído.

## Timeline e vínculo com a fonte

```python
from editorial_engine.openkatana import make_clockmap, render_timeline

timeline = {
    "canvas": {"w": 1920, "h": 1080, "fps": 30, "frames": 60},
    "clips": {
        "bruto": {"frames_dir": "frames", "pattern": "%05d.png",
                  "n": 60, "fps": 30, "w": 1920, "h": 1080}
    },
    "shots": [{"f0": 0, "f1": 60, "clip": "bruto", "speed": 1}],
}
clockmap = make_clockmap(timeline, {
    "bruto": {
        "kind": "source", "path": "/caminho/absoluto/bruto.mp4",
        "sha256": "SHA256_REAL_DO_ARQUIVO",
        "fps": "30", "frame_count": 60, "origin_frame": 0,
    }
})
recipe = {"timeline": timeline, "clockmap": clockmap}
result = render_timeline("projeto", recipe, "resultados/timeline-v1")
```

O exemplo exige mídia e hash reais. A receita pode ser um objeto Python ou um caminho JSON. O envelope com `timeline` e `clockmap` é apropriado para a CLI. Também é possível passar uma timeline pura e `clockmap=` como argumento separado, sem duplicar o mapa.

O binding `kind="source"` confirma mais do que a existência do vídeo: verifica SHA, FPS racional e cobertura do intervalo; decodifica novamente os quadros exatos com FFmpeg; compara todos os pixels RGBA de cada PNG com os quadros correspondentes de `origin_frame`. A validação independe da extensão do arquivo. PNGs de outro vídeo não podem usar o hash de uma fonte válida. Cor, crop ou redimensionamento previamente aplicados exigem uma fonte conformada e identificada ou uma sequência autoral declarada.

O binding `kind="authored_sequence"` exige FPS, contagem, origem e `provenance` não vazia. Essa declaração identifica uma sequência produzida por outro processo; não afirma igualdade com um vídeo original. Os arquivos efetivamente consumidos ainda têm hashes próprios.

O preflight verifica as amostras de cada shot, rampas de velocidade, blends, handles de transição, painéis de colagem, trails, mapas e overlays. Esgotar a fonte bloqueia a execução se não houver `loop` explícito. Os modos upstream são `clamp`, `loop` e `pingpong`; o primeiro segura a borda. Quando o autor declara um desses modos, as amostras fora da faixa ficam identificadas em `sampling_audit.explicit_repetitions`, com dono, clip, contagem e intervalo. Não se inventa um modo `hold` inexistente no contrato upstream.

Efeitos temporais aninhados exigem ainda `clockmap.temporal_output_boundary = {"mode": "clamp", "reason": "MOTIVO_EDITORIAL"}`. Para esses stacks, o preflight verifica conservadoramente todos os quadros possíveis de saída daquele shot, incluindo frames que uma combinação concreta talvez não use. Isso pode exigir mais handles ou bloquear uma receita; evita afirmar cobertura que não foi demonstrada. Alterar os controles de amostragem exige regenerar o mapa.

O encoder Node recebe o FPS racional do `clockmap`. A prévia conserva a fração exata da fonte. O relatório de saída confere igualdade exata de fração e contagem; `30000/1001` tem regressão executada. `frame-trace.json` mantém as escolhas de fonte do engine por quadro. O preflight é uma conferência técnica; não comprova que um corte ou uma repetição tenha função narrativa adequada.

Hooks arbitrários da timeline não são habilitados neste adaptador. Áudio procedural por `audio.cues` é bloqueado; use faixas de áudio explícitas com fontes indexadas. Tipografia requer arquivos de fontes fornecidos no projeto. As leituras do bridge Canvas ficam confinadas ao diretório do projeto.

## Cenas 3D e Blender

```python
from editorial_engine.openkatana import render_scene3d, render_blender

# Requer Chromium/WebGL realmente disponível; não recorre a Canvas se falhar.
scene = render_scene3d("projeto", "scene.json", "resultados/webgl-v1")

# Rota separada, com Blender instalado; .blend pode ser usado sem script autoral.
blender = render_blender(
    "scene.blend", "resultados/blender-v1",
    engine="CYCLES", start=1, end=30,
)

# Um .py executa código local confiado e exige declaração explícita.
script = render_blender(
    "scene.py", "resultados/script-v1",
    engine="CYCLES", trusted_script=True,
)
```

`render_scene3d(project_dir, scene, output_dir, *, trusted_script=False)` usa o caminho WebGL upstream. `render_blender(source, output_dir, *, engine="BLENDER_EEVEE", start=None, end=None, trusted_script=False)` usa o bridge upstream e o Blender instalado. `OPENKATANA_BLENDER` pode apontar para seu executável. O adaptador não baixa o Blender nem altera o engine pedido quando ele falha.

A prova local de Blender usou geometria, câmera, luz, Cycles CPU e PNGs RGBA com pixels opacos e transparentes. O fixture declarou `scene.cycles.use_denoising = False`, pois esse build não possui OpenImageDenoise. Isso é configuração explícita do fixture, não um fallback aplicado silenciosamente a cenas de terceiros.

O worker registra os hashes das texturas antes de renderizar; o adaptador compara esses hashes aos arquivos depois do render. Uma textura alterada durante a execução impede o recibo de sucesso. A fonte da cena também permanece vinculada ao seu SHA. Simulações precisam de bake quando sua reutilização requer acesso aleatório reproduzível, conforme o recibo upstream.

Scripts `.py` confiados e authoring JavaScript executam código fornecido pelo projeto. O adaptador não observa tudo o que esse código pode chamar: nesses modos, `external_api_called`, `external_model_executed` e `credits_used` são `null`, com `external_activity="not_observed_trusted_code"`. O recibo bruto upstream é preservado como evidência de origem, sem converter seu campo de créditos em garantia do adaptador. Os testes próprios executaram apenas cenas locais.

Uma cena autoral 3D não resolve automaticamente a câmera de uma filmagem existente. Esses resultados declaram `camera_solve_on_footage=False`. Para inserir a cena atrás ou ao redor de uma pessoa, o fluxo contextual ainda precisa da câmera/âncora, dos mattes, dos relógios e da verificação espacial do próprio bruto.

## Recibos e reutilização das imagens

Todo render bem-sucedido fornece `path`, `sha256`, `fps` racional, `frame_count`, `width`, `height`, `clockmap`, runtime e controles técnicos. `frames` contém caminho, SHA-256 e índice de cada PNG. `sequence` descreve diretório/padrão e alpha. `adapter-receipt.json` é salvo e a resposta inclui caminho/hash do recibo.

O MP4 H.264 é opaco, inclusive quando uma cena também produz uma sequência PNG transparente. `video_alpha_mode="opaque"` deixa essa distinção explícita. `alpha="straight"` descreve a sequência RGBA; uma timeline comum de vídeo usa `alpha="opaque"`. O importador deve consumir os PNGs quando precisa de transparência. Uma sequência opaca continua sendo válida como cena separada ou camada de fundo declarada.

Os recibos verificam decodificação, clock, hashes de entrada e hashes de frames. Eles também mantêm `perceptual_review="not_performed"` e `user_approval="pending"`. Uma mudança de bytes exige nova evidência e nova revisão. Não há agente remoto, modelo generativo ou endpoint configurado por este adaptador.

## Validação executada

```bash
env -u NODE_PATH python -m unittest discover -s tests -p 'test_openkatana_integration.py' -v
```

A suíte exercitou medição real da referência, DSP em pulsos conhecidos, execução do efeito `local_rgb_split` pelo engine upstream e render de geometria real por Blender/Cycles CPU. O teste do efeito compara o PNG renderizado com o plate decodificado antes do H.264; a diferença não pode ser atribuída apenas ao codec. Há regressões para FPS racional, PNGs incompatíveis com a fonte, in-point negativo, rampa que esgota a fonte, repetição explícita, textura Blender alterada e disponibilidade falsa do executável.

O teste de indisponibilidade WebGL confirma bloqueio; ele não simula um render 3D bem-sucedido. Essas provas sustentam execução técnica e integridade. Julgamento editorial, fidelidade a uma referência específica, audição e aprovação visual permanecem etapas próprias do projeto.
