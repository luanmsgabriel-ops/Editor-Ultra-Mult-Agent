---
name: montar-timeline
description: Montar e revisar timeline a partir dos brutos, ajustando fala, ação, música, silêncio, continuidade e trechos proibidos em quadros.
---
1. Fixe taxa racional, resolução, timebase, faixa principal e tolerância de sincronismo. Separe os tempos da fonte dos tempos da sequência.
2. Escolha in/out por clareza da ação. Aplique cortes de silêncio com proteção de pausas e fonemas. Identifique onsets, pulsos, tempos fortes e frases por finalidade.
3. Conte a história no corte bruto. Use jump cuts, match cuts, inserts, J/L cuts e mudanças de duração somente quando servirem à direção de montagem.
4. Meça a sincronização prevista, registre os handles usados e rode `python -m audiovisual validate <timeline.json>` para a faixa principal quando ela se enquadrar no contrato da CLI.
