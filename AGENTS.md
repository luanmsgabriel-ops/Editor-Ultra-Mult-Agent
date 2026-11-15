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
