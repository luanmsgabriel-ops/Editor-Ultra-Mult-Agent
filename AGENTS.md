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
