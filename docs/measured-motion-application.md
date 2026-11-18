# P0: curvas medidas até um MP4 auditável

## Estado e escopo

Motion Kit 0.9 mede movimentos. A nova ferramenta MCP
`editor_apply_measured_motion` recebe um recibo de medição atual e mapeia
suas curvas a uma camada 2D em mídia NOVA. Renderiza um preview técnico com
`visual_fidelity.geometric_video` e salva vídeo, manifesto e relatório de
quadros realmente consumidos.

Não substitui atuação, rosto, gestos, máscaras temporais, câmera 3D ou áudio.
É prova de movimento 2D com imagem estática e matte fornecido. A referência
nunca se torna base do MP4. A ferramenta NÃO chama VIDEOAPI ou aprova o vídeo.

## Preparação dos arquivos

Importe os quatro materiais, antes de medir, no mesmo projeto:

1. `ref`: vídeo de referência (para observar movimento).
2. `footage`: vídeo novo de fundo (CFR, até 1920x1080, até 60 fps,
   sem rotação de contêiner e com a duração suficiente).
3. `identity` ou `logo`: imagem nova que será animada.
4. Uma segunda imagem do projeto contendo o matte preto/branco, com
   mesmas dimensões da camada nova e pixels de alpha não nulos.

Depois, execute `editor_measure_motion` e examine as curvas e lacunas.

## Chamada de aplicação

```json
{
  "project_id": "UUID_DO_PROJETO",
  "expected_revision": 5,
  "request_id": "motion-preview-001",
  "specification": {
    "schema": "editor-ultra-measured-motion-application/1",
    "measurement_id": "ID_DA_MEDICAO",
    "base_asset_id": "ID_DO_VIDEO_NOVO",
    "overlay_asset_id": "ID_DA_IMAGEM",
    "matte_asset_id": "ID_DA_MASCARA",
    "element_id": "painel",
    "channels": ["position", "scale", "angle"],
    "frame_count": 10,
    "base_start_frame": 0,
    "pivot_px": [48.0, 44.0],
    "base_scale": 1.0,
    "time_map": [
      {"output_time": 0.0, "source_time": 1.0},
      {"output_time": 0.9, "source_time": 1.9}
    ]
  }
}
```

As datas/tempos são ilustrativos. A curva escolhida precisa existir na
medição e cobrir todos os quadros pedidos. O pivot corresponde ao raster
da camada depois do redimensionamento. Para uma saída com outra geometria,
informe `spatial_scale` uniforme e `spatial_offset_px`; não estique o quadro.

O job é assíncrono na fila local de render. Acompanhe com
`editor_get_project` e leia `motion_applications`; abra o MP4 por
`editor_get_asset` com o `render_asset_id` retornado. O vídeo é
`rendered_unreviewed` e não altera o aceite de clone/final.

## Gates e limitação da fidelidade

- Exige recebimentos verificados no mesmo projeto, hashes atuais e revisão
  atual da medição; estado stale é recusado.
- Exige mapa de tempo explícito, matte válido e cobertura por quadro.
- Não extrapola sobre tracking perdido. Lacuna interrompe antes de codificar.
- Verifica SHA-256 do vídeo renderizado, consumo em cada índice da janela,
  e mantém o manifesto e o relatório de consumo.
- A primeira versão usa imagem+máscara estáticas, não tenta trocar uma
  pessoa em movimento nem deduz alpha/oclusões de uma foto.
- Sem SFX/trilha nessa prova técnica; montagem audiovisual permanece
  etapa separada.

## P0 ainda pendente

- Adaptador de curvas medidos em `native.render_bundle` por cena.
- Roteador real de motores com seleção por capacidade e recibos de execução.
- Importação verificada do resultado da VIDEOAPI (sem nova chamada paga).
- QC temporal/estético por cena obrigatório antes da entrega.

## Testes

```bash
python -m pytest -q tests/test_app_motion_application.py tests/test_app_motion.py tests/test_motion_binding.py tests/test_app_server.py
```

O teste cria MP4 sintético, mede movimento, renderiza com curva e reinspeciona
os pixels exportados; não prova fidelidade estética de uma referência humana.
