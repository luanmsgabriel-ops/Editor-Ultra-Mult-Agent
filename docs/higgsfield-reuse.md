# O que aproveitar dos projetos semelhantes ao Higgsfield

Leitura de fontes primárias e de código realizada em **16 de novembro de 2026**. A comparação inicial abaixo trata de seis projetos relacionados à geração e direção, sobretudo ao editar uma filmagem existente. Esses seis estúdios não foram instalados nem executados com GPU ou API paga naquela avaliação. A etapa posterior incorporou subconjuntos de OpenKatana, Motion Lab legado MIT e MOTNGRFX, com provas locais documentadas na seção de motion.

O nome inicialmente mencionado como Hugging Face foi esclarecido como **Higgsfield**. Os seis projetos da comparação inicial são candidatos relacionados; não identificamos um único repositório como sendo necessariamente aquele que o usuário havia visto.

## Decisão para este motor

Adotar três padrões:

1. **Receitas declarativas com requisitos e bindings verificáveis**, como nos manifestos do Freefield e nos contratos do Cheapsfield.
2. **Execução retomável, identificação da tarefa e estado persistente**, como na separação entre diretor, workflow e executor dos projetos open-higgsfield-skills e Comfield.
3. **Composição que preserva a filmagem e revisão vinculada à fonte**, como no recorte, máscara, recomposição e comparação temporal do Body Double.

Esses três padrões foram reimplementados como código original do projeto, sem incorporar os seis estúdios inteiros ou seus modelos. Para execução de motion, a extensão posterior reutiliza código licenciado e fixado dos três projetos descritos a seguir. Os prompts de câmera são úteis para descrever uma intenção, mas a escolha editorial continua dependendo dos pixels, da fala, dos gestos, das oportunidades da cena e das limitações medidas no vídeo atual.

## Extensão implementada para motion no escopo do Katana

O [guia de integração](motion-integration.md) descreve os comandos `motion probe`, `reference`, `audio`, `guidance`, `render`, `evaluate`, `sonic-candidates` e `map-sonic`. A criação continua dirigida por receita explícita. Estes executores acrescentam capacidade de produzir e compor animações, sem configurar um modelo que interpreta qualquer filmagem automaticamente.

| Projeto incorporado | Revisão e licença | Reuso efetivo no Editor Ultra | Limite operacional |
| --- | --- | --- | --- |
| [OpenKatana](https://github.com/rk0neki/OpenKatana) | [`b9282bf0740a7df5b5a8862b5e289ef4cd642641`](https://github.com/rk0neki/OpenKatana/tree/b9282bf0740a7df5b5a8862b5e289ef4cd642641), Apache-2.0, avisos e termos de terceiros preservados | Medição de referência/áudio, timeline, efeitos e prévias com o engine Canvas original em Node; pontes explícitas para Chromium/WebGL e Blender | Medições são estimativas. Disponibilidade das pontes depende do runtime. Um render de timeline opaco não vira overlay transparente. |
| [Motion Lab legado MIT](https://github.com/AndreXes03/motion-lab/tree/6a7f1ca62b7b30d534fe181f912606ad4cfc6718) | `6a7f1ca62b7b30d534fe181f912606ad4cfc6718`, MIT | Grafo 2D, tracks absolutos, grupos, exposição limitada por cortes e planejador de candidatos sonoros; adaptador próprio para geometria/câmera Three.js com raster por CPU | Só a revisão MIT foi incorporada. O backend 3D local usa z-buffer e Lambert, sem sombras, reflexos, PBR ou solve da câmera real. |
| [MOTNGRFX](https://github.com/okkazoo/MOTNGRFX) | [`8c0ddc816616a95f55bddc606eecea3fd5ba5ef1`](https://github.com/okkazoo/MOTNGRFX/tree/8c0ddc816616a95f55bddc606eecea3fd5ba5ef1), Apache-2.0 | Tipografia extrudada, rotação e articulação por glifo, passes de IDs e composição frente/atrás com medição de visibilidade | Subconjunto portátil por CPU. Não incorpora modelos nem executa o pipeline completo de ComfyUI; fonte e matte são recursos explícitos. |

As origens, revisões, licenças, snapshots e alterações ficam em `vendor/` e nos guias de cada adaptador. Os lockfiles fixam as dependências Node. Contribuições proprietárias posteriores do Motion Lab/Framevolve não foram trazidas para o snapshot MIT. A condição de uso de fontes, vídeos, músicas, modelos e serviços permanece própria de cada recurso.

### Do renderer ao plano contextual

Uma sequência realmente renderizada é registrada como `kind: "motion"`, com `path` para `motion-layer.json`. O manifesto conserva FPS racional, quantidade de quadros, raster, alpha straight, hashes individuais e origem. `prepare --assets` verifica os arquivos e oferece uma capacidade `motion_asset`, além de amostras visuais e candidatos sonoros vinculados à receita quando existirem.

`native.motion_layer` aplica essa sequência em tela; `native.motion_behind` exige máscara temporal do bruto. `asset_start_frame` mapeia o relógio local ao intervalo da decisão. FPS incompatível, cobertura insuficiente, vínculo com outra fonte, máscara ausente ou exigência de visibilidade por letra sem seus IDs bloqueiam a operação. A composição não repete quadros nem coloca um efeito atrás do sujeito em primeiro plano para ocultar a falha.

Os candidatos de som indicam instantes derivados do movimento, com evidência e intensidade heurística. `map-sonic` calcula seus alvos no relógio da fonte; a seleção de um arquivo, a revisão do ataque, o ganho e a audição continuam explícitos. Visibilidade estimada na telemetria não substitui a oclusão medida na composição.

O [registro de validação de motion](validation-motion-integration.md) separa execução técnica, provas sintéticas e inspeção visual amostrada. Renderizar uma câmera autorada não prova matchmove; verificar hashes não prova adequação editorial; a aprovação de outro vídeo não aprova esta camada.

## Comparação dos seis candidatos

| Projeto e licença verificada | O que o código realmente faz | Utilidade para filmagem existente | Limite relevante |
| --- | --- | --- | --- |
| [Freefield](https://github.com/neuregex/freefield) — [MIT](https://github.com/neuregex/freefield/blob/main/LICENSE) | Um aplicativo combina manifesto, campos tipados, presets, requisitos de modelos e um workflow ComfyUI. Bindings ligam campos da interface a entradas concretas de nós. Os aplicativos de cinema combinam escolhas de câmera, lente, luz e movimento em prompts. | Melhor referência para cadastrar receitas executáveis e verificar se cada controle chega ao nó correto. | Um aplicativo marcado como pronto comprova a disponibilidade do workflow e de seus bindings no contrato do projeto; não comprova que o resultado combina com a cena. Pedir cortes em um prompt de vídeo não cria uma timeline determinística de cortes. |
| [open-higgsfield-skills](https://github.com/mojomast/open-higgsfield-skills) — [MIT](https://github.com/mojomast/open-higgsfield-skills/blob/main/LICENSE) | Divide direção, stills, geração de planos, revisão e continuidade; descreve rotas, requisitos, alternativas, recursos e etapas retomáveis. | Boa referência de organização entre intenção, execução e revisão. | As necessidades editoriais são descritas em linguagem para o agente; não são um classificador treinado que reconhece a melhor edição. O README delimita etapas de QA e continuidade que não foram exercitadas na demonstração. |
| [Comfield](https://github.com/synthetic-ape/comfield) — [MIT](https://github.com/synthetic-ape/comfield/blob/main/LICENSE) | Compõe prompts por presets; possui assistência de prompt, estimativa de custo, execução de workflow, retomada e chave de idempotência. Há testes de bindings e contratos dos workflows. | Melhor referência de adaptador de execução e de estados de custo conhecido, estimado ou desconhecido. | A assistência expande uma ideia em texto. O código examinado não demonstra um analisador editorial de uma filmagem que escolhe efeitos por contexto. Os testes do repositório foram lidos, não executados nesta avaliação. |
| [Cheapsfield](https://github.com/dougliell/Cheapsfield) — [Apache-2.0](https://github.com/dougliell/Cheapsfield/blob/main/LICENSE) | Define receitas por tarefa/modelo, papéis de imagens e máscara, variantes de workflow e bindings. A direção de cena converte escolhas manuais em prompts. Pode guardar uma receita no PNG. | Contrato claro para distinguir imagem base, referência e máscara; boa inspiração para registrar a receita junto do artefato. | Direção por controles manuais não equivale a reconhecer intenção editorial no vídeo. A interface distribuída para Windows e seus motores não foram executados aqui. |
| [Body Double / open-source-higgsfield](https://github.com/lucataco/open-source-higgsfield) — [Apache-2.0](https://github.com/lucataco/open-source-higgsfield/blob/main/LICENSE) | Pipeline de conformação, detecção, tracking, recorte, referências, segmentos e montagem; mantém estado de execução. Recompõe sobre a filmagem e mede costuras e deriva do fundo em relação à fonte. | É o candidato mais concreto para estudar preservação de fundo, máscaras, continuidade entre segmentos e QA relativo à filmagem original. | Escopo centrado em um performer por execução. O README descreve limitações de poses, halos e enquadramentos. Métricas e limiares de costura não asseguram integração visual nem julgamento editorial geral. |
| [Open Generative AI](https://github.com/Anil-matcha/Open-Generative-AI), anteriormente Open-Higgsfield-AI — [MIT](https://github.com/Anil-matcha/Open-Generative-AI/blob/main/LICENSE) | O componente Cinema Studio transforma seleção de câmera, lente, focal e abertura em prompt e chama geração de imagem. O endereço antigo redireciona para o repositório atual. | Vocabulário de direção e exemplo de separação entre controles criativos e chamada de provedor. | O componente examinado não escolhe edições em footage nem implementa tracking ou composição espacial sobre o vídeo atual. Sua principal contribuição aqui é a interface de direção. |

As licenças acima se referem ao código examinado. Pesos de modelos, datasets, dependências e serviços chamados por cada projeto têm condições próprias. Uma licença de código não autoriza automaticamente o uso de qualquer peso ou serviço incluído no fluxo.

## Evidência de implementação por projeto

### Freefield: manifesto como contrato de execução

Arquivos examinados:

- [schema/app.schema.json](https://github.com/neuregex/freefield/blob/main/schema/app.schema.json): esquema de manifesto, entradas, saídas, modelos e bindings.
- [apps/cinema-video/app.json](https://github.com/neuregex/freefield/blob/main/apps/cinema-video/app.json): composição dos controles criativos e etapas de imagem/vídeo.
- [apps/cinema-studio/app.json](https://github.com/neuregex/freefield/blob/main/apps/cinema-studio/app.json): controles e templates de direção visual.
- [README](https://github.com/neuregex/freefield/blob/main/README.md): instalação, estado dos aplicativos e medições relatadas pelo autor.

A vantagem está em inspecionar uma ligação concreta entre um parâmetro e o campo de um nó. No motor local, um binding inválido bloqueia a execução. Não basta o nome de um botão ou a existência de um arquivo JSON.

Nos aplicativos de cinema examinados, lente, luz, paleta e movimento orientam o gerador por texto. Esse mecanismo pode orientar criação de material novo, mas não mede sozinho se um gesto no vídeo original merece um efeito nem produz garantias de geometria, contato ou continuidade.

### open-higgsfield-skills: separar direção, execução e revisão

Arquivos examinados:

- [skills/video-director/SKILL.md](https://github.com/mojomast/open-higgsfield-skills/blob/main/skills/video-director/SKILL.md): responsabilidades e processo do diretor.
- [skills/video-director/references/routing.md](https://github.com/mojomast/open-higgsfield-skills/blob/main/skills/video-director/references/routing.md): rotas por necessidade, requisitos e alternativas.
- [skills/video-director/scripts/direct.py](https://github.com/mojomast/open-higgsfield-skills/blob/main/skills/video-director/scripts/direct.py): resolução de rotas, orçamento e execução.
- [README](https://github.com/mojomast/open-higgsfield-skills/blob/main/README.md): escopo e limites da demonstração.

Dois detalhes do código motivaram salvaguardas mais estritas no motor local: a resolução consultada aceitava disponibilidade ausente como pronta; a checagem de orçamento consultava gasto acumulado sem reservar o próximo trabalho. Aqui, disponibilidade desconhecida bloqueia, e a reserva ocorre antes de chamar o executor.

Não tratamos a existência de um papel chamado revisor como prova de revisão realizada. O estado de revisão precisa apontar o render real, o que foi examinado e a cobertura temporal.

### Comfield: adaptar workflow sem perder identidade da execução

Arquivos examinados:

- [shared/presets.ts](https://github.com/synthetic-ape/comfield/blob/main/shared/presets.ts): composição de prompts a partir de escolhas.
- [server/src/assist.ts](https://github.com/synthetic-ape/comfield/blob/main/server/src/assist.ts): expansão de prompt e estimativas de custo.
- [server/src/engines/workflow.ts](https://github.com/synthetic-ape/comfield/blob/main/server/src/engines/workflow.ts): preparação, execução, retomada e chave de idempotência.
- [tests/workflows.test.ts](https://github.com/synthetic-ape/comfield/blob/main/tests/workflows.test.ts): verificações dos contratos e bindings.

A identidade da tarefa deve sobreviver a uma queda do processo. Repetir uma requisição sem saber se o provedor já a aceitou pode duplicar o trabalho e a cobrança. Por isso o ledger local distingue falha confirmada de resultado desconhecido, conserva a reserva no segundo caso e permite reconciliação explícita.

### Cheapsfield: papéis dos recursos e receita reproduzível

Arquivos examinados:

- [engine/CONTRATO_WORKFLOWS.md](https://github.com/dougliell/Cheapsfield/blob/main/engine/CONTRATO_WORKFLOWS.md): contrato de receita, workflows, variantes e papéis das entradas.
- [app/src/apps/direcaoCena.ts](https://github.com/dougliell/Cheapsfield/blob/main/app/src/apps/direcaoCena.ts): conversão de controles em prompts de imagem e vídeo.
- [app/src/apps/prompts/cena.ts](https://github.com/dougliell/Cheapsfield/blob/main/app/src/apps/prompts/cena.ts): templates de cena.
- [app/src-tauri/src/receita_png.rs](https://github.com/dougliell/Cheapsfield/blob/main/app/src-tauri/src/receita_png.rs): gravação e leitura de receita em metadados PNG.

O motor adota a ideia de registrar receita e recursos, mas utiliza hashes de conteúdo e registros próprios. Não foi incorporado o mecanismo de escrita em PNG, nem foi importada a aplicação desktop.

### Body Double: avaliar a alteração em relação à fonte

Arquivos examinados:

- [bodydouble/runner.py](https://github.com/lucataco/open-source-higgsfield/blob/main/bodydouble/runner.py): estágios, estado e retomada.
- [bodydouble/media.py](https://github.com/lucataco/open-source-higgsfield/blob/main/bodydouble/media.py): recorte, máscara, transformação e recomposição.
- [bodydouble/qc.py](https://github.com/lucataco/open-source-higgsfield/blob/main/bodydouble/qc.py): costuras e deriva de fundo em relação à fonte.
- [README](https://github.com/lucataco/open-source-higgsfield/blob/main/README.md): escopo, requisitos e limitações conhecidas.

A comparação com a fonte evita marcar como erro uma variação de luz que já existia na filmagem. Esse princípio é útil para QA posterior de fundos, costuras e ancoragem. Ele não substitui assistir ao movimento completo nem ouvir a mixagem.

Os módulos de composição espacial do Editor Ultra já pertenciam ao projeto. Esta comparação justifica reforçar suas evidências e interfaces; não significa que o pipeline do Body Double tenha sido incorporado.

### Open Generative AI: controles de direção são entrada, não julgamento

Arquivo examinado:

- [packages/studio/src/components/CinemaStudio.jsx](https://github.com/Anil-matcha/Open-Generative-AI/blob/main/packages/studio/src/components/CinemaStudio.jsx): mapas de câmera/lente, perspectiva focal, abertura e composição do prompt de imagem.

Os controles expressam uma intenção visual. Um campo de lente não comprova óptica simulada, e um campo de movimento não comprova tracking de câmera. Para editar a filmagem atual, o contrato ainda precisa de âncoras e cobertura medidas.

## Incorporação concreta no Editor Ultra

| Padrão adotado | Implementação local | Comportamento verificável |
| --- | --- | --- |
| Receita e binding explícitos | [editorial_engine/workflows.py](../editorial_engine/workflows.py) | Valida parâmetros, requisitos declarados, tipos de nós, campos existentes, links e placeholders antes de produzir o workflow vinculado. |
| Disponibilidade e rota alternativa | [editorial_engine/workflows.py](../editorial_engine/workflows.py) | Disponibilidade desconhecida bloqueia. Ciclos de fallback bloqueiam. A alternativa deve preservar o modo espacial; não converte 3D em camada plana silenciosamente. |
| Identidade e retomada | [editorial_engine/workflows.py](../editorial_engine/workflows.py) | A identidade deriva de plano, receita, parâmetros e bytes das fontes. Os estados distinguem planned, running, succeeded, failed e unknown. Um artefato alterado deixa de validar o resultado anterior. |
| Reserva e contabilização | [editorial_engine/workflows.py](../editorial_engine/workflows.py) | SQLite serializa reservas concorrentes. Estimativa desconhecida bloqueia com teto finito. Reconciliação registra custo sem consumir a mesma reserva duas vezes. |
| Propostas com evidência | [editorial_engine/directions.py](../editorial_engine/directions.py) e [editorial_engine/planner.py](../editorial_engine/planner.py) | A direção fornece razões e propostas vinculadas aos eventos; o planejador verifica requisitos, conflitos e oportunidades. Notas atribuídas pelo diretor são julgamentos declarados, não medidas automáticas de qualidade. |
| Recursos da filmagem atual | [editorial_engine/perception.py](../editorial_engine/perception.py) e [editorial_engine/native.py](../editorial_engine/native.py) | Preparação e execução tratam hashes, relógio, tracking, máscaras e recursos como evidência específica da fonte. Capacidades técnicas não comprovam adequação estética. |
| Motion renderizado como recurso | [editorial_engine/motion.py](../editorial_engine/motion.py), [motion_assets.py](../editorial_engine/motion_assets.py) e [motion_events.py](../editorial_engine/motion_events.py) | Executa o backend explícito, registra sequências RGBA e mapeia quadros/candidatos sonoros. Registro de arquivo importado distingue atestação do produtor de execução nesta chamada. |
| Revisão do resultado | [editorial_engine/review.py](../editorial_engine/review.py) | A revisão aponta o artefato produzido e distingue cobertura técnica, movimento, áudio e edição. Aprovação do usuário exige registro explícito. |

### Limite operacional do ledger

**Receitas e ledger executam por um callback fornecido pelo integrador. Não há API ou modelo externo configurado por esta incorporação.** O callback recebe o workflow vinculado e uma chave da tarefa, e deve devolver caminho do artefato, SHA-256 e custo real. Nenhum teste com fixture demonstra que um modelo generativo foi executado ou que um vídeo ficou esteticamente adequado.

O ledger só confirma sucesso após verificar os bytes de um arquivo real. Código de saída zero, resposta textual de sucesso ou caminho sem arquivo não bastam. Resultado desconhecido exige reconciliação; repetir automaticamente uma operação externa nessa condição poderia duplicá-la.

A reserva impede que reservas aceitas excedam o teto com base nas estimativas declaradas. Ela não consegue impedir um provedor de cobrar mais do que a estimativa depois da execução. O adaptador externo precisa impor seu limite de gasto; se o custo real ultrapassar a reserva, o ledger registra o gasto e a falha, sem ocultar o excesso.

O módulo de direção possui uma fronteira para um endpoint compatível configurado pelo usuário. Preparar o pedido não executa inferência, e esse suporte não significa que uma credencial, provedor ou modelo estejam disponíveis nesta entrega.

## O que esses projetos não resolvem sozinhos

Nenhum dos arquivos examinados demonstrou um mecanismo completo e validado que receba qualquer filmagem e determine, por conta própria, a edição ideal. Há componentes úteis de direção, geração, workflow, composição e QA. A escolha contextual depende de um diretor humano ou de um modelo configurado com acesso à evidência real, seguido por regras de elegibilidade e revisão do render.

O motor não deve interpretar nome de arquivo como semântica do efeito, prompt de câmera como câmera resolvida, máscara presente como máscara temporalmente correta, nem execução concluída como aprovação estética. Preservar um trecho é uma decisão editorial explícita; indisponibilidade de recurso precisa permanecer visível.

Este documento conserva a avaliação inicial e identifica a implementação posterior de motion. Os repositórios podem mudar; o código incorporado permanece nas revisões fixadas. Reutilização futura de outras revisões ou modelos exige nova conferência da origem e das licenças aplicáveis.
