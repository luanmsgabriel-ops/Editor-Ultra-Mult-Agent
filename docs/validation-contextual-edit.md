# Validação da direção contextual — 16/11/2026

Base do trabalho: commit `e08c23b1ec45bcee410121d8e6f54ce9a34ecbb8` do Editor Ultra Multi-Agent. A implementação acrescenta direção explícita, conciliação de propostas, catálogo executável, integração com a composição existente, busca semântica opcional de áudio, revisão vinculada ao render e ledger de receitas.

## Resultado executado

```bash
python -m pytest -q tests extensions
```

**315 testes passaram, incluindo 30 subcasos, em 25,12 segundos.** Houve dois avisos de depreciação: um plugin de pytest do ambiente e o uso anterior de `Image.getdata` em um teste existente. Nenhum teste falhou ou foi omitido nessa execução. Ambiente: Python 3.12.14, FFmpeg 7.1.5; pytest 9.2.0 foi instalado a partir do cache disponível para executar os testes de função já existentes.

Também foram carregados os cinco arquivos TOML de papéis atualizados, analisados 12 exemplos de CLI pelo parser real e verificados os links locais dos manuais. `git diff --check` não identificou erros de espaços.

## O que as provas demonstraram

| Área | Evidência executada |
| --- | --- |
| Seleção | Intervenções exigem fonte, intervalo, evidências, parâmetros e capacidades. Alto score não supera requisito ausente. Áudio e imagem complementares podem coexistir. Preservação exige decisão explícita. |
| Integridade | Hash alterado, fonte incompatível, recurso não vinculado, relógio de outra montagem e plano não executável impedem a operação correspondente. |
| Direção | O pedido contém pixels reais amostrados e previews de assets. Anotação de frame que o provider não recebeu é rejeitada. A chamada HTTP foi exercitada somente com resposta injetada no limite de transporte. |
| Composição | Renders sintéticos reais mostram o gráfico no intervalo reservado, proteção do sujeito, animações contidas na região e imagem atrás de máscara real. |
| Mão e corpo | Renders reais de fixture comprovam acento seguindo uma palma e órbita com passagens dianteira/traseira e oclusão. Perda de tracking bloqueia o render, sem alternativa automática. |
| Máscaras existentes | Sequência declarada em 160×240 é normalizada explicitamente para a fonte 320×480, com hashes dos frames usados e conservação das máscaras originais. |
| Áudio | Impulso a 44.100 Hz, reamostrado para 48.000 Hz, atinge a amostra prevista após trim e delay. Intervalos menores que um frame e descarte explícito de pré-roll negativo funcionam no relógio de áudio. |
| Mix | Há testes reais de ducking, preservação da trilha original, fonte sem áudio, limiter com seis impactos simultâneos, identidade dos pacotes de vídeo e padding da entrega AAC. |
| Receitas | Bindings e dependências inválidos bloqueiam. Jobs idênticos não repetem execução; estado desconhecido exige reconciliação. Reservas concorrentes respeitam o teto; custo real não é contabilizado duas vezes. |
| Revisão | Plano e render têm identidade verificada. Mudança invalida revisão anterior; patch é localizado e consome tentativa. Teste técnico não registra aprovação do usuário. |

O ensaio espacial usa fonte de 24 frames a 20 fps. Os testes verificam fonte intacta, relógio e posição de um marcador no torso em três momentos. A comparação de cor admite variação de até quatro níveis por H.264; a posição é conferida separadamente. No ensaio orbital, o título curto sem oclusão suficiente é recusado antes de uma variante que satisfaz as cinco medições. Esses casos validam o comportamento do adaptador sobre geometria conhecida.

A integração encontrou e corrigiu uma incompatibilidade: o relógio racional chegava à função de animação como `Fraction`, que OpenCV não aceita como ângulo. O cálculo da animação agora usa tempo numérico, enquanto o encoder conserva o FPS racional original.

## Limites que permanecem explícitos

As direções das fixtures são declarações sintéticas conhecidas. **Não foi avaliado um modelo escolhendo a edição de uma filmagem real.** Não houve chamada a endpoint multimodal externo, execução dos seis clones pesquisados, geração externa de vídeo, download de pesos ou uso de GPU paga.

O probe de áudio confirmou `torch` e `transformers` ausentes. CLAP permanece `unavailable`; o índice técnico não é apresentado como índice semântico. Vetores injetados testam a fronteira de recuperação, sem demonstrar qualidade do modelo.

As provas usam pixels e PCM reais, mas não representam julgamento estético, audição humana, inteligibilidade comprovada ou aprovação do usuário. O ducking reage ao mix original, que pode conter música; não isola voz. A precisão em amostras é conferida no PCM anterior à codificação; a saída AAC tem análise própria de padding.

O adaptador nativo cobre uma fonte CFR no relógio original. Remontagem de várias fontes, retime e geração de planos exigem adaptadores e mapas explícitos. A disponibilidade dos recursos vem do host; o ledger executa callbacks configurados, sem fornecedor externo predefinido.

## Referências de implementação

- [Guia operacional](contextual-editing.md).
- [Pesquisa e decisão sobre os seis projetos semelhantes ao Higgsfield](higgsfield-reuse.md).
- [Testes de percurso completo](../tests/test_contextual_edit.py).
- [Testes espaciais](../tests/test_contextual_spatial.py).
- [Testes de áudio e casos menores que um frame](../tests/test_editorial_audio_render.py), [casos de relógio](../tests/test_contextual_audio_edge.py).
