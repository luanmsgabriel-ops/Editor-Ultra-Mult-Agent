---
name: inspecionar-video
description: Inventariar e interpretar vídeos brutos, referências e áudio com evidências e timecodes de planos, gestos, palavras, enquadramento e defeitos.
---
1. Rode `python -m audiovisual inventory <arquivo-ou-pasta>` para obter hashes, streams e parâmetros técnicos.
2. Marque cenas, ações, enquadramento, movimentos, continuidade, fala, ruído, música, objetos e possíveis enquadramentos de saída. Transcreva com tempos quando a ferramenta disponível permitir.
3. Examine em quadros nativos as regiões de dúvida e protótipos de corte. Diferencie oclusão legítima, rastreamento incerto e defeito confirmado.
4. Entregue por cena arquivo e revisão, in/out da fonte, descrição, evidência, confiança e possível uso. Para defeitos confirmados, marque intervalos proibidos e margem de segurança.
