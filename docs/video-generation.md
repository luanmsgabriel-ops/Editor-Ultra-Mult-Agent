# Direção e prompts para vídeos conectados

`python -m editorial_engine generation` transforma um plano audiovisual escrito pelo diretor em prompts independentes por clipe, configurações, anexos e instruções de montagem. Recebe depois os vídeos efetivamente produzidos e registra seus arquivos, tempos e quadros de referência. O projeto conserva a direção quando a ferramenta de geração muda.

A compreensão da referência e as decisões criativas pertencem ao agente no host ou ao diretor humano. O compilador valida contratos e organiza instruções; não escolhe uma câmera por palavras-chave, não resolve continuidade visual por contagem de caracteres e não envia jobs a provedores.

## Política de execução: sempre entregar os prompts

Toda necessidade de geração de vídeo termina em **prompts por tomada, configurações, referências, continuidade e instruções de montagem**. O usuário executa esses prompts na ferramenta que escolher e devolve os vídeos para o motor conferir e editar. O fluxo não consulta avatares cadastrados nem exige um seletor de aparência de fornecedor. A identidade pertence à ficha e às referências do projeto.

`video_generation_policy.execution_policy()` fornece `mode="prompt_export_only"`. Essa regra acompanha briefing, pedido ao diretor, pacote e estado do projeto. Uma solicitação `external_video` permanece manual mesmo que receba um callback; exportar um pedido não reserva crédito nem cria mídia. Processamento local de filmagens, render de templates/motion/3D e composição são operações próprias e continuam disponíveis. O endpoint de `generation direct` escreve direção textual; não é um gerador de vídeo.

## O que entra no plano

O contrato `video-generation-plan/1` reúne objetivo, público, proporção, duração final, idioma, personagens, cenários, objetos, evidências, recursos a produzir, clipes e suas ligações. O exemplo autoral está em [`examples/video_generation/three-clips-plan.json`](../examples/video_generation/three-clips-plan.json).

Cada plano de câmera descreve intenção, ação, composição, câmera, atuação e iluminação. Falas têm personagem responsável, texto literal, intervalo previsto e indicação de fala em quadro ou fora de quadro. A descrição global preserva identidade, figurino, voz e condições que permanecem durante o filme. Não existe quota obrigatória de cortes, efeitos, movimentos ou títulos.

O diretor deve explicar por que uma intervenção ajuda a cena: revelar uma informação, acompanhar uma ação, estabelecer contraste, explicar uma relação ou preparar a próxima imagem. Ausência de efeito pode ser a decisão correta. Esse julgamento continua atribuído ao autor; a validação do JSON não o certifica.

### Referência e imagens ausentes

Os modos `reference_clone`, `adaptation` e `fill_gaps` exigem evidências identificadas nos clipes e nos recursos. Cada observação aponta para fonte, SHA-256, intervalo quando aplicável e escopo real: quadros amostrados, vídeo contínuo, áudio ouvido, transcrição, documento ou anotação humana. O modo `original` pode começar sem arquivos.

Um recurso pendente informa tipo, função, rota e referências. As rotas são reutilização, imagem no chat, vídeo externo, produção procedural e fornecimento pelo usuário. `chat_image` produz uma imagem estática; câmera que revela volume pode exigir vídeo ou geometria. A geração no chat é uma ação do host com as ferramentas disponíveis, não uma chamada implementada por esta biblioteca Python.

`generation assets` exporta os pedidos de recursos pendentes. Depois de produzir e revisar uma imagem, o diretor registra caminho absoluto e hash numa nova revisão do plano. Um recurso pendente não recebe caminho fictício. Imagens de início/fim, identidade, cenário, movimento e voz mantêm papéis explícitos.

## Briefing sem repetir respostas

`generation brief` combina respostas do projeto com preferências fornecidas. Respostas atuais prevalecem. Retorna lacunas e até três perguntas por rodada; não pergunta por um campo já resolvido nem exige escolher o fornecedor para iniciar uma direção neutra.

`generation request` prepara um pedido estruturado de direção. Pode receber `analysis.json` produzido pelo motor atual e dados de recursos. O pedido contém instruções originais, fatos disponíveis, escopo de observação e contrato de resposta. Criar esse pedido não executa inferência: o host precisa inspecionar o material e preencher o plano.

As perguntas são condicionais à produção. Personagem recorrente pede identidade e voz; referência pede o grau de adaptação; texto literal pede destino e sincronização; duração e ferramenta definem como dividir os clipes. Estratégia de perfil, conexão a redes sociais e planejamento semanal são etapas opcionais externas a este fluxo.

## Cada ligação é planejada dos dois lados

Uma entrada de `joins` liga exatamente dois clipes consecutivos. Ela guarda razão editorial, execução na geração/na edição/em ambas, descrição da saída e da entrada, movimento, câmera, áudio, condições a preservar e sobreposição. A abertura do primeiro clipe e o fechamento do último ficam nesses clipes. As outras fronteiras têm um único dono: sua ligação.

| Estratégia | O que o compilador usa | Condição para finalizar o próximo prompt |
| --- | --- | --- |
| `planned_frame` | A mesma imagem como fim do anterior e início do seguinte | Arquivo real; compatibilidade com esse papel é conferida quando houver perfil |
| `observed_frame` | Um quadro explicitamente selecionado do vídeo devolvido | Recibo íntegro, observação do trecho e coerência do quadro com o corte útil |
| `native_extension` | O vídeo anterior como entrada | Suporte a essa entrada e semântica explícita de duração da extensão |
| `prompt_only` | Descrições completas de estado e movimento | Controle menor de continuidade, indicado no pacote |
| `post_only` | Instrução de montagem fora da geração | Operação e sobreposição declaradas; execução posterior |

Uma imagem compartilhada ajuda a conservar aparência e enquadramento; ela não confirma velocidade, fase do movimento ou continuidade sonora. O diretor confere um trecho em torno da emenda. Se o quadro final estiver deformado e outro quadro for escolhido, isso não autoriza cortar o vídeo automaticamente: o intervalo útil precisa de revisão explícita.

### Duração gerada e duração final

O contrato distingue duração solicitada ao gerador, faixa aproveitada e sobreposição. A conta usa frações exatas de segundos:

`duração final = soma das faixas aproveitadas - soma das sobreposições`

Três clipes de dez segundos e dois cortes sem sobreposição dão trinta segundos. Os mesmos clipes com duas sobreposições de meio segundo dão vinte e nove. Para manter trinta, o diretor precisa alterar conscientemente a duração, os trims ou a estratégia. Um vídeo extra de transição é um clipe explícito no plano. O módulo não repete quadros ou inventa duração para completar o resultado.

Os tempos dos planos e das falas são direção ao gerador, não promessa de obediência. O relógio final em frames só pode ser conformado depois de receber e inspecionar a mídia real.

## Perfis da ferramenta e exportação

Um perfil `video-generation-capabilities/1` identifica ferramenta, modelo, modo, interface, origem e data da conferência. Declara durações, proporções, tamanho máximo do prompt, entradas e seus campos, suporte a áudio/fala e múltiplos planos. O exemplo [`capabilities-template.json`](../examples/video_generation/capabilities-template.json) é deliberadamente **não verificado**; seus valores não descrevem um fornecedor real.

O estado verificado do perfil é uma atestação fornecida pelo autor. A compilação não consulta a API em tempo real. Recursos desconhecidos não se tornam disponíveis por inferência. Um limite no campo de duração ou na entrada de imagem precisa ser atendido na interface do fornecedor; escrever a configuração no prompt não substitui esse ajuste.

Sem perfil, a exportação entrega prompts neutros e registra compatibilidade externa não verificada como nota. Escolher ferramenta ou modelo não é requisito. Com `--ready`, cada clipe é verificado separadamente; arquivos e quadros de continuidade que faltam continuam pendentes. O primeiro pode estar pronto enquanto o segundo aguarda o vídeo anterior. Prontidão significa que os requisitos declarados para uso manual dos prompts estão satisfeitos, não que algum serviço recebeu uma chamada, aceite os parâmetros ou produza um resultado aprovado.

`prompt_export.status="complete"` informa que os textos foram exportados, inclusive quando `status="draft"` ou algum anexo continua pendente. `execution_policy.automatic_video_generation=false` permanece fixo. Se houver perfil, incompatibilidades declaradas continuam bloqueando a prontidão desse perfil, sem truncar textos ou alterar silenciosamente a direção.

O pacote contém JSON, Markdown copiável e um `.txt` por clipe. Cada prompt repete as informações de identidade e estilo necessárias; não depende de expressões como “o mesmo do anterior”. Configurações e anexos ficam separados. O compilador preserva a prosa e as falas fornecidas, não traduz automaticamente. O idioma precisa ser revisado pelo autor. Não há preenchimento até um tamanho arbitrário nem truncamento silencioso quando o limite é excedido.

### Voz, textos e pós-produção

`brief.audio_execution` indica `generation`, `post` ou `none`. Pedidos de áudio gerado precisam de saída de áudio declarada; falas também precisam de suporte a fala. `none` é vídeo silencioso e não pode conter diálogo a ser descartado. Uma referência de voz não comprova sincronismo labial. Fala visível com áudio adicionado depois continua pendente quando não existe um método explicitamente resolvido para esse sincronismo.

Textos exatos, logos, efeitos sonoros e motion podem ser declarados em `post`. Suas instruções saem separadas do prompt de vídeo, com arquivos verificados em `post_assets`, para execução pela pós-produção. O intervalo útil precisa conservar as falas e os eventos de pós por inteiro; descartá-los exige alteração explícita da direção. O gatilho de uma palavra é uma intenção até que o áudio real permita alinhamento. Esses itens são um plano de acabamento, não operações já renderizadas por este módulo.

## Receber e conferir resultados

`generation import` lê um arquivo real com FFprobe/FFmpeg. Registra duração, FPS racional, timestamps, número de quadros, raster, áudio e amostras decodificadas com hashes. Preserva a mídia original e não corta silêncio, altera FPS ou retima automaticamente.

`--selected-frame` é um índice começando em zero, escolhido explicitamente. A observação declara ator, método e escopo. Para uma janela, informa intervalo de frames; um quadro isolado não comprova continuidade de movimento. O recibo mantém estado planejado e observação separados.

`observation.continuity_decision` guarda `status` (`accept`, `revise` ou `unassessed`), `actor` e `reason`. Observar não implica aceitar. O próximo clipe dependente exige a decisão editorial `accept`, vinculada ao trecho efetivamente revisado; isso não representa aprovação do usuário. O padrão é `unassessed`.

FPS variável, corte fora da fronteira de um frame, proporção divergente, pixels não quadrados e rotação declarada ficam pendentes de adequação explícita. A duração visual é medida pelos quadros; áudio mais longo e duração do contêiner são registrados separadamente. Para extensão nativa, o recibo conserva `output_semantics`: retorno completo ou indefinido não cabe silenciosamente como novo clipe independente.

`--export-pack` associa o texto exportado ao retorno e preserva suas dependências. Essa associação registra a declaração da produção; não demonstra que o fornecedor recebeu ou respeitou os anexos. Os resultados precisam de revisão visual e sonora.

`generation verify-return` confere recibo, instruções relevantes, mídia e quadros. Mudança no arquivo ou na direção aplicável invalida o vínculo. A compilação também verifica se uma cadeia usa a mesma versão dos resultados anteriores. Um recibo nunca equivale a aprovação do usuário.

## Revisões e responsabilidade dos agentes

Uma coordenação mantém o plano. Agentes de decupagem, roteiro/direção, recursos, continuidade e QC podem produzir propostas e observações em paralelo. Eles não editam simultaneamente a mesma timeline.

`generation revise` recebe duas versões completas e informa os clipes alterados, preservados e dependentes. Mudança numa ligação atinge suas duas pontas. Mudança global de identidade atinge os clipes afetados pela descrição global. Uma cadeia baseada em resultados anteriores invalida os descendentes do trecho alterado. A versão anterior e seus recibos ficam preservados.

Não se transfere aprovação para o novo vídeo, não se apaga histórico para ganhar novas tentativas e não se marca revisão positiva só porque um comando terminou. A revisão audiovisual contínua e a confirmação do usuário permanecem registros próprios.

## Exemplo de uso

Execute na raiz do repositório. Cada saída usa um caminho novo:

```bash
python -m editorial_engine generation brief examples/video_generation/brief-answers.json --output trabalho/brief-v1.json
python -m editorial_engine generation request examples/video_generation/brief-answers.json --output trabalho/direction-request-v1.json
python -m editorial_engine generation validate examples/video_generation/three-clips-plan.json
python -m editorial_engine generation assets examples/video_generation/three-clips-plan.json --output trabalho/assets-v1.json
python -m editorial_engine generation export examples/video_generation/three-clips-plan.json trabalho/prompts-v1
```

Para conferir os arquivos necessários sem escolher ferramenta:

```bash
python -m editorial_engine generation export trabalho/plan-v2.json trabalho/prompts-neutros --ready
```

Se o usuário também solicitar adaptação a uma ferramenta, um perfil real pode ser fornecido opcionalmente:

```bash
python -m editorial_engine generation export trabalho/plan-v2.json trabalho/prompts-v2 --profile trabalho/capabilities.json --ready
python -m editorial_engine generation import trabalho/plan-v2.json clip-1 midia/clip-1.mp4 trabalho/return-1 --export-pack trabalho/prompts-v2/prompt-pack.json
python -m editorial_engine generation verify-return trabalho/plan-v2.json trabalho/return-1/receipt.json
python -m editorial_engine generation revise trabalho/plan-v2.json trabalho/plan-v3.json --output trabalho/revision-v3.json
```

As observações de emenda são adicionadas na importação correspondente com `--selected-frame` e `--observation`. `--returns` na exportação recebe JSON mapeando IDs dos clipes para seus recibos completos. O exemplo de três clipes usa personagem fictício e recursos pendentes; demonstra a direção e o contrato, não um filme já gerado.

## Fontes de arquitetura e limites

Esta implementação é original. O estudo comparou direção detalhada fornecida para uso privado com estes repositórios públicos, nas revisões registradas:

| Fonte | Revisão | Ideia geral aproveitada |
| --- | --- | --- |
| [OSideMedia/higgsfield-ai-prompt-skill](https://github.com/OSideMedia/higgsfield-ai-prompt-skill) | `6a6a5dd105d285782dd6992692be4d8b3825ca13` | Referências estáveis e prompts independentes por plano |
| [jdnichollsc/seam](https://github.com/jdnichollsc/seam) | `b9f439e2dc72128d961f8e889aee8dae00e9263a` | Cada ligação tratada como decisão e unidade de revisão |
| [HKUDS/ViMax](https://github.com/HKUDS/ViMax) | `fd4b72e7731be6e5f88486206d25ea59849b0285` | Plano, referências e decomposição de imagens e movimento |
| [mojomast/open-higgsfield-skills](https://github.com/mojomast/open-higgsfield-skills) | `5a1a2d492540d349a2d84d413e4b71f88aa94519` | Manifesto de produção, dependências e etapas retomáveis |
| [higgsfield-ai/skills](https://github.com/higgsfield-ai/skills) | `27000402070db19d958789d05b3b52b6f4718d7c` | Configurações e entradas específicas da ferramenta |

Nenhum desses geradores foi instalado ou executado nesta integração. Modelos de vídeo, gateways comerciais, montagem automática dos novos clipes e julgamento perceptivo autônomo não fazem parte desta camada. Os executores existentes de edição/motion continuam disponíveis para uma produção efetiva, com seus próprios contratos de recursos e revisão.
