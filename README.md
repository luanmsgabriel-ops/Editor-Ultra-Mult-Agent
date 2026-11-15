# Editor Ultra Multi-Agent

Fluxo de edição no Codex com nove agentes, nove skills e comandos para inventário de mídia, catálogo com escopo no Drive, curadoria, validação de cortes e áudio em amostras, renderização e auditoria. O piloto Oníria mantém um plano editorial definido e recompila a variante com novos SFX. A direção escolhe os cortes e aprova os efeitos com evidência. O motor valida, aplica e confere o que foi aprovado.

## Começar no Codex

Abra o repositório no Codex com acesso aos arquivos do projeto. Informe fontes, referência, destino e raízes permitidas do Drive. Peça ao coordenador para executar `AGENTS.md` e produzir um plano com timecodes, catálogo, cortes e uma versão comparável. Os papéis do Codex ficam em `.codex/agents` e os procedimentos em `.agents/skills`. [Documentação de agentes](https://learn.chatgpt.com/docs/agent-configuration/subagents)

O repo usa Python 3.11+ e ffprobe. O piloto requer FFmpeg (libass, zscale e libx264), NumPy e fontes do sistema. Reconstruir o letreiro requer também Blender e Pillow.

```sh
python -m unittest discover -s tests -v
python -m unittest discover -s extensions -v
python -m audiovisual inventory /caminho/dos/brutos --output inventario.json
python -m audiovisual validate examples/secador.json
python -m audiovisual.drive_catalog --snapshot drive-snapshot.json --local assets/ --output drive-catalog.json
python extensions/editor_policy.py rank drive-catalog.json necessidade.json drive-scope.json
```

A coleta de metadados também pode consultar a API oficial do Drive. Passe IDs autorizados via `--root` e disponibilize um token no ambiente como `EDITOR_DRIVE_ACCESS_TOKEN`. O arquivo de saída será local. O comando segue paginação, verifica parentesco e mantém atalhos registrados sem seguir destinos. Em sessão com conector, obtenha o catálogo e os arquivos diretamente da conexão autorizada e use `--snapshot`. Salve os arquivos efetivamente baixados no formato `ID.ext`.

O ranking calcula elegibilidade por origem, família, compatibilidade, destino e duração verificada. Pode incluir ativos pendentes para prévia privada autorizada via `allow_unverified_private_preview` no escopo. Cada candidato escolhido precisa bater com o SHA-256 da cópia baixada. A escuta e a adequação editorial são revisadas no contexto da cena. Um pico de onda sozinho não identifica batida, gesto ou efeito.

## Piloto reproduzível

```sh
python -m pilots.oniria.run \
  --sources /caminho/dos/brutos --stage /caminho/do/palco-composto.mp4 \
  --catalog drive-catalog.json --scope drive-scope.json --cues cues.json \
  --assets assets/ --base mix-de-controle.flac --out out/oniria
```

Para repetir apenas som e montagem final, use `--picture` com a imagem limpa já renderizada. O comando grava ranking, decisão, cues, validação do quadro e da amostra, MP4 conferido e manifesto. Os brutos, escopo do projeto, mix e arquivos licenciados ficam no ambiente do projeto. O pacote de auditoria do piloto registra as três escolhas e os parâmetros reais para reaplicá-las. `docs/Mapa-de-Pos-Producao.md` descreve como evoluir os adaptadores de efeitos, a timeline gráfica e as provas 3D.

## Cobertura

O piloto exercita ingest de catálogo, ranking, três efeitos de áudio com proveniência, plano travado, imagem dos 38 brutos, mix, export e verificação. Os papéis de agente integram essa execução quando acionados no Codex. Análise semântica e calibração espacial automatizadas em qualquer filmagem, round-trip gráfico e julgamento perceptivo sem revisão permanecem etapas distintas de validação.

## Motion a partir de referência

O [piloto da cascata de três cards](pilots/motion_cards/README.md) mede movimentos, aplica o mesmo template sobre outro bruto e exporta uma comparação e uma composição HyperFrames.

O [motor de fidelidade visual](visual_fidelity/README.md) mede fontes e vetores, renderiza materiais em Blender/Cycles e compõe fotos ou malhas na timeline Origins. Os adaptadores opcionais de COLMAP e TRELLIS.2 operam em ambientes externos.

Para adaptar palavras e gráficos ao enquadramento de outro vídeo, use `python -m visual_fidelity anchor render` com o [plano de exemplo](examples/ancoras-visuais.json). O motor escolhe uma posição por plano ou acompanha uma superfície pela homografia. O [manual de âncoras](visual_fidelity/README.md#aplicar-texto-e-efeitos-a-outro-vídeo) também cobre trajetórias TAPIR e projeção por câmera Blender/COLMAP.

Para seguir cabeça, ombro, mãos, quadril, joelhos ou pés, use as [âncoras corporais](visual_fidelity/README.md#âncoras-no-corpo-e-órbita). O [plano de exemplo](examples/ancoras-corpo.json) combina uma órbita de texto com o rastreamento do ombro.
