# Cadência de referências

Use `python -m visual_fidelity reference-cadence` antes de fechar a montagem.
O mapa guarda cortes candidatos, batidas, primeiros tempos de compasso, acentos
de áudio e movimento entre quadros por região. A montagem usa uma correspondência
explícita entre cortes ou marcos da referência e quadros da timeline editável.

## Instalação dos modelos

O fluxo base continua usando `requirements.txt`. Para inferência, instale um trio
compatível de PyTorch, TorchVision e TorchAudio. A configuração Linux CPU
validada foi PyTorch 2.6.0, TorchVision 0.21.0 e TorchAudio 2.6.0, com Python 3.12.

```sh
python -m pip install torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 \
  --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r visual_fidelity/requirements.txt beat-this==1.1.0
```

- [Beat This!](https://github.com/CPJKU/beat_this) usa o checkpoint `final0` por padrão.
  Em execução sem rede, forneça o arquivo em `--beat-checkpoint`.
- [TransNetV2](https://github.com/soCzech/TransNetV2/tree/master/inference-pytorch)
  requer `transnetv2_pytorch.py` e o checkpoint convertido pelos scripts oficiais.
  Os dois caminhos são explícitos. O teste usou a implementação oficial e um
  checkpoint convertido distribuído pelo espelho Sn4kehead no Hugging Face.
- [TorchVision RAFT Small](https://docs.pytorch.org/vision/main/models/raft.html)
  usa `C_T_V2`. Forneça `--raft-weights` para execução sem rede.

Guarde os pesos fora do Git. O mapa registra os hashes dos arquivos fornecidos.
Se não houver modelos, rode `--baseline` explicitamente. Ele usa fluxo de
Farnebäck e mudanças de pixel, além de transientes e pulsação estimada. Sua
pulsação hipotética não é disponibilizada como grade de batidas para retiming.

## Análise e montagem

```sh
python -m visual_fidelity reference-cadence analyze reference.mp4 reference-cadence.json \
  --transnet-code models/transnetv2_pytorch.py \
  --transnet-weights models/transnetv2-pytorch-weights.pth \
  --beat-checkpoint models/beat_this-final0.ckpt --raft-weights models/raft-small.pth \
  --markers markers.json --regions regions.json

python -m visual_fidelity reference-cadence apply timeline.json reference-cadence.json \
  anchors.json timeline-retimed.json --render output.mp4
```

`markers.json` associa nomes a índices de quadro revisados, começando em zero.
`regions.json` associa nomes a caixas normalizadas `[x, y, largura, altura]`.
Use vídeo CFR com início no timestamp zero e informe `--rotation 90` se o
raster precisar de rotação manual anti-horária. Para áudio separado, passe
`--soundtrack`, `--audio-start` e `--audio-speed` conforme o render.
Salve a decupagem e as decisões de escolha dos candidatos junto do projeto.

```json
[
  {"template_frame": 36, "reference_cut": 42},
  {"template_frame": 75, "marker": "inicio_da_mascara"}
]
```

A projeção padrão preserva os tempos da referência. Use com a mesma trilha
alinhada ao vídeo ou com uma decisão editorial explícita sobre o novo áudio.
`--reference-start-frame` permite usar um trecho da referência. Informe
`--mask-track` para transferir amostras geométricas revisadas neste mesmo
relógio. A entrada é uma lista de `{"frame": 42, "mask": {...}}` no formato
de `geometric_replay`, sem fotografias recuperadas da referência. Para outra
música, analise o áudio alvo no relógio real da saída e passe seu mapa em
`--target-map`. O motor preserva a fração do intervalo entre batidas de cada
marco, respeita o deslocamento explícito `--beat-offset` e rejeita colisões.
Use âncoras em ordem crescente. Mantenha a timeline compilada no diretório
da original para resolver os mesmos caminhos de assets.

O retiming carrega recortes, quadros de origem, tintas e máscaras juntos.
O relatório registra quantos quadros da montagem base foram repetidos ou
pulados. Quando um recorte exige geometria própria, a entrada medida mantém a
trajetória separada dos assets. RAFT estima deslocamento visível por região.
Uma transição de montagem exige checagem editorial antes de usar essa medida
como movimento de uma única camada. O mapa evita estimar fluxo através dos
cortes detectados e guarda os candidatos para confirmação. Preserve o plano
de assets do projeto e confirme a montagem no MP4 com áudio.

## Validação no caso 329796

Rodamos os três modelos na referência completa, com 427 quadros a 30 fps.
O trecho técnico de 216 a 335 combinou quatro cortes selecionados do detector
com sete marcos revisados. A montagem de quatro segundos reproduziu onze
limites editoriais e aplicou 93 quadros de máscaras geométricas medidas.
A visualização usa o bruto e as imagens existentes da aplicação anterior,
com os dois lados em um mesmo relógio. A prévia avalia cadência e geometria.
Não constitui nova aprovação de aparência, escolha de assets ou música.
