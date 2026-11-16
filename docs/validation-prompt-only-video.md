# Política de vídeo: exportação de prompts

Correção solicitada pelo usuário em 16/11/2026: toda geração de vídeo deve entregar os prompts conforme a direção, para execução externa na ferramenta escolhida por ele. O vínculo com um serviço e seu seletor de aparência não pertence a esse fluxo.

## O que foi corrigido

- A política `video-generation-execution-policy/1` acompanha briefing, pedido ao diretor, prompt pack e estado do projeto. O modo é `prompt_export_only`, com geração automática desativada.
- A exportação neutra não pede ferramenta nem perfil. Incompatibilidades de um perfil opcional, referências ausentes e retornos de continuidade ainda não recebidos permanecem explícitos.
- `external_video` exporta o pedido mesmo quando recebe um callback; não chama o gerador nem reserva créditos. Operações desconhecidas que produziriam vídeo precisam de classificação local no registro confiável do host.
- Contratos de workflow explicitamente declarados como geração de vídeo são bloqueados antes da execução. Jobs históricos pendentes mantêm identidade, estado e reserva, inclusive quando a retomada usa outro diretório.
- Recebimento de MP4 externo, montagem, templates, motion, 3D, composição e processamento local continuam disponíveis. O endpoint de direção retorna texto estruturado; ele não sintetiza vídeo.
- Os prompts distinguem duração de cada tomada da duração/FPS/raster da etapa inteira depois da montagem e conformação.

## Verificação executada

Foram executados **139 testes e 8 subtestes**, em alvos ligados à mudança. Não foi executada a suíte inteira do repositório nesta correção.

| Alvos | Resultado |
| --- | --- |
| `test_generation_prompts`, `test_generation_direction`, `test_recreation_project`, `test_production`, `test_generation_workflow`, `test_clone_project` | 90 testes e 8 subtestes aprovados |
| `test_video_generation_policy` | 11 testes aprovados |
| `test_editorial_workflows`, `test_planar_portal_production`, `test_project_shot_design` | 38 testes aprovados |

Os novos testes usam callbacks sentinela para provar que a rota de geração não os invoca, verificam ausência de reserva de custo e exercitam importação de MP4 e render local reais com FFmpeg. Também cobrem tentativa de alterar a política via JSON e preservação de execução histórica desconhecida. A conferência textual verifica que o diretor recebe a política e que prompts neutros podem ser exportados sem exigir fornecedor.

Houve um aviso de depreciação do plugin AnyIO/pytest no ambiente; nenhum teste falhou. `git diff --check` não apontou problemas de whitespace.

## Limites desta evidência

Nenhum gerador de vídeo foi chamado. Os arquivos de mídia dos testes são fixtures locais identificadas. Validação de contratos e bytes não comprova identidade, naturalidade dos gestos, continuidade perceptiva ou aprovação audiovisual.

A classificação de processamento local é uma declaração confiada ao host, não uma sandbox que analisa qualquer função Python. A política controla as rotas e contratos de geração oferecidos pelo motor. A direção continua autorada e revisável; capacidade não consultada não passa a ser verdadeira pela presença no prompt.
