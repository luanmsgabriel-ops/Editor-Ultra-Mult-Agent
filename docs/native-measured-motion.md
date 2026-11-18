# Editor Ultra P0 | motion medido no compositor nativo

## Objetivo

O Motion Kit 0.9 registra curvas de similaridade 2D por elemento e
um relatório de cobertura. A rota anterior prova aplicação de curvas com
`geometric_video`. Esta etapa permite que `native.render_bundle` também
consuma um perfil de movimento **atual** e preserve um recibo por frame.

## Contrato

A ferramenta existente `editor_render` aceita o argumento opcional
`native_motion`, sem mudar as chamadas antigas:

```json
{
  "project_id": "UUID_DO_PROJETO",
  "kind": "clone",
  "expected_revision": 7,
  "request_id": "native-motion-proof-001",
  "native_motion": {
    "schema": "editor-ultra-native-measured-motion/1",
    "measurement_id": "ID_DA_MEDICAO_ATUAL",
    "decision_id": "ID_DO_EFEITO_NATIVE_AUTORADO",
    "element_id": "elemento",
    "channels": ["position", "scale", "angle"],
    "pivot_px": [80.0, 45.0],
    "base_scale": 0.24,
    "time_map": [
      {"output_time": 0.0, "source_time": 0.0},
      {"output_time": 0.9, "source_time": 0.9}
    ]
  }
}
```

Os números são ilustrativos. O render exige material independente
(modo clone de reconstrução ou edição com novo bruto), registro de medição
válido para revisão atual e uma decisão de composição nativa já autorada.

O sistema recupera o perfil somente pelos IDs/recibos do projeto, confere
SHA-256, relógio e proveniência e o aplica ao efeito de tela identificado
por `decision_id`. Não permite profile JSON ou paths externos no pedido.

## Restrições

- Apenas `native.overlay` e `native.motion_layer` com animação
  `hold` e âncora de tela. Rotas planares, corporais, 3D e perspective
  não utilizam essa transformação 2D.
- Cada quadro do efeito usa o relógio de saída real, mesmo quando o
  perfil medido nasceu em outro relógio devidamente mapeado.
- Curva sem cobertura, escala inválida, extrapolação, elemento que sai
  do raster e decisão incompatível são erros, não fallback silencioso.
- O renderizador registra o frame como consumido **após** compor o overlay
  em pixels reais, e exige que todos os frames do trecho estejam presentes
  no relatório final.
- Referência e bruto original são preservados. Não substitui rosto, atuação,
  perspectiva ou oclusões físicas; requer gravação ou geração independente
  antes de um teste com nova pessoa.

## Validação

Execute o workflow `P0 native measured motion consumption`.
O teste de MP4 sintético usa tracking real, uma imagem RGBA independente,
encodificação FFmpeg e inspeção dos pixels de saída. Não invoca geração paga.
Mesmo com CI verde, o vídeo fica `rendered_unreviewed`.

Este PR está empilhado sobre #16 e não faz merge na main ou publicação.
