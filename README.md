# Editor Ultra Multi-Agent

Fluxo de edição no Codex com nove agentes, nove skills e comandos para inventário de mídia, catálogo com escopo no Drive, curadoria, validação de cortes e áudio em amostras, renderização e auditoria. O piloto Oníria mantém um plano editorial definido e recompila a variante com novos SFX. A direção escolhe os cortes e aprova os efeitos com evidência. O motor valida, aplica e confere o que foi aprovado.

## Começar no Codex

Abra o repositório no Codex com acesso aos arquivos do projeto. Informe fontes, referência, destino e raízes permitidas do Drive. Peça ao coordenador para executar `AGENTS.md` e produzir um plano com timecodes, catálogo, cortes e uma versão comparável. Os papéis do Codex ficam em `.codex/agents` e os procedimentos em `.agents/skills`. [Documentação de agentes](https://learn.chatgpt.com/docs/agent-configuration/subagents)

O repo usa Python 3.11+ e ffprobe. O piloto requer FFmpeg (libass, zscale e libx264), NumPy e fontes do sistema. Reconstruir o letreiro requer também Blender e Pillow.

## Projeto Clone: da entrada à entrega

`python -m editorial_engine project` conecta os motores em um projeto persistente: entradas com papel explícito, direção, produção de recursos, retorno dos clipes, montagem real, acabamento, revisão e pacote de entrega. O estado aponta a próxima ação e os arquivos que perderam validade quando uma fonte ou decisão muda. As onze entradas incluem editar um bruto, montar vários, adaptar referência, recompor com novas filmagens/pessoas, gerar sem referência, partir de imagens/áudio/roteiro, preencher lacunas, personalizar templates, receber clipes e revisar versões.

```sh
python -m editorial_engine project routes
python -m editorial_engine project init trabalho/campanha examples/project_flow/original.json
python -m editorial_engine project advance trabalho/campanha
python -m editorial_engine project status trabalho/campanha
```

O [manual do projeto](docs/clone-project.md) reúne comandos e conexões. O [dossiê de referência](docs/reference-direction.md) define o que manter e substituir; o [provider de direção textual](editorial_engine/generation/provider.py) envia imagens verificadas a um endpoint configurado e valida o plano retornado. A [fila de produção](docs/production-adapters.md) conecta motion local, instâncias de template, callbacks explícitos de processamento e exportação/importação manual de recursos. Geração de vídeo sempre entrega prompts para execução externa pelo usuário. A [montagem](docs/assembly.md) executa cortes e transições entre fontes reais, com trims, formato e áudio declarados.

A produção nativa de [portal planar](docs/planar-portal.md) recebe uma base, uma inserção independente, quatro cantos por quadro e oclusão temporal. `screen_reveal` mantém a imagem revelada ereta enquanto a janela inclina; `projective` prende o conteúdo ao plano. O produtor entra na fila como `operation="planar_portal"` e exporta MP4 silencioso ou camada RGBA. Tracking, camadas ocultas e qualidade visual continuam sendo etapas explícitas de preparação e revisão.

Os serviços externos continuam exigindo adaptador ou retorno manual. Um pedido de imagem não equivale a uma imagem gerada; um template instanciado ainda precisa de render; a montagem conserva as pendências de pós. A entrega final exige revisão contínua do arquivo atual. É possível entregar prompts ou uma prévia antes dessa revisão. Para executar uma prova local de três clipes, sem modelos externos, use `python -m examples.project_flow.demo --output trabalho/prova-clone`.

A [validação das conexões](docs/validation-clone-project.md) registra o gate desta etapa: 538 testes e 57 subtestes passaram, além da demonstração local de três clipes com duas transições e duração final medida. As simulações de provider permanecem identificadas.

## Direção contextual de novos vídeos

O fluxo padrão para escolher efeitos em um novo bruto é `python -m visual_fidelity contextual-edit`. Ele prepara quadros reais, fala e recibos de rastreamento; recebe direção explícita de uma pessoa, do agente no host ou de um modelo multimodal configurado; concilia propostas e executa as operações viáveis. Cada decisão guarda intenção, evidência, intervalo, efeito, âncora, parâmetros e justificativa. Eventos sem decisão bloqueiam o render; preservar também exige justificativa explícita.

O catálogo nativo executa tipografia cinética, imagens e sequências animadas em tela ou atrás do sujeito, projeções em superfícies medidas, órbita corporal, acento na palma e SFX. Máscaras e trajetórias pertencem ao bruto atual. Os requisitos são conferidos antes da execução, as animações respeitam as regiões reservadas e as revisões ficam ligadas aos hashes do plano e do arquivo renderizado. Cenas 3D autoradas podem ser produzidas pelos executores locais de motion; integração espacial na filmagem continua exigindo câmera, plano ou tracking medidos. Geração por modelo externo exige configuração explícita.

Leia o [guia de direção contextual](docs/contextual-editing.md) para preparar o projeto e executar `prepare`, `request`, `plan`, `render`, `review` e `patch`. O comando opcional `direct` chama um endpoint multimodal configurado; o host também pode produzir `direction.json` após examinar as fontes. Não há substituição da análise por palavras-chave quando o modelo está indisponível.

A [comparação de alternativas ao Higgsfield](docs/higgsfield-reuse.md) documenta os padrões reimplementados: manifestos de efeitos, verificação de recursos, receitas, execução retomável e conferência contra a filmagem original. O ledger de workflows reserva custo antes de executar um callback, verifica arquivos reais e não repete jobs de estado desconhecido. Nenhum provedor de geração externo vem configurado.

A busca semântica de áudio em `audiovisual.semantic_audio` admite CLAP local opcional e diferencia indexação técnica de embeddings reais. O render de SFX usa o ataque interno do arquivo, reamostragem explícita, ducking pelo áudio original e controle de picos. Aprovação perceptiva de sincronismo, inteligibilidade e direção continua registrada separadamente dos testes.

O [registro histórico de validação contextual](docs/validation-contextual-edit.md) descreve a bateria de 315 testes daquela etapa e distingue as provas de render/PCM da avaliação com modelo e filmagem reais. A validação da expansão de motion fica em [registro próprio](docs/validation-motion-integration.md); a contagem histórica não representa a suíte atual.

## Direção e geração de prompts de vídeo

**Política permanente: `prompt_export_only`.** O motor entrega prompts por tomada, configurações, referências, continuidade e montagem; o usuário gera os vídeos na ferramenta que escolher e devolve os arquivos. Não há escolha obrigatória de serviço, cadastro de avatar ou submissão automática de vídeo. Perfis opcionais conferem compatibilidade, sem executar geração. Renderização e composição locais continuam próprias da edição. Veja a [correção e validação da política](docs/validation-prompt-only-video.md).

`python -m editorial_engine generation` organiza briefing, personagens, cenas, imagens pendentes e ligações entre clipes; exporta prompts autossuficientes com configurações e anexos separados para a ferramenta escolhida. Ao receber os vídeos, registra metadados, quadros selecionados e dependências por hash. A direção pode ser escrita pelo host ou solicitada pelo comando `generation direct` a um endpoint configurado. O compilador verifica contratos e duração; não apresenta validação técnica como qualidade visual. Consulte o [guia de geração](docs/video-generation.md), a [direção com referências verificadas](docs/reference-direction.md) e o [exemplo autoral de três clipes de dez segundos](examples/video_generation/three-clips-plan.json).

A [validação desta integração](docs/validation-video-generation.md) registra 453 testes e 42 subtestes aprovados, incluindo encadeamento e revisão de retornos com vídeos sintéticos reais. Essa evidência técnica não representa aprovação estética de um gerador externo.

## Criação de motion e aplicação ao bruto

`python -m editorial_engine motion` reúne OpenKatana, Motion Lab legado MIT e MOTNGRFX portátil. OpenKatana mede referência/áudio e executa timeline e efeitos; Motion Lab oferece cenas 2D, grupos independentes, blur por subframes e 3D por CPU; MOTNGRFX produz tipografia extrudada com rotação ou articulação por glifo. O diretor escolhe a receita pela função do trecho. Consulte o [guia de integração de motion](docs/motion-integration.md) para instalação, licenças fixadas, exemplos e disponibilidade medida por backend.

```sh
python -m editorial_engine motion probe --output trabalho/motion-probe.json
python -m editorial_engine motion guidance --output trabalho/motion-guidance.json
python -m editorial_engine motion render motionlab examples/motion_integration/motionlab-2d.json trabalho/motion-v1 --samples 4 --asset-id motion-explicacao
python -m editorial_engine prepare midia/bruto.mp4 trabalho/analise-motion-v1 --assets trabalho/motion-v1/inventory.json --protection midia/protecao.json
```

Configure a receita com o FPS do bruto e uma duração que cubra a decisão antes de renderizar. O export gera PNGs RGBA com alpha straight, `motion-layer.json`, inventário `kind: "motion"` e hashes por frame. `native.motion_layer` compõe a sequência; `native.motion_behind` exige também matte do sujeito. O relógio da camada é mapeado por `asset_start_frame`, sem repetição, congelamento ou retime implícitos. Fonte, máscara, proteção e eventual vínculo da camada precisam coincidir com o bruto atual.

Candidatos SFX derivados do movimento entram na direção com evidências e tempo local. `motion map-sonic` os leva ao relógio da fonte; escolher um som, revisar seu ataque e ouvir a mixagem continuam etapas explícitas. Geometria 3D em câmera sintética não demonstra câmera resolvida na filmagem, e um contato de frames não comprova playback contínuo ou aprovação do usuário.

## Templates autorados e biblioteca privada

`python -m editorial_engine templates` verifica bibliotecas portáteis por hash, apresenta fichas ao diretor e cria instâncias em diretórios novos com parâmetros explícitos. Código, fontes, imagens e demonstrações permanecem no pacote privado. A personalização preserva a versão original e gera um recibo das alterações; o comando não executa scripts contidos nos templates.

Use `editorial_engine request --template-library caminho/library.json` para incluir os templates na direção contextual. Os requisitos de mídia, máscaras, câmera e runtime continuam visíveis. Um template catalogado ou uma demonstração fornecida não se transforma automaticamente em efeito nativo pronto; a sequência renderizada entra pelo contrato de motion já existente. Consulte o [guia de templates](docs/template-library.md).

## Inventário e verificação do projeto

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q tests extensions
python -m unittest discover -s tests -v
python -m unittest discover -s extensions -v
python -m audiovisual inventory /caminho/dos/brutos --output inventario.json
python -m audiovisual validate examples/secador.json
python -m audiovisual.drive_catalog --snapshot drive-snapshot.json --local assets/ --output drive-catalog.json
python extensions/editor_policy.py rank drive-catalog.json necessidade.json drive-scope.json
```

A coleta de metadados também pode consultar a API oficial do Drive. Passe IDs autorizados via `--root` e disponibilize um token no ambiente como `EDITOR_DRIVE_ACCESS_TOKEN`. O arquivo de saída será local. O comando segue paginação, verifica parentesco e mantém atalhos registrados sem seguir destinos. Em sessão com conector, obtenha o catálogo e os arquivos diretamente da conexão autorizada e use `--snapshot`. Salve os arquivos efetivamente baixados no formato `ID.ext`.

O ranking calcula elegibilidade por origem, família, compatibilidade, destino e duração verificada. Pode incluir ativos pendentes para prévia privada autorizada via `allow_unverified_private_preview` no escopo. Cada candidato escolhido precisa bater com o SHA-256 da cópia baixada. A escuta e a adequação editorial são revisadas no contexto da cena. Um pico de onda sozinho não identifica batida, gesto ou efeito.

## Piloto reproduzível

```sh
python -m pilots.oniria.run \
  --sources /caminho/dos/brutos --stage /caminho/do/palco-composto.mp4 \
  --catalog drive-catalog.json --scope drive-scope.json --cues cues.json \
  --assets assets/ --base mix-de-controle.flac --out out/oniria
```

Para repetir apenas som e montagem final, use `--picture` com a imagem limpa já renderizada. O comando grava ranking, decisão, cues, validação do quadro e da amostra, MP4 conferido e manifesto. Os brutos, escopo do projeto, mix e arquivos licenciados ficam no ambiente do projeto. O pacote de auditoria do piloto registra as três escolhas e os parâmetros reais para reaplicá-las. `docs/Mapa-de-Pos-Producao.md` descreve como evoluir os adaptadores de efeitos, a timeline gráfica e as provas 3D.

## Cobertura

O piloto exercita ingest de catálogo, ranking, três efeitos de áudio com proveniência, plano travado, imagem dos 38 brutos, mix, export e verificação. Os papéis de agente integram essa execução quando acionados no Codex. Análise semântica e calibração espacial automatizadas em qualquer filmagem, round-trip gráfico e julgamento perceptivo sem revisão permanecem etapas distintas de validação.

## Motion a partir de referência

Para transferir o estilo da Clara a um novo bruto, use a [direção contextual](docs/contextual-editing.md), com perfil de referência e evidências do vídeo atual. O [template por fala e rastreamento](visual_fidelity/ADAPTIVE_TEMPLATE.md) permanece disponível para reproduzir seu fluxo específico; suas regras de palavras e ícones não são o diretor semântico geral.

O [piloto da cascata de três cards](pilots/motion_cards/README.md) mede movimentos, aplica o mesmo template sobre outro bruto e exporta uma comparação e uma composição HyperFrames.

O [motor de fidelidade visual](visual_fidelity/README.md) mede fontes e vetores, renderiza materiais em Blender/Cycles e compõe fotos ou malhas na timeline Origins. Os adaptadores opcionais de COLMAP e TRELLIS.2 operam em ambientes externos.

Para adaptar palavras e gráficos ao enquadramento de outro vídeo, use `python -m visual_fidelity anchor render` com o [plano de exemplo](examples/ancoras-visuais.json). O motor escolhe uma posição por plano ou acompanha uma superfície pela homografia. O [manual de âncoras](visual_fidelity/README.md#aplicar-texto-e-efeitos-a-outro-vídeo) também cobre trajetórias TAPIR e projeção por câmera Blender/COLMAP.

Para seguir cabeça, ombro, mãos, quadril, joelhos ou pés, use as [âncoras corporais](visual_fidelity/README.md#âncoras-no-corpo-e-órbita). O [plano de exemplo](examples/ancoras-corpo.json) combina uma órbita de texto com o rastreamento do ombro.

A [biblioteca de efeitos](https://drive.google.com/drive/folders/1f3oYF6f1JP1BZVZ2HVkAq7I6I-q-evJC) reúne motion, transições, LUTs, overlays e sons. O [manual do motor](visual_fidelity/README.md#biblioteca-de-efeitos-no-drive) documenta as fichas versionadas, a busca e a criação de novas variantes. Para captura real e auditoria de curvas consulte [MOTION.md](visual_fidelity/MOTION.md).
