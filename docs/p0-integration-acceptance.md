# Editor Ultra | Aceite da integração P0 (PR #16)

## Linhagem do código

- PR #9 contém a comparação de fidelidade visual e temporal, recursos de
  reconstrução e preparo de clonagem independente.
- PR #15 empilhado sobre #9 implementa roteamento e QA por cena.
- PR #16 empilhado sobre #15 incorpora as capacidades funcionais dos PRs
  independentes #13 (Motion Kit 0.9 aplicado ao render) e #14 (importação
  verificada de VIDEOAPI) e reconcilia as atualizações da main.
- O Studio expõe `ui://editor-ultra/studio-v9.html`, preservando aliases v1-v8.

Esta branch não é uma publicação, não faz merge dos outros PRs e não altera
dados persistentes do Railway. Os PRs separados continuam como histórico
auditável da implementação.

## Cadeia funcional que os testes sintéticos devem comprovar

1. Criar/abrir um projeto, importar referência real e um novo vídeo de base;
   não aceitar o arquivo da referência como atuação nova.
2. Registrar um inventário `editor-ultra-reference-scenes/1` que cubra
   todos os quadros no relógio da fonte, sem sobreposição ou lacunas.
3. Routejar necessidades por cena em `editor_route_reference_scenes`;
   probes confirmam disponibilidade, mas não marcam render como executado.
4. Medir um elemento via `editor_measure_motion`; registrar curvas e gaps
   como `evidence_not_applied` até existir uma execução.
5. Aplicar curva 2D em imagem/matte independente pelo
   `editor_apply_measured_motion`, sem interpolação de lacunas, e conferir
   recibo de todos os quadros consumidos no MP4 codificado.
6. Para um job VIDEOAPI previamente concluído, usar
   `editor_import_videoapi_result`, validando origem, tamanho, codec, SHA-256
   e idempotência. A importação não faz outro POST pago.
7. Se necessário, preparar `clone_resource` e `reconstruction` com
   base nova; executar apenas cenas para as quais há materiais e contratos
   aprovados, guardando recibos do executor verdadeiro.
8. Auditar a reconstrução com comparação exata e
   `editor_audit_scene_batch`. Metrificações 2D são diagnósticos, não uma
   porcentagem automática de fidelidade.
9. Toda reconstrução com QA incompleto ou eventos não resolvidos permanece
   bloqueada para aprovação. A revisão estética contínua do usuário continua
   explícita, mesmo depois de todos os testes técnicos aprovados.

## Gates de CI

Workflow `.github/workflows/p0-integration-gate.yml`:

- Python 3.12 + FFmpeg real + dependências de Motion Lab fixadas;
- suites cruzadas de autenticação, upload, API VIDEOAPI, Motions, material
  de clonagem, QA visual e temporal e execução de cena;
- teste `tests/test_p0_integrated_flow.py`, que atravessa todos esses
  componentes no mesmo projeto, sem consumo real de API;
- sintaxe JavaScript do Studio v9 e build Docker sem push/deploy.

O relatório do workflow é a fonte da contagem de testes e aprovação técnica.
Relatório técnico verde NÃO altera decisões do usuário sobre a estética.

## Pendências para homologação com vídeo real

- Staging isolado com dados não produtivos e conexão autenticada para
  executar a branch combinada sem substituir o serviço vigente.
- Novo vídeo de atuação desde o primeiro quadro, além da referência;
  cortes, quadro final, FPS, resolução, voz e direitos de uso verificados.
- Tracking por elemento e cobertura temporal explicitada; quando houver
  perspectiva, objetos escondidos ou oclusão real, exigir executor adequado
  e recibos novos. A prova de similaridade 2D não resolve essas tarefas.
- Medir diferenças por cena de transições, tipografia, composição,
  posição/escala/rotação, ritmo, SFX e sincronização audiovisual.
- Testar o mesmo trecho real com modelos distintos apenas depois que o
  fluxo de binding e QA estiver estável, para não confundir defeito de
  orquestração com defeito de geração.
- A pessoa responsável revisa vídeo completo, aponta divergências e
  registra aprovação ou rejeição explícita antes de qualquer publicação.

## Política de segurança

- Não expor VIDEOAPI_KEY em logs ou browser.
- Não executar geração paga nem baixar modelos automaticamente ao rotejar.
- Não repetir POST incerto e não importar URL arbitrária.
- Não marcar `applied` quando há apenas `measured`.
- Não fazer merge nem deploy sem checklist de segurança/CI e decisão explícita.
