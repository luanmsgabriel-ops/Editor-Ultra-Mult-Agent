# Validação da camada de direção e prompts de vídeo

**Data:** 16/11/2026.

**Base anterior:** `8745c6f62b032d74dede7d5bce668f4f0a961f02`.

**Resultado da suíte integrada:** 453 testes principais e 42 subtestes passaram; zero falhas e zero testes pulados. Tempo observado: 61,95 s.

```bash
python -m pytest -q tests extensions --junitxml=/workspace/scratch/e6d35dc1eceb/generation-integration-tests.xml
```

O JUnit local contém 495 casos contando os subtestes. Dois avisos de depreciação já existentes permanecem: AnyIO/Pytest `CallSpec2` e Pillow `getdata`. Eles não são falhas de geração nem de execução audiovisual.

## Cobertura nova

| Arquivo | Testes principais | O que foi exercitado |
| --- | ---: | --- |
| `test_generation_contracts.py` | 11 | Duração com sobreposições, dono de cada fronteira, imagem compartilhada, cobertura de planos, retenção de fala/pós, evidência e invalidação localizada/global/dependente |
| `test_generation_direction.py` | 14 | Precedência de respostas, perguntas condicionais, ferramenta indefinida, perfil sem revisão herdada, schema completo, evidências e arquivos alterados |
| `test_generation_prompts.py` | 26 | Prompts independentes, perfis, duração/formatos/entradas, arquivos ausentes ou inválidos, teto de texto, áudio, recursos de pós e dependências |
| `test_generation_ingest.py` | 25 | MP4 real, FPS e PTS racionais, extração e comparação de pixels, adulterações, VFR, duração visual/áudio, seleção antecipada, formato/rotação/SAR, extensão e escopo da observação |
| `test_generation_workflow.py` | 3 | Encadeamento completo com MP4, substituição do resultado anterior, quadro rejeitado e CLI export/import/verify sem sobrescrita |

São 79 testes principais novos e 12 subtestes novos, somados à base anterior de 374 testes e 30 subtestes. Os testes unitários do compilador isolam a ingestão por stub; `test_generation_workflow.py` usa os módulos reais e mídia produzida pelo FFmpeg para conferir a integração.

## Provas executadas

1. Exportação do exemplo autoral de três clipes de dez segundos: três prompts completos, cinco necessidades de imagem e montagem planejada de trinta segundos. O perfil ilustrativo continua `unverified` e os clipes continuam `draft`.
2. Pedido de direção produzido pela CLI com briefing, contrato completo e exemplo validado. Inferência e geração permanecem explicitamente não executadas por esse comando.
3. Cadeia sintética: primeiro prompt pronto; segundo aguardando retorno; após importar o primeiro vídeo, segundo pronto usando o frame selecionado; após importar o segundo, terceiro pronto. Trocar o primeiro resultado invalida o descendente ligado ao recibo antigo.
4. Quadro observado com decisão `revise` continua bloqueado para condicionamento do próximo clipe. Observação de movimento, aceitação editorial e aprovação do usuário são estados separados.
5. Selecionar um quadro anterior não modifica o trim planejado. Alteração de bytes, frame incorreto, relógio incompatível ou origem divergente é detectada.
6. Conferência do código e das exportações: instruções, testes e exemplos são autorais; os anexos privados e os scripts Editron não foram copiados para o repositório nem executados.

## Limites da evidência

Os vídeos dos testes são padrões sintéticos para verificar clocks, arquivos, dependências e contratos. As observações usadas em fixtures são dados de teste, não avaliações de qualidade de uma produção. Não houve chamada a um gerador externo, uso de créditos, comparação de rosto real, audição de um filme do usuário ou aprovação audiovisual.

A camada nova planeja e exporta instruções, importa resultados e verifica seus vínculos. Ela não constitui um novo modelo de vídeo, um agente perceptivo autônomo ou um montador genérico de todas as transições. A qualidade da direção precisa ser avaliada num projeto real, com referência, recursos e resultados efetivamente produzidos. O [guia de geração](video-generation.md) registra essas fronteiras e as rotas disponíveis.
