---
title: "Sistema de pós-produção audiovisual"
subtitle: "Do vídeo bruto ao master • mapa de ofícios, acervo, timeline e agentes"
lang: pt-BR
geometry: margin=19mm
fontsize: 10pt
colorlinks: true
linkcolor: teal
urlcolor: teal
mainfont: DejaVu Sans
---

# 1. Como o sistema deve funcionar

**Um repositório privado para código e regras. Um projeto versionado por vídeo. Um catálogo de mídia no Drive. Uma timeline humana editável.** O diretor de edição decide a intenção de cada trecho. Especialistas propõem operações com fonte, timecode, motivo e critérios de revisão. Um compilador aplica essas operações e grava a versão. O controle de qualidade revê a versão exportada e encaminha só os problemas aos especialistas.

Entrada típica: brutos, referências, objetivo, marca e saídas pedidas. O sistema devolve um diagnóstico com evidências, duas ou três direções plausíveis, uma recomendação e uma montagem revisável. Se importar trecho do final para abrir o vídeo, deve apontar o timecode, explicar o ganho e manter a ordem factual da história. As operações sobre o bruto são não destrutivas. A primeira entrega pode ser um corte limpo com fala tratada, antes de cor, motion, overlays ou mix final.

**Separar três decisões.** Formato é a peça comercial, Reel, UGC, institucional ou tutorial. Estilo é a linguagem documental, editorial, cinética, humor, luxo ou espetáculo. Destino é a versão 9:16, 16:9, 4:5 ou 1:1 e seu perfil de duração, áudio, área segura e acessibilidade. Um produto pode ter herói 16:9, anúncio 9:16 e demonstração UGC usando a mesma identidade com estruturas editoriais próprias.

## Referências de mercado e o que copiar do método

| Referência | Decisão para o sistema |
|---|---|
| Framestore, Overwatch — *Free This Weekend?* [1] | Usar créditos reais de editorial, música, som, cor, VFX e finalização como referência para dividir entregas por ofício. |
| Framestore, Gap — *Meet Wearlight Denim* [2] | Planejar VFX e versões de campanha desde o brief. A supervisão começa antes do acabamento. |
| Framestore, Lurpak — *Where There Are Cooks* [3] | Estudar cor e VFX invisível como linguagem de marca. Integrar correções à ação do plano. |
| Natura Una, Clube de Criação [4] | Referência nacional com créditos de montagem, VFX, finalização, cor e áudio. |
| AICP Post Awards [5] | Pesquisar por disciplina, categoria e ano. Catalogar referências por decisões observáveis e por seus timestamps. |
| Frame.io, Adobe e Blackmagic [6–9] | Transformar etapas de ingest, proxy, montagem, conform, Fusion, cor e Fairlight em procedimentos verificáveis. |

Para cada referência, salvar URL, peça, marca e créditos, formato, propósito, mapa de timecodes, estrutura de gancho e final, motivos do design e aspectos adaptáveis. Em áudio, anotar quais momentos marcam frase, batida, gesto e transição. Em imagem, acompanhar como textura, tipografia, enquadramento e cor afetam leitura. Usar fontes e assets próprios ou licenciados para a execução.

# 2. Do bruto ao master

| Etapa | O que o sistema faz e o que entrega |
|---|---|
| 01 Brief e entrega | Define público, propósito, canal, identidade, duração, CTA, requisitos de aprovação, direitos, idiomas e versões. Define fatos e planos obrigatórios. |
| 02 Ingest e preservação | Conta arquivos, fixa IDs e hashes, valida integridade, duplicatas, áudio, timecode, codec, resolução, rotação, taxa de quadros, VFR, perfis log/HDR e metadata. Guarda a relação original–proxy. |
| 03 Preparação | Proxies e dailies, sincronismo por timecode, claquete ou waveform, multicam, scratch audio, bins, nomenclatura, transcrição com timestamps, diarização quando ajuda. Mapeia tempo irregular do bruto sem perder correspondência. |
| 04 Leitura do bruto | Separa planos, falas, música, silêncios, gestos, produto, pessoas, OCR, movimento, olhar, escala, horizonte, luz e cor. Marca problemas, oclusões, cortes suspeitos, chances de reenquadrar e evidências. Entrega selects e mapa de planos/ações. |
| 05 Direção e montagem de papel | Escolhe estrutura, gancho, percurso e payoff. Testa abertura fria com trecho tardio se ajudar. Faz lista de trechos obrigatórios e proibidos, ritmo por bloco, referências, styleframes e opções de música. |
| 06 Assembly e rough cut | Organiza a história, seleciona takes, limpa repetições, testa ordem, trata o diálogo inicial, usa B-roll para explicar ou esconder emendas. Preserva pausas com função e reação. Entrega review com timecode. |
| 07 Fine cut | Refina trims, elipses, continuidade, cortes em ação, J/L cuts, relação voz–imagem, instrumento ou gesto que conduz cada corte. Revisa velocidade natural, ritmo e legibilidade em celular. |
| 08 Picture lock e turnover | Fecha ordem e duração para acabamento. Envia timecode e handles, referência com burn-in, versões, fontes, guias e marcadores a cor, áudio, motion e VFX. Mudanças posteriores reabrem só faixas afetadas ou cortes dependentes. |
| 09 Online e acabamento | Reconecta high-res, confere frame a frame contra o offline, corrige escalas, interpreta cor, renderiza VFX/motion e consolida mix, textos e grades. Trata as entregas dependentes da cor em espaço de trabalho acordado. |
| 10 Localização e adaptações | Recompõe enquadramento, texto, voz, SFX e gráficos específicos por versão. Valida claims e idioma. Enquadra rosto, mãos e produto para cada proporção. |
| 11 QC e exportação | Reproduz o arquivo final em velocidade normal, revê trechos críticos quadro a quadro, mede vídeo e áudio, reconcilia o gráfico com a timeline, testa a reprodução no destino. |
| 12 Handoff e arquivo | Entrega master e derivados acordados, projeto + fontes, legendas, stems, versões, autorizações, checksums, relatório QC e instruções de relink. Armazena métricas somente quando autorizadas e disponíveis. |

## O que significa preparar um corte limpo

- Marcar silêncio combinando transcrição, VAD e nível de áudio, com margem antes/depois de cada palavra. Confirmar respiração, pausa cômica, reação, sotaque e sentido antes de cortar. Preencher emendas de fala com room tone ou microfades e respeitar lip sync.
- Marcar falas como gancho, contexto, prova, objeção, entrega e CTA. Pode mover um trecho para a frente quando ele tem clareza sozinho e o contexto continua verdadeiro. Cortes sugeridos mostram a frase inteira, o antes/depois e o motivo.
- Marcar pose, expressão, contato mão–objeto, foco, sombra, direção de movimento, posição no quadro, identidade, logo e claims. A técnica deve preservar a ação decisiva e remover quadros defeituosos. Câmera, captação e ruído insuficientes viram anotações de revisão, correção ou refilmagem.
- Mapear trilha em silêncios, pickups, frases, compassos, downbeats, batidas, transientes e mudanças de energia. Cortar ou marcar o gesto no evento que tem função. Cruzar waveform, audição e imagem a 1×. Evitar repetir cortes em toda batida quando isso retira clareza.

# 3. Catálogo expansível de operações, efeitos e presets

**Uma operação** é o que acontece com o plano ou faixa. **Um preset** são valores salvos. **Um template ou macro** é uma composição parametrizada. **Um overlay** é uma camada de mídia ou gráfico. **Um plugin** executa uma operação dentro de um host específico. **Uma LUT** mapeia valores de cor com domínio e finalidade definidos. **Uma receita** documenta ordem, condição e revisão. **Um perfil** parametriza formato e destino. Cada registro deve apontar sua família, dependências, licença, função e teste. A lista abaixo cobre famílias e exemplos e deve crescer com os recursos realmente disponíveis em cada motor [9–12].

| Família | Técnicas e parâmetros que o catálogo deve abranger |
|---|---|
| Montagem | Corte seco, corte em ação, match cut visual/sonoro, jump cut, insert, cutaway, cross-cut, elipse, montagem paralela, split edit J/L, multicam, continuidade de olhar, ação e ritmo, reorder e cold open. |
| Operações de timeline | Split, insert, overwrite, lift, extract, trim, ripple, roll, slip, slide, replace, source/record, grupos, faixas aninhadas, takes, sync lock, retime, markers, handles, relink e histórico. |
| Transições | Dissolve, fade/dip, wipe, iris, máscara/oclusão mascarada, whip pan, zoom/push, blur, shutter, light leak, film burn, flash, glitch, match por forma/cor/movimento, morph condicionado por continuidade e split gráfico. |
| Camadas e overlays | Textura, grão, poeira, bokeh, flare, halation, vinheta, fumaça, partículas, prismas, ilustrações, HUD, papel/colagem, overlays animados e placas alpha. Blend modes, luma, straight/premultiplied, premultiplicação e ordem. |
| Espaço, câmera e tempo | Pan/scan, keyframes, reframe com tracking, estabilização, parallax e 2.5D, escala e perspectiva, lens correction, crop, chamada de atenção, slow/fast, ramp, freeze, reverse, cadence e optical flow com inspeção de artefatos. |
| Correção e look | Gestão de cor, transformação de entrada/saída, grade primária, exposição, temperatura, curvas, grupos, matching, secundárias HSL, máscaras e tracking, pele, produto, emulação de filme, bloom, grain, dehaze, redução de ruído, render SDR/HDR. |
| VFX e composição 2D | Keying/chroma e despill, roto, mattes e edge repair, clean plate, pintura, remoção, reconstrução, tracking ponto/planar, corner pin, troca de tela, set extension, beauty retouch, passes, distorção, deformação, chromatic aberration e degradação analógica. |
| 3D e integração | Previs, solve de câmera, escala, proxy geometry, matchmove, modelagem, material, textura, rig, animação, luz/IBL e sombras, partículas e simulação, projeção, cenário, vidro/reflexos, oclusão, sombras de contato, DOF, motion blur, grão e passes AOV/OpenEXR. |
| Motion design | Logo, packshot, lettering cinético, supers, lower thirds, callouts, shape layers, morph, data viz, mapas, UI motion, títulos, comparativos, tipografia 3D, animação por curvas e templates parametrizáveis. |
| Legendas e texto | Forced alignment, segmentação por ideia, hierarquia semântica, cor/fonte de ênfase, contorno e fundo, caixas, tracking, timing palavra a palavra, grids, contraste e áreas seguras. Marcar áudio relevante em SDH quando o perfil pedir. Entregar SRT/VTT separado quando aplicável. |
| Diálogo | Sync/ADR, declick, dehum, denoise/de-reverb, plosivas, de-esser, clip gain, EQ, dinâmica, automação, room tone, crossfades, bus, sidechain e conferência em celular. |
| Música e efeitos sonoros | Spotting, BPM e compassos, ação/beat, edição e crossfade musical, stems, sidechain, hits, risers, whooshes, ambiências, Foley, som diegético, sound bridges e silêncio expressivo. |
| Mix/master | Balance diálogo/música/SFX, mono/estéreo/multicanal conforme destino, mix minus e M&E quando pedidos, LUFS/true peak por perfil, overs e compatibilidade de fase. EBU R128 é referência de broadcast, não meta automática de todas as redes [13]. |
| Restauração e acabamentos | Deband, flicker, pixel morto, estabilização, deinterlace, sharpening controlado, preservação de textura, redução de ruído temporal, compensação de compressão, safe title, conform de cores e prova no dispositivo. |
| Ferramentas generativas | Separação de stems, upscale, preenchimento, remoção e extensão, inpainting, dublagem/voz, lip sync e geração complementar quando autorizadas. Testar identidade, produto, mãos, detalhes registrados, continuidade, rastreabilidade e fallback manual. |
| Formatos especiais | HDR/SDR simultâneo, multicam, tela verde, 360/VR, estereoscopia/multiview, acessibilidade, versões multilíngues, pacotes de emissora/OTT e arquivos com alpha de acordo com contrato. |

## Receitas para decisões críticas

As seções 10 e 11 detalham calibragem musical, curadoria de SFX e integração espacial de tipografia.

- **LUT, cor e identidade:** identificar perfil por câmera/clipe. Normalizar entrada e equalizar exposição, balanço e pele. Separar look criativo de transformação de saída, documentar espaço/gama e intensidade. Analisar waveform, vectorscope e parade. Rever cor oficial, roupa escura, clipping e banding. LUT desconhecida pede prévia e identificação antes de aplicar em lote [10].
- **3D em filmagem:** decidir entre tracking planar, 2.5D ou solve 3D pelo movimento e profundidade. Fechar escala e lente, obter holdouts/oclusão, renderizar passes, casar luz, sombras, reflexos e exposição. Avaliar deslize e choque de escala em quadros distantes e em movimento [9].
- **Legenda editorial/viral:** partir da fala ou da estrutura da ideia. Destacar uma palavra pelo sentido, número, conflito ou punchline. Usar família de leitura e uma família de ênfase se aprovadas pela marca, paleta testada, quebra por bloco e hierarquia de peso/cor. Sincronizar realces à palavra e mover quando disputarem com rosto, mão, produto ou interface. Fornecer legenda limpa e acessível quando for requisito [14].
- **Overlay ou SFX de transição:** identificar o movimento, direção, intensidade, motivo e momento. Comparar corte limpo com até duas alternativas com prévia. Preservar transparência, propagação de áudio e duração do efeito. Um whoosh curto pode seguir um movimento de câmera. Um riser que atravessa a fala ou um flash que compete com o produto perde a avaliação.

# 4. Perfis de edição

| Perfil | Estrutura, ritmo e foco da revisão |
|---|---|
| Comercial de produto | Gancho de uso/benefício, demonstração, prova e packshot/CTA. Priorizar forma real, rótulo, cor, mãos e claims. Para 3D, oclusão e sombra têm precedência sobre intensidade. |
| Comercial de marca | Ideia, progressão e resolução. Localizar assinatura de marca, consistência de cor/som e plano que vai para as reduções. |
| Performance social | Abertura clara cedo, evidência de uso, payoff e ação. Reframing, legendas e área segura nativa. Testar variações de gancho sem alterar alegações. |
| Reel com fala | Construir pelo texto e pela entrega oral. Gancho de trecho tardio quando fizer sentido. Preservar respiração e humor, alternar plano e B-roll onde aumenta compreensão. |
| UGC/testemunho | Preservar espontaneidade, experiência e prova. Efeitos e retoques só quando não prejudicam autenticidade ou informação. |
| Tutorial/demonstração | Mostrar resultado, passos, precedências e erros comuns. Cortar ações repetidas sem ocultar instruções decisivas. Priorizar tela, cursor, mãos ou comparação. |
| Institucional/B2B | Problema do cliente, evidência, casos e entrevista. Checar nomes, produto, crédito, dados e confiança de leitura. |
| Festival/evento/trailer | Crescimento de energia por seção, planos humanos e escala, áudio impactante com folga de qualidade e assinatura final. Batida e frase musical governam as viradas. |
| Documental/entrevista | Clareza cronológica, reação, room tone, contexto e fontes. J/L cut a serviço do raciocínio. |
| Moda/beleza/editorial | Movimento, textura e direção de arte. Evitar pele artificial, deformação de produto e cortes que roubam o gesto. |
| Clipe/reveal/coreografia | Construir pelos gestos e pela música. Âncoras de movimento e de batida, planos fortes no downbeat, contrastes de duração e continuidade de mão/objeto. |

Desdobramentos por destino seguem guias específicos. Exemplos: gancho, corpo e fechamento em TikTok e critérios de marketing de vídeo no Google [15–16]. Estilo se decide após análise, com uma recomendação e alternativas apoiadas em planos reais. Elementos de estilos podem combinar se organização visual e áudio mantiverem coerência.

# 5. Esquadrão de edição e contratos

| Papel | Entrada | Relatório ou operação |
|---|---|---|
| Coordenação de pós e direção | Brief, material, referências, regras de marca | Entrega e versões, plano de trabalho, comparações A/B, escolha editorial e pontos de revisão. |
| Mídia, visão e continuidade | Originais, proxies, transcrição, mapa de planos | Observações com timecode, detecção de ação, oclusão, OCR, composição e defeitos, seleção de takes e intervalos proibidos. |
| Editor de narrativa | Brief, observações, falas, música | Montagem de papel, alternativas de montagem, timeline com trims, ritmo, silêncio, cold open e raccord. |
| Curador do acervo | Direção, pontos de aplicação e catálogo elegível | Opções de música, SFX, transições, overlays, fontes, presets, B-roll e LUTs. Seleção, motivo, alternativa e prévia. |
| Som e sincronismo | Fala, pistas, trilha, corte bloqueado | Limpeza, sincronismo, detecção de ataques, mix, markers e stems. |
| Cor e conform | Originais, mapa de cor, marca, referências | Grade e transformações, shot matching, conform e prova de saída. |
| Tipografia e motion | Guia de marca, falas, gráficos, áreas seguras | Styleframes, MOGRT ou equivalente, keyframes, legendas e motion por faixa. |
| VFX e 3D | Plataformas, supervisão, planos e handles | Tracking, máscaras, composição, renders/passagens e prévia de estabilidade. |
| QC e entrega | Timeline, prévia, mídia e perfil | Revisão independente com gravidade, tempo, evidência e instrução reproduzível. Master, derivados e relatório. |

Papéis podem compartilhar o mesmo modelo. Inicialmente combinar som, cor, tipografia e VFX numa coordenação de acabamento e chamar especialistas conforme exigência. Paralelizar leitura audiovisual, opções de estilo e faixas independentes. O compilador é o único serviço que aplica alterações à revision da timeline. Toda operação carrega versão-base, origem, faixa, entrada/saída, evidência, restrições e impacto. Se uma decisão conflita, o orquestrador compara propostas ou devolve a revisão ao editor. CLI e banco local persistente podem vir primeiro, com fila, retomada e cache por hash. Adoção de LangGraph ou SDK de agentes vale quando houver retomada entre sessões, aprovações assíncronas ou integrações suficientes [27].

## Como o agente enxerga o vídeo

1. **Visão global:** segmentar planos, amostrar começo/meio/fim, descrever o arco junto com áudio, reconhecer pessoa, produto, texto, enquadramento, foco e movimento.
2. **Visão densa:** decodificar a cadência original em cortes, transições, gestos rápidos, interação mão–objeto, defeitos de geração e planos de marca. Quando útil, analisar optical flow, máscaras e trajetória, com evidência visual por quadro e confiança. Uma API semântica com amostragem baixa pode perder uma anomalia breve [17].
3. **Ação temporal:** guardar arquivo e PTS de origem, faixa temporal, frame quando aplicável, posição na sequência, zona sensível e razão para o corte. Diferenciar perda de contato de oclusão real. Inspecionar o antes e depois do render.
4. **Escuta:** transcrever e alinhar palavras, sugerir pausas removíveis, localizar ambiência, pistas musicais, ataques por banda e tempo forte. Associar o acontecimento visual e o áudio. Trabalhar em relógio de origem e de saída. Um beat detector apenas gera uma hipótese de mapa.

# 6. Biblioteca Audiovisual no Drive

## Indexação e deduplicação

Configurar a pasta de destino por ID. Restringir o escopo aos diretórios autorizados. Fazer inventário com paginação, recursão, pasta de origem e atalhos autorizados. Registrar ID, revisão ou modificação, hash binário quando disponível, pasta, mídia e estado de acesso. O nome sozinho é insuficiente. Se a pasta já foi migrada, confrontar manifestos para pular os itens efetivamente copiados, retomar os faltantes e detectar revisões. Dois arquivos iguais podem ser ligados a várias origens. Mudanças posteriores por token da API, com marcação de revogação e remoção no índice [18].

Organizar a busca pela função do asset, independentemente da pasta física. Começar com SQLite/FTS, tags, filtros e thumbnails seguros. Acrescentar embeddings multimodais depois de medir o ganho em casos de busca. Manter originais, previews, catálogo de projetos e outputs fora do Git. Guardar licenças/fontes adquiridas junto do acervo e usar o Git para regras que apontam aos IDs.

## Ficha mínima do asset

ID e versão; drive/folder/file ID; nome e tipo; hash; caminho lógico; formato, taxa, cor, canais, duração/handles, resolução e alpha; função, intensidade, tags, direção de movimento e palavras correlatas; tempo da sessão, BPM e ataque/decay quando houver; licença, mídia, território, validade e permissão de redistribuição; host, plugin, versão, fontes, modelos e custo; thumbnail/waveform; histórico de uso; referência para a prova visual ou sonora.

## Regra de curadoria

1. Eliminar assets com direitos não resolvidos, formato ou host incompatível, mídia sem handles, perfil de cor indefinido para o uso, ou dependência indisponível. Se a elegibilidade faltar, registrar pendência e buscar recurso verificável.
2. Ordenar pela intenção do plano, marca, legibilidade, dinâmica, ação musical, continuidade, qualidade, custo e repetição no vídeo. Um LUT de acabamento precisa ser avaliado no material real. O registro descreve entrada/saída e intensidade.
3. Comparar o corte limpo e até duas aplicações. Preferir evidência direta na prévia. Devolver efeito, versão, faixa, intervalo, parâmetros e justificativa. Registrar por que o concorrente perdeu e como reverter.
4. Para evitar escolhas circulares, medir em uma busca rotulada se os melhores candidatos aparecem cedo, taxa de ativos incompatíveis exibidos e preferência A/B. Rankear por projeto. Aceitação para ativos sem licença ou engine verificada: zero em produção.

**Exemplo:** mudança lateral de plano do produto. Avaliar um whoosh curto que termina no contato, um corte seco e um overlay de passagem com alpha. Se o overlay encobre o rótulo ou a fala perde clareza com o SFX, preferir o corte seco. Definir parâmetros e ataque pelo evento do clipe e da trilha.

# 7. Timeline real e integração de ferramentas

**Caminho inicial recomendado:** FFmpeg/ffprobe para ingest e render de prova, Kdenlive como timeline humana, OpenTimelineIO para intercâmbio, e manifesto próprio para os recursos que o intercâmbio não cobre. Validar ida e volta com a versão alvo. Kdenlive documenta importação/exportação OTIO e usa estrutura baseada em MLT no projeto [19–22]. OTIO descreve montagem e referências. Cada adaptador tem cobertura de efeitos, transições e faixas distinta. Exportar um registro de perdas e, quando necessário, mídia com composição renderizada e handles, mantendo o original e os parâmetros.

A timeline precisa de: fonte/recorte e programa, waveform, scrubbing e navegação por quadro, split, trim, ripple, roll, slip, insert/overwrite, marcadores de erro, comentários, tracks e buses, safe zones, histórico, desfazer, relink, comparação de revisão, preview e render. Faixas esperadas: vídeo principal, B-roll, efeitos/overlay, motion, legendas; diálogo, ambiente, música, SFX. A primeira versão pode abrir a timeline num editor de verdade. Uma timeline web própria só entra depois da prova de edição e da decisão sobre colaboração, revisão e acesso remoto.

## Skills e motores avaliados

| Prioridade | Recurso | Decisão |
|---|---|---|
| Reusar | Composição de legendas editoriais e integração 3D do seu fluxo, junto com os procedimentos de edição e motion disponíveis | Usar como referências internas de execução. Validar casos de marca, tipo de timeline e compatibilidade de fonte antes de tornar padrão. |
| Adotar em piloto | HyperFrames e suas skills oficiais | Testar motion codificado, templates e composição com Node/FFmpeg. Fixar versão e testar no render real. |
| Auditar antes de clonar | gitethanwoo/video-editing | Skills candidatas de análise de edição, B-roll, produto e execução. Ler licença, scripts e dependências. Fazer prova nos próprios vídeos antes de incorporar. |
| Integrar | OpenTimelineIO, Kdenlive/MLT, FFmpeg/ffprobe | Base de montagem e exportação. Instalar como dependências separadas e fixar versões; fazer prova de ida e volta com projeto real. |
| Integrar por função | PySceneDetect, faster-whisper, MediaPipe/OpenCV, SAM 2, Beat This!, libass | Análise de planos, fala, fluxo/máscara, pulsação e legenda. Fixar versão, licença e condições dos modelos/pesos. Validar confiança e evidência. |
| Integrar por demanda | Blender, OpenColorIO/ACES, OpenFX | Blender em CLI para 3D e passes; OCIO para cor; OFX quando o host e o plugin forem compatíveis. |
| Acompanhar | OpenCut | Usar como referência ou experimento de UI. O projeto descreve recursos de API/MCP/headless como futuros na reescrita consultada. Verificar novamente antes de dependência de produção. |
| Condicional | Remotion, Adobe Premiere/After Effects, Resolve/Fusion | Remotion depende de termos aplicáveis ao uso. A integração de Adobe/Resolve depende da instalação, versão, licenças e recursos de host. Priorizar conforme o NLE usado nos projetos. |

GitHub privado organiza código, contratos, testes, adaptadores, configs e skills próprias. Usar `.agents/skills/` para instruções modulares do Codex [26], cada uma com entrada, saídas e testes. Projetos de código aberto entram como dependência ou fork apenas com licença e ganho medidos. Auditar antes de executar scripts, fixar commit/versão e registrar licença/NOTICE, recursos, versões, limites de hardware, teste-canário e fallback. Um Drive sincronizado contém arquivos de projeto e mídia. Um GitHub novo pode ser criado após escolher conta e nome. O pacote inicial pode funcionar localmente.

# 8. Roteiro de implementação e critérios de aprovação

| Fase | Entrega | Prova para avançar |
|---|---|---|
| 0. Fundamentos | Regras, skills iniciais, inventário local, contratos e validação | Localizar um clipe e validar uma decisão de corte por quadro. Casos inválidos falham com motivo. |
| 1. Do bruto à timeline | Análise de mídia, ASR, selects, mapa audiovisual, rough cut, preview e primeira entrega OTIO | Abrir no editor, mudar um corte em interface, devolver e comparar faixas, tempos, mídias e marcadores. Identificar efeitos perdidos. |
| 2. Biblioteca | Índice de pasta-piloto, previews, elegibilidade e ranking | IDs e duplicatas conferidos. Testar arquivo moved/removed, revogação e escolha com licença. Curadoria justifica a aplicação em um plano. |
| 3. Acabamento | Receitas executáveis de áudio, legenda, motion, LUT e comp | Testar logo, tom do produto, tipografia, áudio e estabilidade. Comparar prévia/render em celular e workstation. |
| 4. Operação | Fila persistente, revisões, panel/timeline web se houver ganho, novas versões | Recuperar erro/reinício sem refazer todo render e sem aplicar mudanças repetidas. Medir custo, tempo, qualidade/aceite e retrabalho por formato. |

## Quatro pilotos reais

- **Avatar e secador:** registrar o defeito como intervalo proibido. Verificar que nenhum quadro do trecho nem handles/interpolação contamina o render. Preservar os dois lados e testar insert do cabelo. Validar o corte no ataque com tolerância inicial de um quadro e assistir a 1×. No clipe já revisado, o close entra a 9,000 s e o plano aberto retorna a 9,625 s.
- **PICO:** sincronizar passos ao áudio, preservar packshot fiel, dimensionar logo e produto, conferir estabilidade de integração e oclusão, testar recorte para vertical.
- **Reel Tomorrow Travel:** encontrar gancho tardio, remover silêncio sem perder humor, testar palavra-chave em duas famílias/pesos/cores, conferir B-roll, CTAs e fala.
- **OnBio:** conferir logo, espaço de cor e embalagem, preservar texto do produto, validar versões social/comercial e revisão de claims.

## Controle de qualidade do master

Criativo: história, ritmo, legibilidade da ideia e do CTA, sincronismo, ações, continuidade, movimento, contato entre elementos, cor/pele/produto, leitura no celular, enquadramento e rasgos/manchas/artefatos. Técnico: codec e perfis, frame rate e timestamps, duração, relação de aspecto, níveis/true peak, canais, sincronismo labial, arquivo decodificado, flash, quadro preto ou repetido indevido, metadata, HDR/SDR, alpha, legendas, offsets, licenças e versões. Revisão humana em velocidade normal e conferência quadro a quadro nos pontos críticos. Perfil de emissora, digital, OTT ou web deve dizer o que medir e o que bloqueia entrega [13–14, 28].

# 9. Referências e documentação

1. [Framestore — Overwatch, Free This Weekend?](https://www.framestore.com/work/free-weekend)
2. [Framestore — Gap, Wearlight Denim](https://www.framestore.com/work/meet-wearlight-denim)
3. [Framestore — Lurpak, Where There Are Cooks](https://www.framestore.com/work/where-there-are-cooks)
4. [Clube de Criação — Natura Una, Beleza que Inspira](https://clubedecriacao.com.br/acervo/natura-una-beleza-que-inspira-galeria-natura/)
5. [AICP — Post Awards](https://aicp.com/aicp-awards/aicp-post-awards)
6. [Frame.io — Editing stages](https://workflow.frame.io/guide/editing-stages)
7. [Frame.io — Workflow guide por etapa](https://workflow.frame.io/chapters)
8. [Adobe Premiere — ingest e proxies](https://helpx.adobe.com/premiere/desktop/organize-media/ingest-proxy-workflow/ingest-and-proxy-workflow.html)
9. [Blackmagic Design — treinamento Resolve, Fusion, Color e Fairlight](https://www.blackmagicdesign.com/br/products/davinciresolve/training)
10. [SMPTE — ACES](https://www.smpte.org/standards/aces-standards)
11. [Adobe — lista de efeitos do After Effects](https://helpx.adobe.com/br/after-effects/desktop/apply-effects-and-animation-presets/effects-and-animation-presets/effect-list.html)
12. [FFmpeg — filtros](https://ffmpeg.org/ffmpeg-filters.html)
13. [EBU R128 — loudness](https://tech.ebu.ch/publications/r128)
14. [W3C WAI — acessibilidade em mídia](https://www.w3.org/WAI/media/av/)
15. [TikTok for Business — Creative Codes](https://ads.tiktok.com/business/en-US/creative-codes)
16. [Google Ads — ABCDs da publicidade em vídeo](https://support.google.com/google-ads/answer/14783551?hl=pt-BR)
17. [Google — vídeo e amostragem temporal](https://ai.google.dev/gemini-api/docs/video-understanding)
18. [Google Drive API — alterações incrementais](https://developers.google.com/workspace/drive/api/guides/manage-changes)
19. [OpenTimelineIO — código e escopo](https://github.com/AcademySoftwareFoundation/OpenTimelineIO)
20. [OpenTimelineIO — matriz de recursos](https://opentimelineio.readthedocs.io/en/v0.18.0/tutorials/feature-matrix.html)
21. [Kdenlive — funções de importação e exportação](https://docs.kdenlive.org/en/user_interface/menu/file_menu.html)
22. [KDE — formato de projeto Kdenlive/MLT](https://github.com/KDE/kdenlive/blob/master/dev-docs/fileformat.md)
23. [OpenCut — roadmap do projeto](https://github.com/OpenCut-app/OpenCut/blob/main/README.md)
24. [OpenAI Plugins — HyperFrames](https://github.com/openai/plugins/tree/main/plugins/hyperframes) e [upstream](https://github.com/heygen-com/hyperframes)
25. [Skills candidatas — gitethanwoo/video-editing](https://github.com/gitethanwoo/video-editing) e [Remotion — licença](https://www.remotion.dev/license)
26. [Codex — estrutura de skills](https://developers.openai.com/codex/skills)
27. [OpenAI Agents SDK — orquestração de agentes](https://openai.github.io/openai-agents-python/multi_agent/)
28. [Netflix — especificações e requisitos de entrega](https://studiopartner.netflix.net/studio/delivery-specifications-and-requirements-external)
29. [Blender — render em linha de comando](https://docs.blender.org/manual/en/latest/advanced/command_line/render.html) e [OpenFX](https://github.com/AcademySoftwareFoundation/openfx)
30. [PySceneDetect](https://www.scenedetect.com/docs/latest/), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [SAM 2](https://github.com/facebookresearch/sam2), [Beat This!](https://github.com/CPJKU/beat_this) e [libass](https://github.com/libass/libass)

# 10. Sound design e sincronismo de transições

Um SFX precisa ter uma função audível. O erro que o protocolo deve evitar é escolher pela categoria e colar na transição. Primeiro, assistir à versão com música e cortes. Em seguida, fazer uma sessão de spotting: marcar o que aconteceu, o que precisa ficar mais legível e em qual instante o som deve chegar. Usar os efeitos do acervo cuja origem, licença e parâmetros estejam resolvidos. Sons gerados também passam pelo mesmo teste.

## Como ler a ondulação da música

| Leitura | O que extrair | Como usar |
|---|---|---|
| Forma de onda | Amplitude, silêncio, picos, saturação e sinais de edição. | Localizar o trecho e inspecionar o ataque. O maior pico pode ser voz, ruído ou cauda do efeito. |
| Envelope de energia | Pico e RMS por janela curta e uma curva mais lenta para o arco do trecho. | Identificar preparação, subida, suspensão, chegada, queda ou retomada. Um envelope de volume só não identifica a batida. |
| Espectrograma e fluxo | Mudança espectral por banda: grave para kick/sub, médios para corpo, agudos para cliques, caixas/hats e borda do ataque. | Separar o início do golpe de sua amplitude máxima. Fazer prova de escuta por trecho e confirmar se o detector marcou o instrumento correto. |
| Pulsação musical | Beat, subdivisão, primeiro tempo do compasso, fim de frase, pausa, virada e drop. | Marcar compassos em trechos de tempo variável. Reservar viradas visualmente decisivas para eventos relevantes, incluindo cortes que ficam fora da batida por intenção. |
| Gesto visual | Primeiro movimento, maior velocidade, oclusão que esconde a emenda, contato e estabilização do plano. | Associar a posição na fonte e na sequência ao evento de som. Em gesto curto, inspeção por quadro e playback normal. |

Manter áudio em PCM de referência com amostragem conhecida. Registrar origem do relógio, offset de stream, deslocamento da trilha, janela e compensação do detector. Estimar batidas e transientes separadamente. Medir em amostras na timeline e arredondar o vídeo ao quadro compatível. Um quadro equivale a cerca de 41,7 ms a 24 fps ou 33,3 ms a 30 fps. A tolerância inicial de um quadro é um teste editorial, não uma regra de toda peça. Os guias de sincronismo e análise dão suporte ao uso de timecode e amostragem fina [31–33].

## O que sincronizar em cada efeito

| Movimento ou motivo | Ancoragem do efeito | O que faz reprovar |
|---|---|---|
| Whip, pan, wipe de primeiro plano | Abrir o whoosh antes do gesto, alinhar crista ou passagem real ao cruzamento do quadro/corte e deixar a cauda terminar com o movimento. | Sentido ou velocidade incompatível. Som longo que continua quando a imagem já parou. |
| Contato, encaixe, tampa ou packshot | Alinhar o ataque audível ao quadro de contato ou resolução. Usar Foley/material correspondente. Ajustar reflexão, panorama e distância à cena. | Hit atrasado, genérico ou forte demais. Impacto batendo junto do kick e embolando o grave. |
| Mudança de seção | Usar a curva de energia. O riser começa antes e resolve no downbeat, no drop ou no silêncio marcado. | Riser sem payoff, antecipando a revelação ou com cauda atravessando a primeira palavra. |
| Passagem discreta ou depoimento | Testar room tone, sound bridge, microfade, J/L cut ou só música. Julgar o sentido e a inteligibilidade. | Clique, buraco de ambiência, mudança de fase, efeito chamando mais atenção que a fala. |
| Transformação de objeto ou tipografia 3D | Identificar evento do objeto: entrada, apoio no chão, passagem atrás de pessoa ou movimento de câmera. Se houver som, combinar peso, espaço e perspectiva. | Som sem causa clara. Vários efeitos sobrepostos para o mesmo gesto. |

## Curadoria, mix e validação

1. **Spotting.** Salvar sequência e revisão, intervalo em quadros, ação e função, ataque do evento de música, classe do SFX e intenção. Num whoosh ou riser, guardar início, crista e fim separados. Guardar alternativa limpa.
2. **Escolha.** Filtrar origem, direitos e formato. Buscar por material, direção, distância, ataque/cauda, energia, textura e faixa de frequências. Comparar até duas alternativas ao corte com música apenas. Se ambas diminuem clareza, a montagem segue sem efeito adicional.
3. **Montagem sonora.** Aparar silêncio da fonte onde fizer sentido, alinhar o ataque interno do arquivo, automatizar clip gain e fade sem apagar a batida, mover a entrada ou saída para o efeito respirar. Dar prioridade à fala e ao gesto. Usar EQ seletivo, ducking ou som mais leve quando há mascaramento. Conferir se kick, impacto e baixo somam ou brigam. Preservar estéreo e escutar em mono.
4. **Mix.** Separar diálogo, ambiente, música, Foley e efeitos em faixas ou buses. Escutar transições em fluxo, ajustar energia por bloco e comparar A/B com volumes equivalentes. Medir LUFS e true peak conforme a entrega e conferir cliques, cortes de cauda e distorção [12–13, 31].
5. **QC.** Decodificar o MP4, medir ataque no áudio final e validar a relação com o quadro pretendido. Assistir em velocidade normal, em fone e num celular/monitor pequeno quando disponível. Ouvir um trecho antes e depois. Se a precisão numérica passar e a transição ainda soar errada, reavaliar se o evento escolhido era a batida percebida ou se o efeito tem ataque difuso, mascaramento ou antecipação inadequada.

**Exemplo da edição do secador.** No arquivo já revisado, o ataque do grave na trilha fonte está perto de 8,986 s e o close entra a 9,000 s. O desvio de 14 ms passa na janela inicial de um quadro a 24 fps. Isso valida a relação temporal medida. Adicionar whoosh ou hit precisa passar por A/B porque o ataque do grave já pode dar toda a pontuação necessária.

# 11. Visão espacial, tipografia e VFX 3D por código

O estudo começa com a distinção entre o que acompanha o quadro, o que adere a uma superfície e o que ocupa um lugar físico na cena. Classificar cada elemento por plano e reunir evidência na escala real. Uma solução 2D pode servir a uma tela ou parede. Quando o desenho pede profundidade, contato, oclusão ou reflexos, escolher um método que reproduza essa relação.

| O que se observa | Método | Prova para aprovar |
|---|---|---|
| Texto mantém posição em relação à tela, mesmo quando a câmera se move. | Overlay em coordenadas de tela. HyperFrames/CSS/GSAP, Canvas, ASS ou equivalente conforme o efeito. | Posição, área segura e leitura em celular. Não deslocar tipografia com o cenário nesse caso. |
| Texto acompanha perspectiva de tela, parede, embalagem plana ou chão. | Tracking planar e homografia/corner pin. OpenCV ou tracker de composição. | Pontos distribuídos e teste de deriva nos cantos. Máscara quando pessoa ou objeto passa pela frente. Em superfície curva ou deformável, testar outro método. |
| Letras têm volume, aparecem de outros ângulos, passam atrás de pessoas ou parecem tocar o chão. | Solve de câmera, objeto 3D, proxy geometry, iluminação, passes e composição. Blender via Python/CLI. | Parallax, largura/altura, perspectiva, contato no chão, ordem de oclusão, sombra e consistência até o fim. |
| Efeito fica preso a um produto em movimento. | Resolver câmera e movimento do produto no espaço necessário. Usar proxy/material do objeto. | Medir estabilidade relativa ao produto, em vez de estabilizar o efeito em relação à moldura. |

## Passo a passo da integração

1. **Decupar o plano.** Registrar referência, timecode de origem e montagem, FPS/PTS, recorte e reenquadramento, movimento de câmera, desfoque e fenômenos de lente. Marcar sobreposição de pessoas e produto. Aprovar volume, posição e função com um frame de referência.
2. **Rastrear e calibrar.** Coletar tracks em geometria rígida e pontos com textura. Distribuir áreas próximas e distantes. Máscaras retiram regiões móveis do solve. Tratar distorção e rolling shutter quando afetarem a aderência. Se só houver rotação, baixa paralaxe ou ausência de textura/escala, apontar a incerteza e testar homografia, reconstrução assistida ou intervenção manual.
3. **Resolver o espaço.** Revisar erro de reprojeção, alongamento e distribuição dos tracks, incluindo pontos não usados no solve. Fixar horizonte, chão, eixos, escala por medida confiável e âncora. Inspecionar grade/proxy no começo, fim e em quadros críticos. O erro médio é só uma das provas [34–35].
4. **Construir a tipografia.** Identificar família/peso provável pela forma de glifos e indicar confiança. Usar fonte licenciada ou alternativa testada. Documentar peso, tracking, altura, alinhamento e cores. Para volume, parametrizar extrusão, bevel, perfil lateral, espessura, material e animação. Manter o texto editável e testar acentos e caracteres. Reservar cor e outra fonte para palavras-chave quando a ideia pedir [37–38].
5. **Iluminar e compor.** Casar luz, cor e dureza de sombra. Criar sombras de contato, reflexos, plano receptor, holdouts de oclusão e máscara. Trabalhar com espaço de cor consistente e alpha correto. Quando necessário, exportar beauty, matte, sombra, Z/depth e IDs em OpenEXR, com motion blur, profundidade de campo, distorção e grão casados ao bruto [36].
6. **Conferir e entregar.** Fazer sobreposição de guia/tracks, inspeção de drift, escorregamento, máscara, saltos, recorte, leitura e mudança de perspectiva. Assistir ao plano todo em velocidade normal. Entregar prévia, frames de prova, arquivo de cena/script com parâmetros e passes necessários. O teste deriva da resolução e do plano. Uma referência inicial para inspeção é drift subpixel a aproximadamente 1 px em áreas estáveis, ajustado à textura, escala e saída.

## Ficha para analisar o vídeo de referência quando chegar

| Campo | Conteúdo a registrar por plano |
|---|---|
| Intervalo | Início/fim, eventos rápidos, transição anterior e posterior, suspeita de composição. |
| Som | Ataque, frase, drop/pausa, SFX e sua função, curva de energia, pontos de escuta. |
| Letras | Família provável, peso, atributos visuais observáveis, caps, tracking, cor, ênfase e trajetória. |
| Espaço | Tela, plano ou mundo 3D. Ponto fixo, horizonte, lente, paralaxe, profundidade, perspectiva e oclusores. |
| Render | Ferramenta/algoritmo, scripts, fonte, material, luz, passes e checks. |
| Evidência | Frames com timestamps, como distinguir a hipótese alternativa, grau de certeza e teste de reprodução. |

Neste estágio, o guia e o pacote estabelecem o método. O vídeo de referência vai fornecer as cenas, os efeitos e os estilos para a decupagem aplicada.

## Fontes complementares

31. [Avid Pro Tools — sincronizar áudio e vídeo](https://www.avid.com/pro-tools/audio-video-sync) e [Blackmagic — Fairlight Audio Post](https://documents.blackmagicdesign.com/UserManuals/DaVinci-Resolve-20-Fairlight-Audio-Post.pdf)
32. [librosa — detecção por fluxo espectral](https://librosa.org/doc/main/_modules/librosa/onset.html) e [Beat This! — beats e downbeats](https://github.com/CPJKU/beat_this)
33. [ITU-R BS.1770 — medição de loudness e true peak](https://www.itu.int/rec/R-REC-BS.1770/en)
34. [Adobe — 3D Camera Tracker](https://helpx.adobe.com/after-effects/desktop/work-with-3d-composition/3d-camera-tracker-effect/tracking-3d-camera-movement.html) e [Blender — Solve](https://docs.blender.org/manual/pt/latest/movie_clip/tracking/clip/toolbar/solve.html)
35. [OpenCV — Homography](https://docs.opencv.org/4.12.0/d9/dab/tutorial_homography.html)
36. [Blender — passes de render, Shadow Catcher e Cryptomatte](https://docs.blender.org/manual/en/latest/render/layers/passes.html)
37. [Blender — tipografia, extrusão e bevel](https://docs.blender.org/manual/en/3.0/modeling/texts/properties.html)
38. [HyperFrames — CLI de render](https://github.com/heygen-com/hyperframes/blob/main/docs/packages/cli.mdx)
