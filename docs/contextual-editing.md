# Direção contextual da edição

O caminho para escolher intervenções pela intenção do trecho é `python -m visual_fidelity contextual-edit`. Ele prepara evidências do bruto, recebe a direção explícita de uma pessoa ou de um modelo configurado, concilia propostas, compila efeitos implementados e registra a revisão do arquivo produzido.

O motor não configura um diretor automaticamente. `prepare` extrai fatos técnicos; `request` prepara o pedido; a interpretação e as propostas chegam em `direction.json`. O host pode escrever esse arquivo depois de assistir à fonte e examinar as evidências. A chamada HTTP opcional de `direct` exige endpoint e modelo explícitos. Não existe fallback de decisão por regex, palavras da transcrição ou nomes de arquivos.

## Escopo desta implementação

O adaptador nativo trabalha com **uma fonte CFR, com timestamp inicial zero, sem remontagem, retime ou mudança da grade de quadros**. Os intervalos de análise e decisão usam `clock: "source"`; a revisão usa `clock: "output"`. A coincidência atual entre esses relógios não autoriza transportar timecodes de outra montagem.

As primitivas existentes de `visual_fidelity` continuam responsáveis pela composição. Os módulos de direção organizam contratos, recursos e revisão; os executores locais de [motion](motion-integration.md) acrescentam cenas e tipografia animadas como recursos verificáveis. Essa incorporação não instala tracking, segmentação, reconstrução de câmera ou modelos generativos. Capacidade ausente, desconhecida, incompleta ou vinculada a outra fonte bloqueia a intervenção. Uma alternativa exige proposta e justificativa próprias. O executor não troca uma órbita por cartão nem uma projeção por camada de tela silenciosamente.

A API do provider está implementada, mas **não foi exercitada com um modelo externo ao vivo nesta entrega**. O CLAP estava indisponível no runtime verificado, e sua inferência com pesos reais não foi exercitada. Testes de contrato e renders sintéticos confirmam o comportamento técnico exercitado, sem demonstrar julgamento semântico de um modelo ou aprovação estética de um vídeo real.

## Quem decide e quem verifica

| Etapa | Responsável | Registro |
| --- | --- | --- |
| Inventário e decupagem | Decupagem, com observação da fonte | Fontes, SHA-256, FPS racional, quadros, evidências e limitações |
| Intenção e alternativas | Direção editorial, reunindo propostas de motion e som | Observações, objetivos dos eventos, oportunidades, candidatos e razões |
| Elegibilidade e conciliação | `planner.py` | Escolhas, descartes, conflitos, repetição e oportunidades não atendidas |
| Execução | `native.py` e renderizadores existentes | Arquivo, hash, recursos importados, relógio e checagens técnicas |
| Revisão | QC sobre o arquivo efetivamente produzido | Cobertura técnica, movimento, áudio, direção e resposta do usuário |
| Correção | Editor responsável pelo plano | Patch localizado, nova versão e invalidação da revisão anterior |

Os agentes entregam propostas independentes. Um responsável concilia o plano versionado. Ter vários agentes não substitui um contrato compartilhado nem comprova que alguém assistiu à exportação.

## Arquivos e identidade

Os exemplos abaixo partem da raiz do repositório. Substitua os caminhos pelos materiais reais do projeto. Mantenha mídia, credenciais, catálogo privado e saídas fora do Git. Use uma pasta de análise vazia e nomes novos para cada saída: o fluxo preserva originais e não sobrescreve seus JSONs ou renders.

| Arquivo | Conteúdo |
| --- | --- |
| `analise-v1/analysis.json` | Fonte, evidências, eventos, capacidades e recibos técnicos |
| `analise-v1/catalog.json` | Manifestos dos adaptadores nativos |
| `request-v1.json` | Brief, referência, evidências disponíveis, imagens amostradas e contrato da resposta |
| `direction-v1.json` | Direção explicitamente fornecida pelo host ou provider |
| `bundle-v1.json` | Análise anotada, catálogo e plano selado |
| `render-v1.artifact.json` | Identidade do MP4, decisões executadas, recursos e checagens |
| `review-v1-*.json` | Estado persistente de revisão e histórico de relatórios |
| `patch-v2.json` | Substituições localizadas contra uma versão exata |
| `motion-v1/motion-layer.json` | Sequência RGBA, FPS local, hashes por quadro e origem do renderer |
| `motion-v1/inventory.json` | Asset `kind: "motion"` consumível por `prepare --assets` |

Um SHA-256 identifica bytes. Um recibo registra a origem e o método de uma verificação. Nenhum dos dois, isoladamente, comprova que uma observação está correta, que uma máscara recorta bem o sujeito ou que um efeito combina com o trecho.

## 1. Preparar a fonte e os recursos

Preparação mínima:

```bash
python -m visual_fidelity contextual-edit prepare \
  midia/bruto.mp4 trabalho/analise-v1 \
  --sample-every-s 0.5
```

O comando salva `analysis.json`, `catalog.json`, quadros amostrados e recibos. O estado semântico inicial é `awaiting_direction`. Cortes por diferença de pixels e gestos medidos são candidatos a examinar. As amostras recebem inicialmente a indicação de que ainda não foram interpretadas.

Para uma preparação com recursos previamente produzidos e conferidos, use uma nova pasta:

```bash
python -m visual_fidelity contextual-edit prepare \
  midia/bruto.mp4 trabalho/analise-com-recursos-v1 \
  --transcript midia/transcricao.json \
  --pose midia/pose.json \
  --mattes midia/mattes \
  --protection midia/protecao.json \
  --projection midia/projecao.json \
  --assets midia/inventario-assets.json \
  --sample-every-s 0.25
```

Todas as opções de recursos são opcionais; inclua apenas as que existem. Omitir um recurso mantém indisponíveis os efeitos que dependem dele. `prepare` não gera uma transcrição, uma pose ou uma câmera fictícias para completar o plano. Nos comandos seguintes, substitua `analise-v1` pelo diretório da preparação escolhida; efeitos dependentes de recursos precisam da análise que contém esses recursos.

Os dados temporais devem identificar a mesma fonte e seu relógio. A transcrição usa segmentos ordenados com `start`, `end` e `text`, além de `source_sha256`; explicite `clock: "source"`. Pose, proteção, máscaras e projeção também precisam conservar FPS e grade de quadros. A preparação rejeita entradas que declarem outro relógio. Uma máscara em grade reduzida exige resolução declarada e normalização registrada, conservando os originais e hashes dos arquivos efetivamente usados.

O inventário distingue imagem, motion e SFX. Para imagem, registre `id`, `kind: "image"`, `path` e metadados curatoriais como descrição, funções editoriais, origem e licença. Para motion, `kind: "motion"` recebe em `path` o manifesto `motion-layer/1` de uma sequência renderizada, com PNGs RGBA straight, FPS racional, frame count, raster e hashes. Para som, `kind: "sfx"` recebe em `asset` o registro verificado do índice de áudio. IDs e nomes de arquivo servem para identidade; a adequação editorial precisa de curadoria, audição, preview ou outra observação explícita do conteúdo.

A preparação mínima, sem tracking, proteção ou assets, pode ser suficiente para decupagem e uma decisão motivada de preservação. Ela não torna automaticamente executáveis os efeitos do catálogo.

### Produzir e importar uma camada de motion

Use o [fluxo de motion](motion-integration.md) quando a direção precisar de animação autorada, tipografia extrudada, grupos independentes, uma transição ou cena gráfica. Consulte `motion probe` antes de escolher o backend. OpenKatana, Motion Lab legado MIT e MOTNGRFX têm escopos próprios; receita ainda não renderizada não constitui capacidade pronta.

```bash
python -m editorial_engine motion render motionlab \
  examples/motion_integration/motionlab-2d.json trabalho/motion-v1 \
  --samples 4 --asset-id motion-explicacao

python -m visual_fidelity contextual-edit prepare \
  midia/bruto.mp4 trabalho/analise-motion-v1 \
  --assets trabalho/motion-v1/inventory.json \
  --protection midia/protecao.json \
  --mattes midia/mattes
```

Configure FPS e duração da receita a partir do bruto antes desse render. O inventário gerado tem a forma abaixo; os arquivos referidos precisam existir:

```json
{
  "assets": [{
    "id": "motion-explicacao",
    "kind": "motion",
    "path": "/projeto/exports/motion-v1/motion-layer.json",
    "description": "Descrição curatorial do conteúdo e da função proposta"
  }]
}
```

`prepare` confere todos os quadros, alpha, hashes e FPS. Se existir `source_binding`, confere também a identidade e o relógio da fonte à qual a sequência pertence. O frame inicial da decisão recebe o frame local indicado por `asset_start_frame`; os demais seguem um a um até o fim do intervalo. Não há repetição, congelamento, reordenação ou retime para completar uma animação curta.

`native.motion_layer` requer `motion_asset` e proteção; `native.motion_behind` requer também `subject_mask`. O alpha é transformado pelo mesmo caminho usado na renderização, preservando proporção e verificando proteção e visibilidade. Um piso positivo de visibilidade por letra exige mapas de IDs dos glifos; ele não pode ser comprovado apenas pelo alpha global. Falha de máscara ou cobertura exige correção ou nova proposta explícita.

Motion Lab e MOTNGRFX podem produzir volume em câmera sintética por CPU. Isso demonstra uma cena 3D autorada, sem resolver a câmera da filmagem nem demonstrar fixação no chão. A aplicação no espaço real continua sujeita às evidências de tracking, plano, profundidade e câmera do bruto. MP4s achatados de inspeção não substituem os PNGs RGBA da camada.

## 2. Preparar o pedido de direção

```bash
python -m visual_fidelity contextual-edit request \
  trabalho/analise-v1/analysis.json \
  trabalho/analise-v1/catalog.json \
  --brief-file midia/brief.txt \
  --reference-profile midia/perfil-referencia.json \
  --max-frames 24 \
  --output trabalho/request-v1.json
```

Use `--brief "texto do objetivo"` no lugar de `--brief-file` quando for conveniente. `--reference-profile` é opcional. O perfil entra como contexto fornecido: não dispara análise automática da referência. Registre nele a gramática observada — função dos efeitos, ritmo, hierarquia, movimentos e relações entre imagem e som — com suas evidências e limitações.

As posições, tracking, fala e espaços disponíveis pertencem ao vídeo atual. Reutilizar o perfil da referência não transplanta suas coordenadas, máscaras ou marcos de fala para outra pessoa. Quando for necessário reconstruir uma referência fixa, conserve os contratos específicos dos pacotes de replay existentes.

O pedido informa quais imagens foram realmente incluídas. `--max-frames` aceita de 2 a 96 amostras; o padrão é 24. `--no-images` prepara somente o conteúdo textual e estrutural. Uma resposta do provider não pode anotar um frame que não recebeu. Amostras isoladas não provam movimento contínuo, e transcrição não comprova audição.

O pedido inclui também previews de até 12 imagens e folhas amostradas de até 8 camadas de motion do inventário, identificadas como assets e separadas dos quadros da fonte. Prepare uma seleção de candidatos antes de enviá-los. O provider só pode selecionar uma imagem cujo preview recebeu; descrição técnica, ID e SHA não substituem a observação do asset. As cartas `motion_guidance` apresentam opções e requisitos, sem impor estilo nem escolher pela presença de palavras. Folhas de motion mostram apenas os frames identificados, sem comprovar reprodução contínua ou legibilidade durante toda a animação.

Quando o inventário inclui candidatos sonoros de motion, o pedido conserva sua relação com o hash da receita renderizada e seu clock local. Eles não são áudios ou ataques já aprovados. Busca de som deve entregar candidatos com semântica e proveniência próprias, e a âncora interna precisa estar revisada antes do render final.

`--lessons caminho.json` aceita uma lista de lições com `status: "user_approved"` e confirmação explícita. Registre a confirmação verdadeira; uma observação do agente não vira aprovação do usuário. As lições entram como contexto editorial, sem substituir evidência da fonte atual.

## 3. Fornecer a direção

### Direção escrita pelo host

O host pode assistir ao bruto, abrir as evidências e escrever `direction-v1.json` seguindo `response_contract` dentro do pedido. Registre a autoria real: `kind: "human"` para anotação humana e `kind: "model"` para julgamento de modelo, com `actor` e `method` correspondentes ao trabalho executado.

O documento contém:

- `schema_version: "1.0"` e `provenance`.
- `evidence_annotations`: IDs de evidências visuais existentes e observações do conteúdo realmente examinado.
- `event_annotations`: intenção e oportunidades de **todos** os eventos, inclusive os preservados.
- `proposals`: `schema_version: "1.0"` e a lista `candidates`.
- `limitations`: o que permaneceu sem observação, indisponível ou incerto.

Cada candidato referencia `event_id`, `effect_id`, `source_id`, `source_sha256`, `clock`, `interval` e `evidence_ids`. Inclui `why`, `scores`, `score_provenance`, `anchor`, `bindings`, `params`, `addresses` e a região quando houver composição visual. Os intervalos são não vazios e semiabertos: `[start_s, end_s)`.

As notas `intent_fit`, `visual_fit`, `style_fit` e `timing_fit` ficam entre zero e um e representam julgamento declarado. Elas ajudam a comparar alternativas elegíveis; não comprovam qualidade e nunca superam requisitos ausentes.

Uma proposta `preserve` usa o intervalo completo do evento, explica a preservação e não leva parâmetros de render nem atende artificialmente a oportunidades de efeito. Ela entra como escolha explícita quando nenhuma intervenção é selecionada para o evento. Não existe preservação implícita para esconder evento sem direção.

### Provider opcional, configurado explicitamente

O comando abaixo é um exemplo de configuração; substitua endpoint e modelo pelos serviços efetivamente escolhidos. Ele envia brief, evidências e amostras preparadas ao endpoint indicado.

```bash
python -m visual_fidelity contextual-edit direct \
  trabalho/request-v1.json \
  --endpoint https://SEU-ENDPOINT/v1/chat/completions \
  --model NOME_DO_MODELO \
  --api-key-env EDITORIAL_API_KEY \
  --output trabalho/direction-v1.json
```

O valor da credencial vem da variável de ambiente e não é salvo nos artefatos. O endpoint deve ser HTTPS ou HTTP local. A interface espera resposta compatível com chat completions em JSON. Preparar um pedido não chama esse endpoint; executar `direct` é a etapa que solicita inferência. Falha de rede, de credencial ou de formato bloqueia a etapa sem criar propostas por heurística.

## 4. Conciliar e validar o plano

```bash
python -m visual_fidelity contextual-edit plan \
  trabalho/analise-v1/analysis.json \
  trabalho/analise-v1/catalog.json \
  trabalho/direction-v1.json \
  --plan-id campanha-v1 \
  --output trabalho/bundle-v1.json

python -m visual_fidelity contextual-edit validate trabalho/bundle-v1.json
```

O plano verifica a evidência antes de pontuar. Propostas inválidas ficam em `discarded`, com estágio e motivo. O seletor compara alternativas, conflitos de canal/região, ocupação simultânea e repetição. Áudio e visual complementares podem coexistir no mesmo evento.

Inspecione os campos que explicam a decisão:

| Campo do plano | Leitura operacional |
| --- | --- |
| `decisions` | Intervenções e preservações escolhidas, com proposta e operação compilável |
| `discarded` | Alternativas recusadas e requisitos ou escolhas que as bloquearam |
| `planned_opportunities` | Oportunidades cobertas por uma decisão planejada, ainda sem prova do render |
| `missed_opportunities` | Oportunidades declaradas e não atendidas, inclusive em eventos preservados |
| `unresolved_events` | Eventos sem decisão válida; impedem execução |
| `validation` | Separação entre contrato, integridade de arquivos, execução e revisão pendente |

`addresses` precisa citar uma oportunidade daquele evento, e a função precisa existir no manifesto do efeito. Citar um ID não basta. A inexistência de oportunidades no plano também não demonstra que o vídeo foi analisado suficientemente: a direção responde pela cobertura da decupagem.

A política pode ser fornecida por `--policy arquivo.json`. Os controles atuais são `weights`, `minimum_score`, `opportunity_bonus`, `repetition_penalty`, `max_effect_repetitions`, `max_visual_layers` e `max_audio_layers`. Registre o motivo editorial da alteração. Maximizar a quantidade de efeitos e minimizar toda intervenção não são metas do seletor.

## Catálogo dos adaptadores nativos

`contextual-edit catalog --output caminho.json` exporta os mesmos manifestos. O estado `ready` significa que há um adaptador implementado; a disponibilidade para uma fonte ainda exige recibos e dependências válidos no intervalo escolhido.

| `effect_id` | Operação | Recursos e limites principais |
| --- | --- | --- |
| `native.kinetic_type` | Tipografia cinética | Título, fontes reais, região de tela e regiões protegidas; legenda acessível continua sendo uma responsabilidade própria |
| `native.overlay` | Imagem em camada de tela | Asset verificado, região protegida e envelope da animação reservado |
| `native.behind_subject` | Imagem com oclusão pelo sujeito | Asset, máscara temporal e proteção; a máscara precisa ser revisada no render |
| `native.motion_layer` | Sequência animada em camada de tela | `motion_asset`, proteção, FPS igual ao bruto e cobertura integral; `asset_start_frame` escolhe o início local |
| `native.motion_behind` | Sequência animada com oclusão pelo sujeito | `motion_asset`, máscara temporal e proteção; controles `min_visible_fraction` e `min_glyph_visible_fraction`, este último condicionado a IDs reais dos glifos |
| `native.projected_asset` | Imagem projetada em plano | Quads medidos e contínuos, asset, região e proteção; não resolve volume ou câmera 3D |
| `native.body_orbit` | Tipografia orbital em torno do corpo | Pose contínua, máscara, fontes e evidência de passagens dianteira/traseira; reserva o quadro inteiro no seu canal |
| `native.hand_accent` | Gráfico acompanhando a mão | Tracking da palma no lado pedido, máscara e proteção; reserva o quadro inteiro no seu canal |
| `native.sfx` | Spot e mix de um som indexado | Asset de áudio, âncora interna revisada, alvo em amostras e reserva do pré-roll/cauda audíveis |

Os manifestos fixam tipos de parâmetros, funções editoriais, bindings e âncoras permitidas. O planejador acrescenta obrigatoriamente a capacidade `renderer:native:<operação>`. Pose, máscara, projeção ou instalação isolada não certificam adequação editorial. A execução confere novamente recursos, relógio, implementação e geometria; uma seleção tecnicamente pré-elegível ainda pode falhar em uma condição dependente dos parâmetros.

## 5. Renderizar a versão escolhida

```bash
python -m visual_fidelity contextual-edit render \
  trabalho/bundle-v1.json \
  --font midia/fontes/condensada.ttf \
  --script-font midia/fontes/cursiva.ttf \
  --style midia/estilo.json \
  --output trabalho/render-v1.mp4 \
  --artifact trabalho/render-v1.artifact.json
```

Fontes são necessárias quando houver tipografia. `--script-font` pode ser omitido para usar a mesma fonte de `--font`. `--style` é opcional e usa `paper` e `ink` como listas de três inteiros RGB. Sem `--artifact`, o recibo será salvo como `render-v1.mp4.artifact.json`.

O adapter bloqueia planos não executáveis e recursos alterados. Conferências do render incluem decodificação, FPS, contagem de quadros e integridade da fonte. O recibo registra as decisões compiladas e permanece com revisão perceptiva `unverified` e aprovação `pending`.

Intervenções nativas exportam MP4. A preservação integral por cópia de bytes conserva a extensão da fonte. A composição ordena fundo com oclusão, superfície, gráficos de tela, corpo e mão explicitamente; essa ordem não depende do nome ou do início temporal da proposta. Motion atrás do sujeito segue a camada de fundo; motion em tela segue a camada gráfica. A tipografia e as sequências preservam sua proporção na região reservada.

Para som, o mix preserva o áudio original como base e aplica ducking ao bus de SFX quando há áudio da fonte. Esse controle reage à mixagem original inteira, sem alegar separação automática de voz. Há margem de ganho, limitador e relatório do áudio codificado. Posição em amostras é aferida no PCM anterior à codificação; AAC pode adicionar padding, que permanece separado no relatório. O ataque percebido, a inteligibilidade e a pertinência do som dependem de audição do render.

## 6. Persistir a revisão do arquivo real

Inicialize o estado vinculado ao plano e ao arquivo produzidos:

```bash
python -m visual_fidelity contextual-edit review \
  trabalho/bundle-v1.json trabalho/render-v1.artifact.json \
  --max-retries 2 \
  --output trabalho/review-v1-0.json
```

Depois da revisão realizada, salve um relatório e acrescente-o ao estado existente:

```bash
python -m visual_fidelity contextual-edit review \
  trabalho/bundle-v1.json trabalho/render-v1.artifact.json \
  --state trabalho/review-v1-0.json \
  --report trabalho/qc-v1-realizado.json \
  --output trabalho/review-v1-1.json
```

O relatório contém `id`, `reviewer` com `kind/actor/method`, `plan_sha256`, `render_sha256`, `clock: "output"` e `checks`. Cada dimensão — `technical`, `motion`, `audio` ou `editorial` — declara `status` (`pass`, `fail`, `unverified`), `mode` (`continuous`, `sampled`, `metadata`, `unverified`), intervalos de `coverage` e `notes`.

A cobertura precisa descrever o que foi examinado. Metadados podem sustentar checagem técnica; movimento, áudio e direção exigem cobertura contínua declarada por revisor humano, modelo que de fato tenha examinado esse conteúdo ou usuário. Quadros esparsos, JSON correto, silêncio sobre falhas e um processo encerrado com sucesso não autorizam registrar playback completo.

Uma resposta real do usuário pode acrescentar `approval` com `status: "approved"` ou `"rejected"` e `confirmation`. Apenas `reviewer.kind: "user"` registra esse tipo de resposta. Aprovação editorial e validação técnica permanecem separadas; `can_finalize` não é sinônimo de `user_approval: "approved"`.

Quando um artefato representa apenas parte das decisões, registre `decision_ids` correspondentes. O estado distingue aceitação desse render parcial de conclusão do plano inteiro. Alteração do plano, dos bytes do render ou de seu escopo invalida os relatórios anteriores.

**Continue sempre a partir do estado persistido.** Recriar arbitrariamente um estado vazio perde a continuidade da revisão. O histórico conserva o consumo do orçamento de patches; nenhuma revisão deve apagar uma falha para parecer uma primeira tentativa.

## 7. Aplicar uma correção localizada

O patch referencia `base_plan_sha256`, `base_version`, `reason` e uma lista `updates`. Cada atualização informa `decision_id`, `expected_revision` e a **proposta completa** substituta. Ela conserva o ID da proposta e do evento. Alterações em evidências, fonte ou catálogo exigem nova preparação/direção, não edição manual de hashes.

```bash
python -m visual_fidelity contextual-edit patch \
  trabalho/bundle-v1.json trabalho/patch-v2.json \
  --review trabalho/review-v1-1.json \
  --output trabalho/bundle-v2.json \
  --review-output trabalho/review-v2-stale.json

python -m visual_fidelity contextual-edit render \
  trabalho/bundle-v2.json \
  --font midia/fontes/condensada.ttf \
  --script-font midia/fontes/cursiva.ttf \
  --style midia/estilo.json \
  --output trabalho/render-v2.mp4 \
  --artifact trabalho/render-v2.artifact.json

python -m visual_fidelity contextual-edit review \
  trabalho/bundle-v2.json trabalho/render-v2.artifact.json \
  --state trabalho/review-v2-stale.json \
  --report trabalho/qc-v2-realizado.json \
  --output trabalho/review-v2-1.json
```

O patch só é aceito se as substitutas forem elegíveis e selecionadas. Uma atualização não pode eliminar ou acrescentar silenciosamente decisões fora de seu escopo, incluindo uma camada de áudio companheira no mesmo evento. Cada patch consome uma tentativa e invalida a revisão anterior. Ao esgotar o limite, registre o problema remanescente e solicite decisão sobre o escopo; não mantenha um ciclo ilimitado de correções.

## Biblioteca SFX e busca semântica opcional

O índice fica em `audiovisual.semantic_audio`, separado do CLI de direção:

```bash
python -m audiovisual.semantic_audio probe

python -m audiovisual.semantic_audio index \
  midia/sfx/impacto.wav midia/sfx/transicao.wav \
  --output trabalho/sfx-index.json
```

A verificação desta entrega retornou `clap.status: "unavailable"`, com `torch` e `transformers` ausentes, pesos não verificados, inferência não executada e zero chamadas de API. Rode `probe` novamente no ambiente que executará o projeto.

A indexação comum mede e registra os arquivos. Ela não executa busca semântica. Para dados curatoriais e uma âncora realmente revisada, use `--catalog midia/catalogo-sfx.json` no lugar da lista de arquivos. Um pico de amplitude inferido não equivale ao ataque perceptivo aprovado.

Somente depois de verificar dependências e pesos locais, a opção abaixo solicita embeddings reais:

```bash
python -m audiovisual.semantic_audio index \
  --catalog midia/catalogo-sfx.json \
  --semantic \
  --output trabalho/sfx-semantic-index.json

python -m audiovisual.semantic_audio search \
  trabalho/sfx-semantic-index.json \
  --query "um impacto curto e discreto para acentuar a revelação" \
  --top-k 5
```

O CLAP é carregado sob demanda a partir do cache local; o módulo não instala dependências nem baixa pesos. Sua inferência real não foi validada nesta entrega. Backend ausente ou índice sem embeddings retorna indisponibilidade, sem transformar comparação de nomes em busca semântica. Similaridade recupera candidatos; o diretor e o agente de som ainda escolhem se o efeito faz sentido e onde deve entrar.

No adaptador nativo, o alvo usa 48.000 amostras por segundo. Trims e âncora interna pertencem ao PCM do asset; a normalização registra arredondamentos. O intervalo editorial precisa reservar o som inteiro após o trim, incluindo pré-roll e cauda. Mantenha fonte, arquivo de áudio indexado, capacidade, proposta e relatório de mix vinculados pelos respectivos hashes.

### Candidatos derivados da animação

`motion sonic-candidates` mede o estado animado de uma receita Motion Lab e produz candidatos em `scene_seconds`, com evento, instante, intensidade heurística e evidências. `motion map-sonic` recebe a fonte, os frames inicial/final da aplicação e `asset_start_frame`, e devolve alvos em amostras de 48 kHz com erro de quantização registrado. Exige FPS compatível e cobertura integral; eventos excluídos do trecho permanecem listados. Um alvo arredondado para fora do intervalo é rejeitado.

```bash
python -m editorial_engine motion map-sonic \
  trabalho/motion-v1/sonic-candidates.json midia/bruto.mp4 \
  --source-first-frame 48 --source-last-frame 96 --asset-start-frame 0 \
  --output trabalho/sonic-na-fonte.json
```

O exemplo pressupõe uma sequência com pelo menos 48 frames, mesmo FPS do bruto e uma fonte com pelo menos 96 frames. O intervalo de fonte é `[48,96)`. Esse mapeamento não seleciona arquivo SFX, não mede loudness e não comprova ataque ouvido. O agente de som compara os candidatos com fala/música, escolhe um `audio_asset`, revisa a âncora e entrega uma proposta `native.sfx` completa.

## Receitas e execução retomável

[editorial_engine/workflows.py](../editorial_engine/workflows.py) oferece `validate_recipe`, `bind_workflow`, `preflight_recipe`, `resolve_recipe` e `WorkflowLedger`. Trata-se de uma API Python com callback de execução; **não há comando de geração nem provider externo configurado por esse ledger**.

O integrador fornece disponibilidade medida e um executor `executor(bound_workflow, job_key)`. O retorno precisa identificar um artefato real, seu hash e custo efetivo. A persistência SQLite conserva identidade, estados, reservas e reconciliação. Uma tarefa `running` ou `unknown` não é repetida automaticamente. Disponibilidade desconhecida bloqueia; uma alternativa de receita não pode mudar silenciosamente o modo espacial.

As reservas organizam o limite com base nos valores declarados. O callback externo deve impor o teto de gasto; o ledger não controla cobranças de um serviço independente. Encerramento bem-sucedido e artefato existente continuam separados da revisão perceptiva.

Consulte [higgsfield-reuse.md](higgsfield-reuse.md) para a origem dos padrões estudados e seus limites. Os contratos e o ledger são código próprio. A incorporação seletiva e licenciada de código dos três executores locais de motion está identificada no [guia de integração](motion-integration.md), com revisões fixadas e provas separadas; ela não configura um modelo generativo externo.

## Referências de implementação

- [contracts.py](../editorial_engine/contracts.py): identidade, intervalos, relógio e evidências.
- [catalog.py](../editorial_engine/catalog.py): manifestos e parâmetros tipados.
- [directions.py](../editorial_engine/directions.py): pedido, provider opcional e direção explícita.
- [perception.py](../editorial_engine/perception.py): preparação técnica da fonte e dos recursos.
- [planner.py](../editorial_engine/planner.py): elegibilidade, conciliação, oportunidades e patches.
- [native.py](../editorial_engine/native.py): compilação para as primitivas existentes.
- [audio_render.py](../editorial_engine/audio_render.py): mix, ducking e conferência de áudio.
- [motion.py](../editorial_engine/motion.py): CLI dos executores e exportação para o inventário.
- [motion_assets.py](../editorial_engine/motion_assets.py): sequências RGBA, hashes, mapeamento de quadros e visibilidade.
- [motion_events.py](../editorial_engine/motion_events.py): relógio dos candidatos sonoros no bruto.
- [motion_guidance.py](../editorial_engine/motion_guidance.py): cartas de possibilidades para direção explícita.
- [review.py](../editorial_engine/review.py): revisão vinculada ao arquivo e histórico.
- [semantic_audio.py](../audiovisual/semantic_audio.py): índice, CLAP opcional e relógios de spotting.
- [__main__.py](../editorial_engine/__main__.py): opções atuais dos comandos.
