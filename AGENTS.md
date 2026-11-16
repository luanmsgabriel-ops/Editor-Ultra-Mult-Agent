# Pós-produção audiovisual

1. Preserve os originais e registre permissões, revisão, identidade e vínculo com os proxies. Trabalhe com assets e saídas em pastas distintas.
2. Use as skills conforme a etapa. Em paralelo, cada agente entrega observações e propostas independentes. O editor responsável concilia mudanças e atualiza a timeline versionada.
3. Assista ao bruto em contexto. Aumente a amostragem perto de gestos rápidos, trocas de mão, emendas, problemas de continuidade e cortes propostos. Registre arquivo, faixa de quadros, evidência e nível de certeza.
4. Defina objetivo, público, formato, referência e destino. Proponha alternativas editoriais úteis, com exemplos do próprio material e ponto de vista justificado.
5. Valide a montagem antes de acabamento. Depois que a ordem e a duração estiverem alinhadas, coordene cor, áudio, motion, legendas e VFX pela mesma revisão da timeline.
6. Use arquivos e direitos verificados. Mantenha um log de seleções e versões. Preserve identificadores e controles editáveis. Entregue timecodes de revisão, export e mapa de cortes.
7. Comprove o resultado no arquivo efetivamente entregue. Lembre que igualdade dimensional e verificação do JSON não substituem a reprodução audiovisual.

8. Em transições, anote o ponto musical e o ponto do gesto em seus respectivos relógios. Decida se a trilha já dá a pontuação. Teste o SFX com e sem o efeito e confira ataque e mix no render.
9. Em tipografia e objetos espaciais, classifique tela, plano ou volume por evidência visual. Confira ponto de fixação, oclusão, luz, perspectiva e estabilidade no intervalo inteiro.

## Orquestração no Codex

Peça a decupagem e análise musical em paralelo. Depois que a direção fixar os beats narrativos, divida curadoria, cor, motion e VFX por faixas. A montagem tem um responsável e recebe propostas identificadas por revisão. Use os agentes de `.codex/agents` e as skills de `.agents/skills`. Rode o validador de timeline e faça o QC sobre a exportação, além do plano. Marque no relatório cada fallback, como adequação manual de câmera ou audição sem confirmação perceptiva.

Antes de consumir ativos de um projeto, registre raízes, IDs e vínculos de pasta. Limite a busca ao escopo solicitado. Mantenha mídia, o catálogo privado e credenciais fora do Git. Em prévia privada autorizada, informe o que depende de licença para um uso futuro. A marcação de acesso à pasta não confirma direitos de publicação.

Para reaplicar motion tipográfico e gráficos a novos brutos, use `python -m visual_fidelity anchor render` e entregue o relatório junto do render. Escolha âncora de tela, planar ou 3D a partir do papel do efeito. Preserve o enquadramento, proteja rostos e texto já embutido nas amostras e revise regiões sem detecção confiável. Use `glyph-profile` para transportar curvas por letra entre palavras e indique quais âncoras perderam o rastreamento ou precisaram de marcação por plano.

Quando o efeito acompanha uma pessoa, use `body-pose` para ancorar nos pontos anatômicos ou `anchor render --body-model` para resolver o movimento junto da composição. Para texto que gira em volta de alguém, use o modo `orbit`, valide a máscara de oclusão e revise a troca de plano ou perda de pose. Registre o quadro de gestos usados como gatilho.

Ao analisar um vídeo de referência, registre também transições, tratamentos de cor, overlays e eventos sonoros que possam ser reaplicados. Consulte a [biblioteca de efeitos](https://drive.google.com/drive/folders/1f3oYF6f1JP1BZVZ2HVkAq7I6I-q-evJC), leia o índice e reúna os achados por quadro. Reuse fichas existentes e salve cada técnica nova com prévia, parâmetros ou código, origem e versão. Quando houver acesso ao Drive, envie à categoria e atualize o catálogo com links verificados. Guarde sons próprios e autorizados isolados do mix, com a proveniência. Em interface, priorize a captura da janela do app e use a auditoria de movimento para conferir os quadros-chave.

Quando o objetivo for clonar uma referência completa, entregue uma reconstrução contínua com os planos, transições e eventos na timeline. Use a mesma cadência da referência no comparativo lado a lado. Rode `python -m visual_fidelity timeline-qa` no render final e registre desvios em quadros, priorizando os trechos com maior divergência perceptível. Uma ficha individual da biblioteca serve para reutilização. A verificação da montagem acontece na sequência completa.

Para reconstrução de ambientes com volume, use `scene3d prepare`, `scene3d infer` e `scene3d render`. Escolha MoGe para a vista única e VGGT para vistas de um plano contínuo. Carregue no Blender/Cycles a geometria e a câmera do mesmo raster, registre escala, confiança e regiões ocultas. Revise a projeção antes de calibrar materiais e luz. Consulte `visual_fidelity/SCENE3D.md` e registre separadamente o que teve inferência real e o que passou apenas por teste de contrato.

## Assets híbridos e reconstrução fiel

Ao receber um vídeo de referência, avalie quais elementos podem ser reconstruídos por código/3D e quais ganham fidelidade como imagens geradas. O usuário autorizou gerar no próprio chat imagens sem fundo para silhuetas, ilustrações, ícones e outros elementos difíceis de reproduzir proceduralmente, e incorporá-las à edição. Preserve alpha real, registre prompt e referência e guarde o asset junto do projeto. Para GIFs e pequenos loops, anime imagens ou sequências por uma ferramenta adequada e exporte o arquivo; não prometa que um gerador de imagem estática gera animação.

Escolha o método pelo movimento: uma imagem gerada pode servir como elemento gráfico ou camada com perspectiva; um cenário cuja câmera revela profundidade exige geometria e câmera 3D animada durante todo o plano. Não substitua esse movimento por zoom/rotação de um render estático. Identifique a entrega como híbrida quando incorporar imagens geradas; não a chame de inteiramente procedural.

Para uma referência rejeitada por falta de fidelidade, valide primeiro os trechos críticos (por exemplo cenário com câmera e um ícone), comparando silhueta, perspectiva, material, iluminação e trajetória em vários quadros. Testes de código, duração correta e instalação de modelos não equivalem a fidelidade visual. Diferencie medições, ajustes manuais, inferências e limitações remanescentes.

## Tipografia híbrida e fontes reutilizáveis

Para recriar tipografia de vídeos, procure primeiro identificar a fonte original e separar desenho, espaçamento, perspectiva e efeitos. Quando o título for uma palavra fixa com conexões ou floreios próprios, preserve também um lettering vetorial separado. Não trate um lettering de poucas palavras como alfabeto completo.

Se a fonte não puder ser identificada, o usuário autorizou gerar imagens de letras com fundo transparente, tomando quadros nítidos como referência, e transformá-las em uma fonte instalável. A geração é uma etapa: vetorize, refine curvas, normalize altura, largura, linha de base, peso e espaçamento, mapeie Unicode e construa TTF/OTF com métricas e kerning. Inclua acentos de português, números e pontuação conforme a cobertura declarada. Valide o arquivo com renderização de palavras e frases, não apenas com a existência do arquivo.

Registre caracteres observados, reconstruídos e inferidos; preserve atlas, prompt, vetores, cobertura, versão e limitações. Letras ausentes ou ocultas são interpretações, não recuperações exatas da fonte original. Fontes experimentais devem ser identificadas como tais. Materiais, extrusão, luz e animação permanecem separados do desenho tipográfico. Guarde a fonte reutilizável e o lettering específico de cada cena no catálogo do projeto. Imagens e fontes derivadas permanecem no pacote de mídia; scripts e documentação podem ficar no Git.

O protótipo em `typography_lab/scripts/build_font.py` gera uma TTF real a partir do atlas documentado; consulte `typography_lab/README.md` antes de reutilizar em outra referência.


## Aprendizado obrigatório no motor de motion

Ao receber uma correção visual, registre defeito, causa, componente reutilizável, teste e evidência. Implemente a técnica no pacote visual_fidelity e use esse mesmo componente no adaptador do vídeo. Não deixe a correção apenas no render privado nem apenas em instruções.

Consulte visual_fidelity/MOTION_KIT.md e execute `python -m visual_fidelity motion-kit list` antes de reconstruir órbitas, brilhos, tipografia curva, palavras sobrepostas, alvos animados ou molduras metálicas. O projeto deve fixar a versão do motor e validar o manifesto pelo comando `motion-kit check`.

Separe palavras inteiras de máscaras de visibilidade; contornos extraídos de letras ocultas são fragmentos e exigem reconstrução declarada antes de reutilização como palavra completa. Preserve kerning e avanços reais ao distribuir letras em curvas. Brilho deve seguir a superfície e seu alpha. Órbitas precisam de profundidade/oclusão; objetos com movimento próprio devem ter hierarquia e controles separados. Molduras metálicas precisam de silhueta, relevo, material e iluminação, preservando o conteúdo aprovado.

As seis rejeições da revisão 329687 V6 são casos de regressão, não um estilo obrigatório para todo vídeo. Use o desenho, ritmo e materiais da nova referência. Fontes substitutas, movimento ajustado, 2,5D e ausência de playback perceptivo devem permanecer declarados. Só marque aprovado pelo usuário após confirmação real.


## Reedição de bruto curto no estilo de uma referência

Para recortar pessoa/cadeira e remontar em uma timeline híbrida, consulte `visual_fidelity/STUDIO_EDIT.md` e execute `python -m visual_fidelity studio-edit`. A versão 0.8.0 reutiliza as primitivas do motion-kit 0.7.0, com manifesto, relógios de fonte explícitos, alpha temporal supervisionado e relatório dos hashes realmente importados. Não substitua a execução por imagens de demonstração.

Quando o usuário autorizar estender o material, mantenha as falas originais em cláusulas completas e use cenas gráficas, recortes e reutilização visual declarada. Preserve sincronismo nos trechos em que o rosto e a fala coexistem. Revise V/U e acentos da fonte em palavras reais, contraste, crop facial, ampliação óptica da lupa e fechamento coerente com a fala. Uma sequência de fundo 3D não transforma o recorte da pessoa em geometria 3D.


## Pacote fixo por referência: rejeição da adaptação Clara

A adaptação Clara de 47 segundos foi REJEITADA. A versão V7 anterior também não tem aprovação visual global. Não usar testes de código, duração correta ou ausência de quadros pretos como prova de fidelidade.

Antes de reutilizar a referência 329687, carregar a pasta https://drive.google.com/drive/folders/1kPgwgsaby5YUwEogAZVpJkVmolrhD5Z5 e o seu MAPA-DE-MONTAGEM.md, AUDITORIA-DE-FIDELIDADE.md e bundle.json. Extrair o pacote completo preservando caminhos. Executar `python -m visual_fidelity reference-bundle verify bundle.json --root CAMINHO` antes de adaptar.

Reutilizar os mesmos assets, fontes, módulos ativos, parâmetros, ordem de camadas e relógios. Não substituir painéis de vidro por cartões planos, não remover folhagem, não reduzir a sequência relatório/presente/computador a um objeto. Traduzir textos em camadas separadas ou em variantes localizadas versionadas, preservando desenho/material/perspectiva; nunca recriar toda a composição para trocar letras. Copiar bytes sem conservar os bindings por cena também não atende ao pedido.

Antes de exportar a adaptação inteira, comparar cenas críticas da lupa, órbita e arquitetura com o original. Mudanças de assets ou da receita exigem nova versão identificada e evidência visual; não sobrescrever a base. O verificador detecta alterações e ausências, mas não mede estética, câmera ou identidade visual automaticamente.


## Reaplicação PT2: preservar composição, plano e movimento

A revisão Clara PT2 usa `examples/reference_replays/329687_pt2/` e `visual_fidelity/reference_replay.py`, com pacote de mídia em https://drive.google.com/drive/folders/1gzaDgUdLVcnVOkR-ONPM8csCRCd6vzgz. A revisão Clara PT2 foi APROVADA pelo usuário: “Agora sim, ficou perfeito vou te mandar um novo vídeo”. SHA-256 do render aprovado: `34e2c8926a821d53933a65661d6de053c375d1737d299248e02b2f5e37c22d4d`. Registro externo `APROVACAO-PT2.json` na pasta; manter pacote congelado e rejeições anteriores separados.

Na troca de pessoa, conservar plano aberto versus close, inserir a pessoa e sua cadeira como uma única camada, separar transformação final de tela da câmera global e manter oclusores de mesa em primeiro plano. O relógio explícito deve preservar a fala em ambos os lados de cada corte. Não repetir quadros de origem silenciosamente.

Na troca de idioma, conservar composição de fontes, cursivas reais, hierarquia, palavras completas e perspectiva. Usar a mesma câmera do cenário para reprojetar lettering na parede. Conferir a velocidade e a entrada da órbita em vários quadros; um quadro parecido não comprova movimento parecido. Gerar variantes de assets apenas quando necessário, manter alpha, prompt, proveniência e versões. Salvar render, comparação, manifesto e instruções de encaixe junto dos materiais reutilizáveis.


## Reconstrução geométrica por camadas: referência 329796

Use `visual_fidelity/geometric_replay.py` versão 1.0.1 para faixas horizontais/verticais, X, polígonos, máscaras suaves, keyframes e composição com recorte em primeiro plano. A referência 329796 está em `examples/reference_replays/329796_geometric/`; pacote e mídia: https://drive.google.com/drive/folders/1YakP-w83hT2rQrmsKyDXm8KtZSawFJbT. A aprovação visual está PENDENTE e não se transfere da Clara PT2.

Quando só existir o MP4 final, declare a recomposição de pixels fotográficos recuperados, marque regiões ocultas inferidas e mantenha a geometria independente dos assets. A comparação usando pixels da referência não prova generalização. Gere uma prova adicional trocando as fontes pelas mesmas máscaras/tempos. Para um novo bruto, refaça os recortes e reancore portais como viseiras; não reutilize coordenadas de uma pessoa como rastreamento de outra.

Em transições suaves, `decompose_observed` restringe a base aproximada ao intervalo de cor que permite uma inserção sem clipping. A correção da emenda clara da colagem 180/195 foi incorporada ao motor e tem teste de regressão. A decomposição é não única; não a descreva como recuperação exata do material oculto. Preserve os parâmetros, camadas, áudio, proveniência, instruções e hashes no pacote. Não imponha fontes ou estética de referências anteriores a um vídeo sem tipografia.


## Aplicação geométrica a bruto novo: 330494

Use `visual_fidelity/geometric_video.py` 1.0.1 e o adaptador `examples/reference_replays/330494_application/`. Pacote completo: https://drive.google.com/drive/folders/1wYeiImVXB2dVG_2hi1622S23iWt_yEd4. Aprovação do usuário pendente.

Refaça mattes de sujeito e viseira para cada bruto. Aplique exatamente o mesmo viewport ao vídeo e à máscara; redimensione recortes com alpha premultiplicado e ajuste a inserção à caixa da máscara do portal. Preserve relógios explícitos, proporção e hashes reais. Reutilize geometria e tempos da referência, sem transportar seus pixels fotográficos. Se faltar fundo, gere clean plate documentado com prompt/proveniência e preserve o original. Mantenha novos assets, máscaras, timeline, dependências, código e instruções juntos. A trilha de referência usada em teste privado permanece identificada separadamente. Testes e decodificação não equivalem a aprovação estética; registre serrilhado, limitações de ampliação e ausência de audição confirmada.


## Regressão330494V1: ritmo e cobertura de imagens

A aplicação330494V1 foi rejeitada pelo usuário por estar fora do ritmo e repetir crops do bruto/fundo vazio. A revisãoV2 usa geometric_video1.1.0, music_sync1.0.1 e edit_contract1.0.0; ler visual_fidelity/REFERENCE_PLANNING.md e MUSIC_SYNC.md. PacoteV2: https://drive.google.com/drive/folders/11-iMF3gBOBdxRS9uD6RPgFVusPeYr1Z5. Aprovação estética pendente.

Antes de adaptar, analisar quais conteúdos aparecem dentro de cada máscara e colagem; criar asset_plan com evidência, papel, intervalo, fonte/reuso/geração e movimento necessário. Gerar complementos autorizados quando o bruto não possui os ângulos/cenários; guardar prompt, identidade de referência, proveniência e arquivo. O validador confirma consumo de assets, não entende semântica sozinho. Revisar visualmente. Não confundir fotografia2D animada com novo vídeo3D. Não usar foto que já contém pessoa como fundo de colagem sem verificar duplicações sobrepostas.

A música comanda o tempo de start/apex/reveal/cut/resolve. Usar analyze_audio no PCM com trim/velocidade reais, separar textura/transiente/retorno de energia e não inventar BPM quando houver ambiguidade. Usar schedule_events com janelas e espaçamentos; remover ciclos arbitrários de troca a cadaNframes. Manter fonte, matte e viewport juntos ao retimar. edited_audio_filter compartilhado evita atempo=1, que causava deslocamento mesmo com velocidade nominalunitária. Conferir o áudio do MP4 codificado contra o clock planejado e os ápices visuais no arquivo entregue. Guardar métricas de quantização separadas de revisão perceptiva, nunca alegar audição não realizada. Não transfira aprovação de outra referência.

## Medição e reaplicação da cadência

Use `python -m visual_fidelity reference-cadence analyze` para medir batidas com Beat This!, cortes candidatos com TransNetV2 e movimento regional com RAFT. Confirme quais cortes são trocas de plano, trocas dentro das máscaras ou falsos positivos. Salve os marcos revisados, o mapa e os pesos identificados. Use `reference-cadence apply` para transferir tempos, fase musical ou máscaras medidas aos assets do novo bruto. Leia `visual_fidelity/REFERENCE_CADENCE.md`. Revise um trecho representativo com áudio antes de expandir para toda a montagem. A V2 da aplicação 330494 foi rejeitada por ritmo, velocidade dos cortes e aparência.

## Leitura e reaplicação de efeitos em camadas

Quando uma máscara composta tem formas independentes, preserve a identidade de cada forma. Use `reference-layers analyze` para ler a oclusão, detectar mudanças de conteúdo por faixa e guardar as evidências. Use `reference-layers apply` após compilar a cadência, com a paleta de imagens e os recortes do novo sujeito. Valide profundidade e trocas no render. Consulte `visual_fidelity/REFERENCE_LAYERS.md`.

## Aplicação de estilo ao bruto novo

Ao receber um bruto novo com pedido para aplicar a Clara PT2, use `python -m visual_fidelity contextual-edit`, conforme `docs/contextual-editing.md`. A Clara passa a fornecer paleta, hierarquia de fontes e linguagem de animação. Defina momentos, enquadramentos, gráficos e textos a partir da fala, das imagens e dos pontos rastreados no bruto. Em close ou corpo cortado, mantenha o enquadramento real e proteja rosto e mãos no decorrer do plano. Para inserir algo no ambiente, use âncora planar ou câmera com evidência medida. Se um ícone precisar ser criado, use o conceito sustentado pela fala e registre o arquivo com transparência e proveniência. `adaptive-template` e `visual_fidelity/ADAPTIVE_TEMPLATE.md` preservam o fluxo específico anterior, sem representar a direção semântica geral. O render fixo de 329687 PT2 serve para reproduzir a edição aprovada com a Clara.

Ao reaplicar a Clara PT2, escolha a montagem de cada trecho pelo que ele precisa comunicar. Use revelação tipográfica para o gancho, cenas gráficas separadas para explicar conceitos ou números, e assinatura no gesto quando houver rastreamento que sustente o timing. Confirme no MP4 que há mudanças de composição e que cada tela tem função narrativa. Repetir tarjetas no topo com palavras da transcrição não reproduz a linguagem de motion da Clara.

Quando a referência pedir letras orbitais ou interação com as mãos, use o rastreamento e o alpha do próprio bruto. Prepare os recursos com os detectores existentes e forneça-os ao fluxo contextual via `--pose` e `--mattes`. Verifique a parte dianteira, a parte traseira e o trecho coberto pelo corpo. Acompanhe a palma quando a detecção está presente. Se faltar profundidade observável ou continuidade da mão, registre o requisito ausente e proponha uma revisão explícita; não converta o efeito espacial em uma composição de tela silenciosamente.

## Direção contextual, execução e revisão

Para novas edições, o coordenador mantém um único dono da timeline. Decupagem, motion, som e QC entregam observações ou propostas estruturadas. `editorial_engine` recebe análise, catálogo e candidatos explícitos; não interpreta palavras-chave como intenção. Use `prepare` para evidências e recursos, `request` para o pacote de direção, `plan` para conciliação, `render` para a prova real, `review` para registrar o que foi efetivamente conferido e `patch` para correções localizadas.

Analise oportunidades de fala, gesto, corpo, espaço, demonstração, revelação, contraste e som. Registre as úteis e o motivo de atendê-las ou deixá-las pendentes. Não use quantidade de efeitos como pontuação de qualidade. Não limite automaticamente as opções a tarjetas acima da cabeça. O catálogo é um vocabulário de funções, requisitos e operações; cada escolha precisa de evidência semântica e viabilidade técnica no intervalo completo.

O agente no host pode assistir à fonte e escrever `direction.json`; `direct` também oferece um adaptador para endpoint multimodal explicitamente configurado. Frames amostrados não comprovam movimento contínuo. Uma transcrição não comprova escuta. Atestação de arquivo e SHA não comprovam significado ou qualidade. Capacidade desconhecida, arquivo alterado, região ocupada, âncora inválida ou operação não implementada bloqueiam a execução correspondente.

Preserve o estado de revisão e o histórico retornados pelos patches. Não reinicialize estados para contornar o limite de correções. Um relatório fica vinculado à versão do plano e aos bytes do render; mudar qualquer um invalida a aprovação anterior. Testes, hashes, decodificação, contagem de frames e validação de grafo permanecem verificações técnicas. Aprovação visual, áudio ouvido e confirmação do usuário precisam de registros próprios.

Para SFX, use `audiovisual.semantic_audio` com índice real e CLAP local quando os pesos/dependências estiverem disponíveis. Ausência de embeddings deve continuar declarada; não substituir busca semântica por nome de arquivo. Registre ataque/apex revisado, trim e taxa de amostragem. O mix nativo reduz SFX pelo mix original, que pode incluir música; isso não demonstra isolamento de voz ou inteligibilidade. Receitas e orçamento em `editorial_engine.workflows` executam somente por callback configurado, com reserva prévia e recuperação de jobs sem repetição automática.
