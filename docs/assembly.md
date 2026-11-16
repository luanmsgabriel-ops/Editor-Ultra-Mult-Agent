# Montagem real de múltiplos clipes

`editorial_engine.assembly` liga filmagens reais e retornos de geração a uma sequência codificada por FFmpeg. O diretor determina a ordem, os recortes, as transições e as políticas de imagem e áudio. O executor confere arquivos, aplica essa montagem e mede o resultado. Ele não escolhe uma edição por palavras-chave.

Esta camada produz uma base de vídeo para os renderizadores e para a revisão existentes. Títulos, motion, fala nova e outros itens de pós-produção permanecem pendentes quando ainda não foram executados.

## API pública

```python
from editorial_engine.assembly import (
    validate_assembly, render_assembly, from_generation,
)

checked = validate_assembly(plan, verify_files=True)
receipt = render_assembly(plan, "/absolute/new-output-directory")

assembly = from_generation(
    generation_plan, returned_receipts,
    fps="30/1", width=1080, height=1920,
    fit="reject", fps_policy="reject",
    audio="source", missing_audio="silence",
    transitions={"join-1": "crossfade"},
)
```

`validate_assembly` retorna `video-assembly-validation/1`; não altera o plano. Com `verify_files=True`, confere bytes e mede os streams e os quadros decodificados. Com `False`, o relatório declara `files_verified=False` e serve apenas à validação estrutural e ao cálculo de tempo. `render_assembly` sempre verifica os arquivos reais, inclusive novamente depois da execução.

`from_generation` devolve um plano de montagem selado, pronto para ser conferido e renderizado. O dicionário `returned_receipts` usa o ID de cada clipe como chave e seu recibo de `generation import` como valor. Esta função exige todos os clipes atuais; um retorno parcial ainda pertence ao fluxo de geração.

## Plano `video-assembly/1`

Os exemplos [assembly-cuts.json](../examples/project_flow/assembly-cuts.json) e [assembly-crossfade.json](../examples/project_flow/assembly-crossfade.json) contêm caminhos e hashes ilustrativos. É necessário substituí-los por mídia real; eles não atestam execução.

| Campo | Conteúdo obrigatório |
| --- | --- |
| `schema`, `id`, `revision` | Versão do contrato, identidade da montagem e revisão inteira positiva |
| `sources` | Recursos identificados por `id`, caminho local absoluto e SHA-256 dos bytes |
| `clips` | Ordem final dos trechos, cada um com `id`, `source_id`, `use`, `fit`, `reframe_fps` e `audio` |
| `joins` | Uma junção para cada par adjacente: `from`, `to`, `transition`, `duration_s` |
| `output` | FPS racional, largura, altura e política explícita de áudio |

`use.start_s` é inclusivo e `use.end_s` é exclusivo. Tempos podem ser números ou frações em texto, como `"7007/30000"`. Início e fim devem corresponder a fronteiras de quadros da fonte; a duração utilizada deve caber em um número inteiro de quadros da saída. A conferência aceita apenas a tolerância numérica de representação, sem arredondar um corte editorial arbitrário.

`plan_sha256` é opcional na autoria direta. Quando presente, é o SHA-256 canônico do objeto sem esse campo; a validação bloqueia qualquer mudança sem novo selo. A ponte de geração sempre o inclui. A montagem não pode declarar fontes que não utiliza.

### Imagem, velocidade e encaixe

O plano declara FPS e raster da saída. Todos os clipes conservam sua velocidade de reprodução. Não há loop, reversão, congelamento para completar duração ou alteração automática de duração.

`reframe_fps="reject"` bloqueia fonte com outra cadência. `"resample"` autoriza conversão explícita de FPS, com descarte ou duplicação de amostras de imagem para representar o mesmo intervalo temporal na cadência de saída. Essa conversão fica registrada por clipe. Ela não altera a velocidade da ação.

`fit="reject"` exige dimensões iguais às da saída. `"contain"` mantém a imagem inteira e centraliza com barras pretas quando necessárias. `"cover"` ocupa todo o raster e recorta o excedente nas bordas, também de forma centralizada. O crop de `cover` é uma escolha declarada; o executor não acompanha automaticamente o rosto ou o assunto.

Esta versão exige vídeo CFR, pixels quadrados, início do relógio próximo de zero e rotação de exibição resolvida. A saída H.264 usa dimensões pares e `yuv420p`. Vídeo VFR, rotação, pixels não quadrados ou múltiplas faixas de áudio precisam de conformação explícita anterior. Um recibo da geração que indique essas condições não as corrige por si só.

### Cortes e transições

As transições disponíveis são `cut`, `crossfade`, `fadeblack`, `wipeleft`, `wiperight`, `slideleft` e `slideright`. Uma opção desconhecida bloqueia a montagem. Não existe substituição automática por outra transição.

`cut` tem `duration_s=0`. As demais operações usam sobreposição positiva, alinhada ao FPS da saída, menor que cada um dos clipes envolvidos. Em um clipe intermediário, as sobreposições de entrada e saída não podem consumir regiões conflitantes.

O cálculo é explícito:

```text
quadros finais = soma dos quadros utilizados − soma dos quadros sobrepostos
```

A linha do tempo do recibo registra `start_frame` e `end_frame` de cada clipe, os quadros usados na fonte e seus tempos na saída. O fim é exclusivo. Uma transição ocupa material dos dois clipes; não acrescenta um trecho artificial para conservar uma duração anterior.

### Áudio

`output.audio` declara `mode` (`source` ou `none`), `sample_rate=48000`, `channels=2` e `missing` (`reject` ou `silence`). Cada clipe declara `audio.mode` (`source` ou `silence`) e `gain_db`, entre −60 e 0 dB.

Com `source`, o executor usa a faixa de áudio real da fonte e o mesmo recorte temporal do vídeo. O áudio é convertido explicitamente para estéreo a 48 kHz. Cortes concatenam os trechos; todas as transições com sobreposição usam crossfade de áudio linear. Nesta versão não há escolha separada de curva sonora, faixa externa, isolador de voz, TTS, música nova ou sincronização labial.

`missing="reject"` bloqueia áudio ausente ou que não cubra o trecho solicitado. `"silence"` autoriza silêncio nas partes sem cobertura. `clip.audio.mode="silence"` silencia o clipe inteiro de maneira declarada. `output.audio.mode="none"` produz vídeo sem faixa sonora. O executor não remove pausas e não estica áudio para completar uma tomada.

O relógio PCM usa a posição global de cada fronteira e arredondamento à amostra mais próxima. Isso conserva o total da sequência mesmo quando o FPS é racional e uma fronteira de vídeo cai entre duas amostras de áudio. O recibo guarda os totais esperados e medidos, as medições originais de áudio e um WAV PCM separado. O MP4 recebe AAC; seu preenchimento final de codificação é medido e deve ser inferior a 1024 amostras. Esse preenchimento é registrado, sem mudar o número de quadros do vídeo. Picos acima do limite, deslocamento inesperado ou contagem divergente bloqueiam a saída. Não é aplicado limiter automático.

## Receber clipes da geração

A ponte preserva um snapshot completo do plano de geração, seu hash, os recibos e o mapeamento das transições. Cada fonte da montagem deve continuar correspondendo aos bytes e ao intervalo útil do retorno indicado. A duração final precisa coincidir com `brief.target_duration_s`.

Para uma junção executada na geração, com sobreposição zero, a ligação física é um corte. Junções `post` ou `hybrid` exigem um mapeamento explícito de seus IDs para uma transição suportada. Um nome descritivo de transição no prompt não se transforma em código executável por similaridade textual.

A ponte verifica dependências entre os retornos. Um filho gerado com o quadro de uma versão antiga do pai não pode entrar silenciosamente com um novo resultado desse pai. Para `observed_frame`, exige a mesma seleção de quadro, fronteira compatível com o intervalo útil, observação de janela ou reprodução contínua e decisão editorial `accept`. Essa decisão não é aprovação do usuário. Para extensão nativa, exige a correspondência com o fim real do pai; uma sequência completa devolvida pelo fornecedor precisa de um mapeamento explícito anterior para ser tratada como novo clipe.

Quando `brief.audio_execution="none"`, a chamada deve declarar `audio="none"`. Quando `require_generated_audio=True`, deve declarar `audio="source", missing_audio="reject"`. Assim, a montagem não descarta uma exigência de áudio nem preenche sua ausência com silêncio por padrão.

### Pós-produção pendente

Cada item preservado recebe um ID estável `post:<clip_id>:<post_id>`, a instrução original, o intervalo convertido para o relógio da montagem e o recurso associado, quando declarado. A rota de áudio em pós recebe `audio-post:<clip_id>`, com falas, direção sonora e indicação de sincronismo labial ainda não resolvido. Nenhuma dessas instruções é considerada executada pela montagem.

`pending_post` também pode ser declarado em um plano de montagem direta. Cada registro exige ID único, `kind`, `status="pending"` e `timeline_interval` válido na saída. O coordenador deve conservar a instrução e os recursos necessários para retomar esse trabalho.

Um render com pendências recebe `status="assembled_with_pending_post"`; os demais recebem `"assembled"`. Ambos mantêm `delivery_ready=False` até o fluxo de revisão e entrega do projeto resolver o que falta. Apagar uma pendência de uma montagem vinculada à geração viola o vínculo com o plano original.

## Artefatos e revisão

`render_assembly` exige um diretório de saída que ainda não exista. Trabalha em um diretório temporário, mede o resultado e só então publica localmente o conjunto. Não sobrescreve fontes nem um render anterior. A saída contém:

- `render.mp4`: sequência realmente codificada;
- `audio.wav`: mistura PCM, quando o áudio está habilitado;
- `assembly.json`: plano utilizado;
- `receipt.json`: recibo `video-assembly-result/1`;
- `filter-complex.txt`: grafo concreto executado pelo FFmpeg.

O recibo traz caminho e hash do vídeo, contagem de quadros, duração, linha do tempo, fontes e medições, resultados técnicos, pendências e hash da implementação. `receipt_sha256` é o hash canônico do recibo sem esse próprio campo. `assembly_plan_sha256` identifica a montagem autorada.

`review_plan` é um envelope selado `assembly-review-plan/1`, aceito pela API de revisão existente. Seu `plan_sha256` também aparece no campo homônimo do artefato. Ele identifica os clipes como decisões e vincula a montagem ao objeto revisável. O módulo de montagem não cria estado de revisão, não concede aprovação e não reinicia o orçamento de correções. Em revisões do mesmo projeto, o coordenador conserva o estado anterior, o histórico e os limites.

Decodificar, contar quadros, verificar hashes e medir amostras prova a execução e a coerência técnica. Movimento, fidelidade, cortes percebidos, fala compreensível e áudio ouvido exigem observação própria. O recibo começa com esses aspectos `unverified` e com aprovação do usuário `pending`.

## Erros que exigem uma decisão explícita

| Código | Decisão necessária |
| --- | --- |
| `file_hash_mismatch`, `stale_receipt`, `assembly_stale_dependency` | Reimportar ou revisar a fonte/retorno correspondente, sem reaproveitar a aprovação antiga |
| `assembly_frame_alignment`, `assembly_source_short` | Alterar o intervalo autorado ou fornecer material suficiente |
| `assembly_vfr`, `assembly_origin`, `assembly_raster`, `assembly_audio_tracks` | Conformar a mídia ou escolher a faixa antes da montagem |
| `assembly_fps_mismatch`, `assembly_size_mismatch` | Declarar conversão e encaixe, ou fornecer uma fonte compatível |
| `assembly_audio_missing`, `assembly_audio_short`, `assembly_audio_source` | Fornecer áudio íntegro ou autorizar a política apropriada; gaps internos não são achatados silenciosamente |
| `assembly_transition_map`, `assembly_transition`, `assembly_overlap` | Especificar uma operação suportada e sua sobreposição real |
| `assembly_generation_audio`, `assembly_generation_changed`, `assembly_generation_duration` | Conciliar a montagem com o plano de geração vigente |
| `assembly_render_clock`, `assembly_audio_clock`, `assembly_output_clock`, `assembly_audio_encode` | Investigar o resultado técnico; não há ajuste automático para fazer a contagem passar |
| `assembly_output_exists` | Escolher um novo diretório para preservar o resultado anterior |

Os testes focados de `tests/test_assembly.py` executam FFmpeg sobre cores e tons sintéticos: cortes e trims, sobreposição visual/sonora, mistura com fonte sem áudio, contain/cover, conversão declarada de FPS, três clipes com junções combinadas a 30000/1001, dependências antigas e vínculos de revisão. Essa prova técnica não representa avaliação estética de um filme real.
