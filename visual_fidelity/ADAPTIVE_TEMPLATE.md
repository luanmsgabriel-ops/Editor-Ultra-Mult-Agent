# Aplicação de estilo orientada pelo bruto

Use este fluxo ao receber um novo vídeo com pedido para usar a Clara PT2.
A timeline aprovada fica como referência de acabamento. O perfil de estilo
guarda cor, famílias tipográficas e entrada dos gráficos. Posições, tempos
e conteúdo são decididos para o bruto do projeto.

## Analisar e preparar

Use MediaPipe com Pose Landmarker e Gesture Recognizer, FFmpeg e as
dependências de `visual_fidelity/requirements.txt`. Para transcrição local
use Faster Whisper com um modelo disponível no ambiente ou forneça
um JSON com segmentos e palavras cronometradas.

```sh
python -m visual_fidelity adaptive-template bruto.mp4 \
  examples/style_profiles/clara.json planejamento \
  --transcript fala.json --pose-model pose.task --hand-model gesture.task \
  --condensed Anton.ttf --script GreatVibes-Regular.ttf
```

O comando analisa os cortes e o enquadramento, mede pontos de rosto,
ombros, pés e mãos e fixa o relógio pelo bruto. Um close sem pés visíveis
é registrado como plano parcial e conserva a filmagem. Pés visíveis por
si só são insuficientes para provar contato ou geometria. Os gráficos
usam pequenos espaços livres por plano. O motor exclui quadros em que
o rosto ou uma mão intersecta o envelope da animação. Um gesto medido
pode marcar a entrada do gráfico após o início das palavras já
pronunciadas. O limite padrão é 320 ms depois do início do termo.

Para reproduzir o plano, adicione `--render saida.mp4`. O fluxo compõe
sobre o bruto e copia o áudio original. `analysis.json` registra a origem,
a composição, as mãos visíveis, os gestos usados, o trecho de fala que
sustenta cada gráfico e os quadros em que a posição foi viável.

## Selecionar imagens e ícones úteis

Leia a transcrição e selecione conceitos que ajudam a compreender a cena.
O vocabulário interno cobre algumas expressões de viagem, interrupção,
duração, contagem e status. Quantidades vêm da fala. Os ícones
correspondentes são desenhados pelo motor com alpha real. Para outros
temas, produza `--cues` com a decupagem semântica do bruto. Um exemplo
de entrada:

```json
[
  {
    "title": "FALHA DE COMUNICAÇÃO",
    "script": "controle aéreo",
    "evidence": "falha nos sistemas de comunicação",
    "icon": "signal"
  }
]
```

A evidência deve ocorrer na transcrição. Em casos em que um ícone novo seja
necessário, desenhe ou gere o PNG por uma ferramenta de desenho/imagem e
use `icon_asset` e `provenance`, com caminhos relativos ao arquivo de
cues. O JSON de proveniência inclui `concept`, `evidence`, origem e, se
gerado, prompt e versão. Se texto resolver o trecho, omita o ícone.
A confirmação de relevância de uma arte externa continua sendo editorial.

## Colocação espacial

Para gráficos integrados ao ambiente, um cue pode declarar
`anchor.mode: planar` ou `world` com a evidência espacial e os dados
aceitos por `anchor render`, como quad rastreado, poses de câmera ou
projeção Blender. O compositor usa esses dados e confere o mesmo espaço
protegido de rosto e mão. A visibilidade de uma pose corporal é evidência
de enquadramento e gesto. A profundidade métrica e a posição de um plano
no cômodo dependem da solução espacial. Quando ela falta, mantenha o
bruto e aplique o estilo em espaço de tela. Revise o resultado em
movimento, com atenção ao rosto e às mãos durante a entrada do gráfico.
