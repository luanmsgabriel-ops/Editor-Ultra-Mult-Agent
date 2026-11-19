# Biblioteca inteligente e edição por trecho

O Studio v10 liga dois vídeos independentes ao mesmo projeto. Um fornece observações de edição. O outro recebe as técnicas escolhidas. A biblioteca preserva versões e previews autorados. O vídeo de referência fica associado à origem da receita por hash e intervalo. A composição usa a filmagem nova.

## Pelo Studio

1. Abra um projeto e expanda **Biblioteca inteligente e edição por trecho**.
2. Envie e analise o vídeo de referência. **Buscar referências na conversa** pede ao ChatGPT uma busca por referências públicas. Use o campo de link para registrar a origem e anexe a mídia pelo upload normal.
3. Abra a inspeção e confirme a técnica a partir da referência. Cadastre uma receita com título, ID, versão e intervalo. O motor gera um MP4 de demonstração sobre fundo sintético.
4. Envie e analise o vídeo a editar. Peça sugestões ou consulte a biblioteca. Selecione o efeito, trecho e texto quando necessário.
5. Renderize uma prévia do trecho ou o vídeo completo. Revise o arquivo atual. As versões do projeto mantêm a prévia, o recibo e a decisão de revisão.

## Pelo chat e MCP

Use `editor_open`, `editor_save_project` e `editor_import_file` para abrir o projeto e admitir anexos com papéis `ref` e `footage`. Use `editor_effect_workflow` com o ID do projeto, `expected_revision`, um `request_id` novo para a operação e um objeto `command`. As operações são retomáveis pelo ID do job em `editor_get_project`. Os resultados ficam em `effect_workflow`. Os intervalos são `[primeiro quadro, fim exclusivo]` no relógio da própria fonte.

| Ação | Campos e comportamento |
| --- | --- |
| `analyze` | `role`, `asset_id` e `source_url` opcional. Grava PTS, segmentos candidatos, mudanças fortes, possíveis flashes, estimativa de atividade acústica, contato dos planos e proxy de inspeção. |
| `publish` | `recipe_id`, `version`, `title`, `description`, `effect`, `reference_range` e `confirmed: true`. Aceita `tags`, duração, cor e intensidade. O envelope opcional é uma lista de pares de fase e opacidade entre 0 e 1. |
| `suggest` | `query` opcional e `opportunities` autoradas com `range`, `intent` e famílias admissíveis. Vincula alternativas ao bruto analisado e informa quando a câmera precisa ser resolvida. |
| `select` | `recipe_id`, `version`, `range` e `text` quando aplicável. `replace: true` confirma a troca de aplicações sobrepostas. |
| `remove` | `application_id`. A versão anterior fica no histórico e o render perde a condição de versão atual. |
| `render` | `preview: true` e `application_id` opcional para inspeção de um efeito. Use `preview: false` para renderizar todo o bruto. |
| `review` | `asset_id`, `decision`, `confirmed: true` e `notes` opcional. A aprovação final exige o MP4 completo atual. |

`editor_list_effects` retorna versões disponíveis, executor, âncora e URLs de demonstração. O widget utiliza comandos equivalentes em `editor_save_project` para funcionar com hosts que ainda têm o schema anterior em cache.

Para reaplicar movimento da referência, use `editor_measure_motion` no vídeo identificado como `ref`. Depois passe `motion_measurement_id` e `motion_element_id` ao publicar uma legenda ou cartão. A receita consome posição, escala e rotação do perfil validado ao longo do intervalo inteiro. A curva é normalizada para a duração da aplicação. Os efeitos e parâmetros ausentes de um vídeo achatado exigem reconstrução e autoria explícitas.

## Aplicações e cobertura

- `flash` pontua um corte já presente no bruto. `type` compõe uma legenda cinética. `world` renderiza um cartão extrudado em coordenadas de mundo.
- O cartão 3D pode usar câmera pinhole com intrínsecos estimados e reconstrução relativa por paralaxe. Para calibração explícita, forneça `calibration.intrinsics`, `calibration.world_points` e `calibration.image_points`. Os pontos de imagem são normalizados e descrevem o primeiro quadro da aplicação. A solução exige pontos de cena com profundidades distintas e boa cobertura.
- `anchor` é a posição normalizada no primeiro quadro e `scale` é a fração de largura desejada. A métrica da reconstrução automática é relativa. O movimento do elemento no mundo e o movimento da câmera aparecem separadamente no cálculo.
- `occlusion` aceita o contorno normalizado inicial de um elemento que passa na frente. O matte propaga o recorte no vídeo atual. A prévia permite conferir as bordas. Esse modo exige que o elemento oclusor esteja visível no quadro inicial.
- O recibo do render registra revisão das receitas, quadros consumidos, pixels alterados, área ocluída, câmeras e reprojeção. A câmera é reaproveitada entre prévia e render completo quando fonte, trecho, calibração e âncora coincidem.
- Para este fluxo, use um bruto CFR por projeto, sem rotação de contêiner, com raster de até 1080p e 3.600 quadros. A análise aceita PTS variáveis, e a execução pede uma cópia CFR. A reconstrução 3D aceita até 300 quadros por aplicação. O motor exige uma solução para todo o intervalo e registra a falha quando a cobertura é insuficiente.

O fluxo inclui escolha e aprovação no Studio. A qualidade da reconstrução, a seleção da âncora e a fidelidade ao estilo continuam decisões de revisão. Cobertura futura inclui importação direta de provedores autorizados, efeitos adicionais via adaptadores existentes, camadas simultâneas e tracking de objetos articulados.

## Teste de integração

```sh
python -m pytest -q tests/test_effect_workflow.py
```

A prova autenticada usa dois arquivos sintéticos. Mede motion da referência, publica três receitas, consulta alternativas, resolve a câmera do bruto, gera a prévia e exporta a edição com áudio. Verifica o recorte e o elemento projetado no MP4 codificado. Uma prova separada resolve uma câmera relativa com paralaxe e verifica a recusa de uma sequência estática.
