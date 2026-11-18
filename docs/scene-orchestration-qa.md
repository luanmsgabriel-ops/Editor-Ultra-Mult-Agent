# P0: roteamento por cena + QA obrigatório de reconstruções

## Dependência e segurança

Este PR depende do PR #9 (reference_fidelity, reference_temporal_qa e
reference_scene). É uma **branch empilhada**, não modifica main nem publica no
Railway. PRs #13 e #14 continuam independentes. O roteador não envia arquivos
para provedores pagos e NÃO clona rostos, gestos ou atuação em vídeo.

## Sequência implementada

1. Importar a referência real e registrar `editor-ultra-reference-scenes/1`
   com cobertura total, início/fim e eventos observados/desconhecidos.
2. Chamar `editor_route_reference_scenes` com um item para CADA cena:
   `scene_id`, `needs` e eventual receita declarativa `recipe`.
3. A seleção usa probes reais das dependências locais de Motion Lab,
   OpenKatana/Blender, MOTNGRFX e composição nativa. Indisponibilidade e
   evidências insuficientes permanecem como bloqueios, nunca fallback.
4. Somente `motion_graphic_2d` com receita autoria completa, alpha
   transparente, FPS e duração exatos, até 120 frames e 1280×720, pode
   executar diretamente via `editor_run_scene_motion`. A execução usa o
   adaptador e ledger de produção existentes, gerando sequência RGBA real,
   recibos com hash e estado `motion_produced_unreviewed`. Essa sequência
   não vira automaticamente clone completo.
5. Para cada render `clone` de tipo `reconstruction`, o servidor tenta
   automaticamente diagnosticar as PRIMEIRAS quatro cenas do inventário.
   Se não houver inventário/relógio compatível ou algum erro de QA, registra
   estado bloqueado. O MP4 real continua preservado.
6. Usar `editor_audit_scene_batch` para completar as demais cenas,
   em lotes de até quatro. Cada lote mede quadros alinhados pelo mesmo índice
   e fluxo óptico 2D numa janela central da cena. Salva MP4 hashes, JPEG
   comparativo e CSV/relatório temporal.
7. A revisão técnica só fica `technical_evidence_complete_visual_review_pending`
   se TODAS as cenas possuírem relatórios atuais vinculados aos mesmos
   bytes de referência, inventário e clone. Só então uma reconstrução pode
   receber eventual aprovação explícita do usuário.

## Exemplo de roteamento

```json
{
  "project_id": "UUID_DO_PROJETO",
  "expected_revision": 4,
  "request_id": "route-reference-scenes-001",
  "choices": {
    "schema": "editor-ultra-scene-routing/1",
    "scenes": [
      {
        "scene_id": "sceneA",
        "needs": ["motion_graphic_2d"],
        "recipe": {"schema_version": "motionlab-scene/1", "id": "cena-autoral",
                   "mode": "2d", "width": 160, "height": 90, "fps": "10/1",
                   "frame_count": 10, "background": null,
                   "nodes": [{"id": "tile", "type": "rect", "x": 8, "y": 20,
                              "width": 24, "height": 20, "fill": "#22bbee"}],
                   "tracks": []}
      },
      {"scene_id": "sceneB", "needs": ["new_actor_performance"]}
    ]
  }
}
```

Os IDs, durações e receitas são ilustrativos. O relógio e os nomes precisam
coincidir com um inventário real já registrado. `new_actor_performance` fica
externo e exige material/consentimento; não aciona a VIDEOAPI automaticamente.

## Matriz de capacidade

| Necessidade | Motor candidato | Estado inicial |
|---|---|---|
| motion_graphic_2d | Motion Lab | Executável somente com runtime/receita verificados |
| measured_motion_2d | Motion Kit | Tracking medido não equivale a curva aplicada |
| native_composite | Native + FFmpeg | Exige plano, capacidades e recursos verificados |
| typography_3d | MOTNGRFX | Depende de fonte/licença e direção |
| environment_3d | OpenKatana/Blender | Precisa de geometria, ambiente e plano autorados |
| synchronized_sfx | Native Audio | Exige assets e âncoras temporais |
| temporal_occlusion | Máscara temporal própria | Não há segmentação universal comprovada |
| new_actor_performance | Geração/filmagem externa | Sem execução paga implícita |
| preserve | Sem operação | Preservação explicitamente autorada |

## Garantias e limites

- Não transforma um vídeo original em pessoa nova nem reutiliza os pixels do
  vídeo de referência para fingir nova atuação.
- Não executa render via seleção de motor. Somente pedido explícito inicia
  produção local.
- Não perde registros de execuções anteriores ao falhar uma operação.
- Um vídeo pode estar tecnicamente decodificado e ser esteticamente rejeitado.
  QA 2D detecta divergências, não dá nota final de fidelidade universal.
- Dependência: os PRs #9, #13 e #14 ainda precisam ser reconciliados antes
  de integração conjunta e deploy, com regressões sobre o código combinado.

## Validação

```bash
python -m pytest -q tests/test_app_scene_orchestrator.py \
  tests/test_reference_fidelity.py tests/test_reference_temporal_qa.py \
  tests/test_app_fidelity_bridge.py tests/test_app_server.py
```

Requer FFmpeg e dependências Node fixadas do Motion Lab para o teste real.
Nenhuma chamada paga é feita.
