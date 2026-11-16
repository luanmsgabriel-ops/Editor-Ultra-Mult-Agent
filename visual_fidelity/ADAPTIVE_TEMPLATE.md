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

## Tratamento por função narrativa

O perfil Clara ativa `editorial_motion`. Em trechos em que a imagem do
apresentador precisa continuar, o motor revela tipografia sem tarjeta e
pode marcar uma assinatura no gesto. Conceitos com ilustração pertinente,
como falha de comunicação, duração, quantidade ou consulta de voo, podem
virar cenas gráficas próprias de até 2,35 segundos, com transições diagonais
de entrada e saída. A narração continua no mesmo relógio.

A escolha fica em `visual_treatment` no relatório. Cues revisados podem
informar `editorial` como `kinetic_type`, `signature`, `signal`, `clock`,
`metric`, `location` ou `status`. Os tratamentos de tela respeitam a
proteção de rosto e mãos. As cenas gráficas são cortes intencionais, separados
do ambiente real, com perspectiva e profundidade desenhadas. Arte PNG
externa e âncoras planas ou de câmera continuam disponíveis pelo compositor.

## Camadas no bruto

A opção `body_depth` do perfil Clara permite efeitos ligados ao corpo.
Passe `--matte-model rvm_mobilenetv3_fp32.onnx` para calcular alpha recorrente
com ONNX Runtime no mesmo relógio do bruto. Para reaproveitar uma sequência
já calculada, passe `--mattes PASTA`. A pasta inclui `alpha.json` e PNGs
numerados com seis dígitos. A origem e a taxa precisam coincidir.

- A faixa de texto segue os ombros e projeta letras em duas passagens.
  O alpha do sujeito oculta a parte traseira. O rosto e as mãos protegem
  a passagem dianteira. O motor verifica amostras de letras visíveis na
  frente e atrás, além das que ficaram cobertas. Se o quadro não sustenta
  os dois lados, aplica a tipografia de tela.
- O efeito de mão usa os pontos de palma em sequência contínua. O arco
  traseiro respeita o alpha da pessoa. A animação termina quando a mão
  sai do quadro ou a detecção se perde. A narração permanece intacta.

O relatório `depth_effects` registra os intervalos aprovados. Órbita e
arcos são projeções para composição, sem reconstruir o ambiente ou deslocar
a imagem do apresentador.

Para outros assuntos, um cue com `"body_effect": "orbit"` pode propor a
órbita com as palavras do trecho. A opção passa pela mesma validação de
oclusão e espaço visível. `depth_candidates` guarda o resultado dessa
seleção, inclusive casos que voltaram à composição de tela.
