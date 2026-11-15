# Fidelidade visual por referência

O motor mede tipografia no frame, aceita wordmarks vetoriais, renderiza produtos em 3D e insere uma fotografia ou um render RGBA na timeline. Mantém fontes, fotos, perfis extraídos, texturas e filmagens no projeto local. O piloto Origins testa a troca dos materiais preservando o monograma e a cadência dos cortes.

## Instalação

Python 3.11+, FFmpeg com libx264 e `python -m pip install -r visual_fidelity/requirements.txt`. Para ranquear fontes, Pillow deve ter RAQM/HarfBuzz. Para o render de produto, Blender 4.3+ no PATH. Para importar SVG no piloto, Inkscape no PATH. Servidores ou Windows sem as fontes DejaVu nos caminhos padrão podem configurar as constantes FONT e MONO em origins/scenes.py.

## Tipografia e marca

O ranking renderiza a palavra de referência usando HarfBuzz via RAQM. Compara contorno, distribuição horizontal e largura. FontTools fornece metadados e eixos variáveis. Use um recorte de uma linha e fontes candidatas já disponíveis ou licenciadas. No caso de arte desenhada sob medida, prefira o SVG de origem e use o modo trace em um recorte plano quando só houver uma imagem.

```sh
python -m visual_fidelity typography rank quadro.png --crop 310 848 595 881 \
  --text 'Origins Of is a home' --font /assets/Satoshi-Medium.otf \
  --font /assets/OutraFonte.ttf --output out/fontes.json --preview out/fontes.png

python -m visual_fidelity typography trace wordmark.png \
  --crop 0 0 1024 300 --output out/wordmark.svg
```

Para Origins, o [estúdio original](https://www.slsh.studio/works/origins-of) documenta Satoshi nos textos e um wordmark desenhado para a marca. A [família Satoshi](https://www.fontshare.com/fonts/satoshi) é uma entrada local do render. O modo trace preserva os vazios das letras. Ele estima somente o desenho visível.

## Produto

```sh
python -m visual_fidelity cap --output out/bone.png --scene out/bone.blend \
  --logo /assets/monograma.png --base-color /assets/tecido-color.png \
  --normal /assets/tecido-normal.png --roughness /assets/tecido-roughness.png

python -m visual_fidelity reconstruct colmap /assets/views out/colmap --gpu --dense
python -m visual_fidelity reconstruct trellis /assets/bone.png out/bone.glb \
  --python /ambientes/trellis2/bin/python

python -m visual_fidelity asset out/bone.glb --output out/bone-asset.png --yaw 12 --pitch 14
```

O boné usa malha, costura, trama e câmera configuradas no Blender/Cycles. Os mapas externos são opcionais. O logo PNG pode ser aplicado à superfície no Blender. O comando asset lê GLB, glTF ou malha PLY com faces. A placa RGBA também pode vir de uma foto recortada e posicionada na tela vertical do plano final.

COLMAP precisa de fotos nítidas, sobrepostas, com múltiplos ângulos e captura consistente. Sem `--dense`, o provedor retorna modelos esparsos. A opção densa usa uma instalação COLMAP com CUDA e produz `dense/mesh.ply`, que ainda pode precisar de material e acabamento. TRELLIS.2 roda no ambiente oficial instalado separadamente e gera um GLB texturizado. Provedores 3D opcionais podem exigir GPU, modelos e um ajuste posterior de escala, câmera e textura.

## Montagem e verificação

```sh
python -m visual_fidelity origins out/origins --reference /projeto/origins.mp4 \
  --font /assets/Satoshi-Medium.otf --wordmark out/wordmark.svg \
  --cap-plate out/bone.png --cap-logo baked

python -m visual_fidelity measure /projeto/origins.mp4 out/origins/motion.mp4
```

A grade, a posição do monograma, os cortes de 30 fps e os sons sintetizados do piloto usam `origins/timeline.json`. O parâmetro `--reference` extrai apenas o monograma dessa referência conhecida no quadro calibrado. Para repetir usando um perfil local, passe `--mark-profile`. Use `--cap-logo baked` se o PNG já contiver o logo, ou `overlay` se o motor for aplicar o monograma. Os casos que omitem a placa externa ou wordmark usam a versão procedural ou texto editável como alternativas. O comando de medida compara 28 cortes e seis amostras locais do monograma Origins. Para outra referência, comece pela decupagem e pelos comandos genéricos de tipografia e produto, depois calibre a timeline e as regiões de medição correspondentes.

## Aplicar texto e efeitos a outro vídeo

Use o mesmo plano criativo em dois brutos para calcular posições novas em cada plano. O motor encaixa tanto texto editável quanto uma arte PNG com transparência. O JSON de relatório local guarda cortes, posições, cor, quadros ausentes e motivos para revisão.

```sh
python -m visual_fidelity anchor render bruto.mp4 out/editado.mp4 \
  --plan examples/ancoras-visuais.json --font /assets/Roboto.ttf

python -m visual_fidelity anchor render bruto.mp4 out/editado.mp4 \
  --transcript /projeto/timeline-transcrita.json --font /assets/Roboto.ttf \
  --ocr-language por
```

O modo de transcrição lê `{"segments":[{"start":0.2,"end":1.5,"text":"frase"}]}`. A transcrição vem do fluxo de edição. Use o plano explícito para aplicar apenas palavras-chave e efeitos selecionados. Com `--ocr-language por`, o Tesseract local procura texto já embutido, protege caixas detectadas e pula a camada se a mesma frase aparecer nas amostras do plano. Instale o idioma desejado antes de ativar. Texto inclinado, muito pequeno ou encoberto pode exigir proteção manual.

| Modo | O que o editor fornece | O que o motor calcula |
|---|---|---|
| `screen` | Texto ou ativo, tempo, tamanho e, se necessário, regiões protegidas | Escolhe posição estável por plano, evitando rostos e áreas protegidas e avaliando contraste, bordas e movimento. Encolhe se necessário e suprime a camada se persistir a colisão. |
| `planar` | Quatro cantos do alvo no primeiro quadro do intervalo | OpenCV rastreia pontos e estima a homografia. O corte ou a perda de trajetória encerra a aplicação até que haja uma nova âncora. |
| `world` | Quatro pontos no espaço e câmera resolvida, ou projeções exportadas pelo Blender | Projeta e encaixa a camada no plano do objeto por quadro. Projeções ausentes ou fora da vista são registradas ou descartadas. |

Os intervalos usam `start/end` em segundos ou `frames: [início, fim]`, com fim exclusivo. O render conforma o vídeo ao FPS pedido, 30 por padrão. As posições são normalizadas, origem no canto superior esquerdo. O modo de tela aceita `protected` como lista de caixas [x0,y0,x1,y1] normalizadas, ou mapa de caixas por índice de quadro. A detecção de rosto usa um modelo local opcional, por exemplo o [YuNet do OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) em `VISUAL_FIDELITY_FACE_MODEL=/assets/face_detection_yunet_2023mar.onnx`. Caixas de proteção também funcionam sem detector. Para ocultar parte de um efeito atrás da pessoa ou objeto, passe `occlusion` com uma pasta de máscaras em cinza branco = encoberto, nomeadas `000000.png`, etc., usando o índice conformado. As máscaras vêm de segmentação ou rotoscopia e são aplicadas na composição.

Para reaproveitar a trajetória real de um título, extraia uma curva por letra num trecho isolado e de alto contraste. A camada seguinte pode trocar o texto e retimar o perfil à nova duração. Tanto a posição quanto o espaço reservado são recalculados pelo modo de âncora.

```sh
python -m visual_fidelity glyph-profile referencia.mp4 /projeto/curva.json \
  --text conteúdo --font /assets/Roboto.ttf --box 310 0 690 250 \
  --frames 278 289 --threshold 188 --min-area 2350
```

No plano, adicione `"glyph_profile":"curva.json"` à camada. O perfil é calibrado para palavras limpas no recorte e não determina a fonte original. O plano também aceita arte em vez de texto, com `"asset":"grafico.png"`, e animações `hold`, `fade`, `slide` e `pop`.

### Tela ou objeto rastreado

Ordem dos cantos: superior esquerdo, superior direito, inferior direito, inferior esquerdo. Exemplo de âncora para a borda de uma tela.

```json
{"mode":"planar","quad":[[0.26,0.32],[0.70,0.30],[0.72,0.67],[0.28,0.69]]}
```

Também é possível dar ao rastreador trajetórias TAPIR via `"tracks":"tracks.npz"` dentro de `anchor`. O NPZ usa `tracks` PT2 (ou 1PT2), `visibility` ou `occlusion` e `expected_dist` do TAPIR, e `image_size:[largura,altura]` ou `coordinates:"normalized"`. Os quadros precisam coincidir com o trecho planar. Para exportar trajetórias com o runner local, instale o [TAPNet](https://github.com/google-deepmind/tapnet), PyTorch e o checkpoint oficial de BootsTAPIR compatível.

```sh
python -m visual_fidelity anchor tapir bruto.mp4 /projeto/tracks.npz \
  --checkpoint /modelos/bootstapir_checkpoint_v2.pt --frames 8 34 \
  --quad .26 .32 .70 .30 .72 .67 .28 .69
```

### Ponto fixo no cenário

Para câmera já resolvida no Blender, crie quatro marcadores de um plano e exporte as projeções.

```sh
python -m visual_fidelity blender-anchors cena.blend /projeto/projecao.json \
  --objects TL TR BR BL --start 1 --end 48 --video-start 0
```

Use `{"mode":"world","projection":"projecao.json"}`. Para COLMAP, use o modelo de texto PINHOLE sem distorção e JSON que mapeia nome de cada imagem para quadro no vídeo. Converta com `python -m visual_fidelity anchor colmap MODELO mapa.json cameras.json`. A âncora usa `{"mode":"world","cameras":"cameras.json","corners_3d":[...quatro pontos XYZ...]}`. As projeções se referem às mesmas imagens pinhole usadas para resolver a câmera. Dê novo intervalo após o corte. O motor não infere qual objeto da cena a direção quer selecionar.

## Âncoras no corpo e órbita

As âncoras corporais acompanham uma pessoa por plano. Use pontos como `head`, `left_shoulder`, `right_elbow`, `body_center`, `left_hip`, `right_knee`, `left_ankle`, `left_foot_index`, `right_wrist`, `right_palm` e `left_index_tip`. Os últimos pontos especializados de mão dependem do modelo complementar. Escolha uma pessoa por ID ou deixe o motor escolher um ID estável por plano. A resolução de identidade é local ao plano. O editor reinicia o vínculo após um corte.

```sh
python -m pip install mediapipe
python -m visual_fidelity anchor render bruto.mp4 out/orbita.mp4 \
  --plan examples/ancoras-corpo.json --font /assets/Roboto.ttf --fps 24 \
  --body-model /modelos/pose_landmarker_lite.task
```

O [MediaPipe Pose Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker) fornece pontos e máscara corporal. A opção `--gesture-model /modelos/gesture_recognizer.task` adiciona mãos detalhadas e gestos. Os modelos ficam no ambiente local. O comando abaixo serve para extrair e revisar pontos e máscaras sem renderizar.

```sh
python -m visual_fidelity body-pose bruto.mp4 /projeto/pose.json \
  --fps 24 --persons 4 --model /modelos/pose_landmarker_lite.task \
  --gesture-model /modelos/gesture_recognizer.task --masks /projeto/mascaras
```

Uma camada pode usar `"anchor":{"mode":"body","pose":"pose.json","landmark":"right_palm","relation":"above"}`. Use `trigger` para disparar a entrada só quando a mão abrir ou quando a articulação se mover. Exemplo: `"trigger":{"gesture":"Open_Palm","side":"right","min_frames":2}`. Para movimento numérico use `"trigger":{"motion":"rise","min_speed":0.3}`, com velocidade em fração de imagem por segundo. `"follow":false` fixa a camada na posição do disparo até o fim do plano ou intervalo. O relatório identifica o quadro do evento e os intervalos sem suporte.

Com `"mode":"orbit"`, o motor usa um ponto do corpo como centro de uma órbita projetada. `layout:"ribbon"` distribui as letras na trajetória e `layout:"label"` gira uma legenda inteira. Ativos PNG com transparência também orbitam como unidade. Os mapas de opacidade permitem que o corpo esconda o trecho de trás. Com o MediaPipe integrado, as máscaras são produzidas automaticamente; para um JSON já extraído, inclua `"masks":"mascaras"` na âncora. Máscaras externas como as do SAM 2 usam o mesmo formato de arquivos. Na ausência de máscara, o motor mostra a parte da frente e registra necessidade de revisão. A órbita usa uma projeção parametrizada e a pose 2D em cada quadro.

### Alternativa 2D com RTMW

```sh
python -m visual_fidelity body-rtmw --fps 24 run bruto.mp4 /projeto/pose.json \
  --detector /modelos/yolox.onnx --pose /modelos/rtmw.onnx
python -m visual_fidelity body-rtmw --fps 24 import predicoes.json /projeto/pose.json \
  --size 720 1280
```

Instale `rtmlib` e `onnxruntime` no ambiente que executa `run`. Use pesos compatíveis de [OpenMMLab RTMW](https://github.com/open-mmlab/mmpose/tree/main/projects/rtmpose). O importador aceita a saída do MMPose WholeBody. Essas rotas fornecem pontos 2D; para gestos classificados e recorte, use MediaPipe ou máscaras locais. Exporte todos os dados no FPS usado na composição.

## Biblioteca de efeitos no Drive

O [catálogo do Editor Ultra](https://drive.google.com/drive/folders/1f3oYF6f1JP1BZVZ2HVkAq7I6I-q-evJC) separa motion, transições, cor/LUTs, efeitos visuais e sons. Cada versão registra como foi feita, quando usar, parâmetros ou código e os ativos necessários.

```sh
python -m visual_fidelity effects analyze referencia.mp4 out/analise.json
python -m visual_fidelity effects register /projeto/efeito/card.json /projeto/catalogo
python -m visual_fidelity effects index /projeto/catalogo out/catalogo.json
python -m visual_fidelity effects suggest out/catalogo.json "produto flash no corte" --kind transicao
```

A análise marca mudanças fortes e inserções claras curtas para revisão. Classifique manualmente o que for lettering, overlay, tratamento de cor, material, gesto ou efeito sonoro. O registro salva hashes dos arquivos e reutiliza uma versão idêntica. A definição e os arquivos de execução pertencem à pasta da categoria e a única versão corrente de cada efeito fica no índice. Ao publicar pelo agente, mantenha versões anteriores no histórico e atualize o JSON/guia com os links reais. O CLI registra localmente. O envio ao Drive usa a conexão autorizada do projeto.

```sh
python -m visual_fidelity presets transition plano-a.mp4 plano-b.mp4 out/match.mp4 \
  --size 720 1280 --fps 30 --anchor-before .42 .55 --anchor-after .54 .44 \
  --target .5 .5 --flash-frames 4

python -m visual_fidelity presets cube out/look.cube --side 17 --contrast 1.26
python -m visual_fidelity presets color bruto-sdr.mp4 out/look.cube out/cor.mp4
python -m visual_fidelity overlay out/textura.mov --mask texto.png --size 720 1280
```

A transição produz a faixa visual e o áudio fica a cargo do plano de montagem. O LUT de demonstração é autoral em SDR. Em referências acabadas, um look pode ser refeito por aproximação visual; dados antes/depois alinhados permitem uma comparação mais fiel da transformação. O overlay aceita uma máscara PNG e exporta MOV com transparência ou MP4 de revisão.

Veja [regras de movimento, auditoria de curvas e captura OBS](MOTION.md). Para som, exporte e catalogue o arquivo próprio separado do mix. Prefira alternativas de som cujo uso esteja documentado e marque cada ataque pela timeline. Registre fonte e método para reconstruir quando só houver o efeito misturado com voz ou música na referência.
