# Validação da integração de motion

Data: **16 de novembro de 2026**. Escopo: OpenKatana fixado, Motion Lab legado
MIT, módulos portáteis de MOTNGRFX e sua ligação com a direção/composição
contextual do Editor Ultra.

## Resultado da suíte integrada

```sh
python -m pytest -q tests extensions --junitxml=/caminho/fora-do-repositorio/motion-integration-tests.xml
```

**374 testes e 30 subcasos passaram em 43,01 segundos. Nenhuma falha, erro ou
skip.** O JUnit registra 404 casos ao incluir os 30 subcasos. Foram emitidos dois
avisos de depreciação de dependências/testes existentes: `CallSpec2` no plugin
AnyIO/Pytest e `Image.getdata` no teste de alpha. Esses avisos não representam
aprovação visual nem falha de render.

O registro anterior de 315 testes é histórico. Esta integração acrescenta 59:

| Arquivo | Testes | Evidência principal |
| --- | ---: | --- |
| [test_openkatana_integration.py](../tests/test_openkatana_integration.py) | 13 | Medição sobre pixels/PCM reais, execução JS Canvas, FPS racional, origem dos proxies, Blender/Cycles e gates de dependências. |
| [test_motionlab_integration.py](../tests/test_motionlab_integration.py) | 16 | 2D, geometria 3D, câmera, z-buffer, alpha, fontes reais, grupos, blur limitado por cortes e candidatos sonoros. |
| [test_motngrfx_integration.py](../tests/test_motngrfx_integration.py) | 15 | Extrusão, rotação/articulação, fonte, IDs por glifo, frente/atrás, cobertura e composição sobre vídeo real codificado. |
| [test_motion_assets.py](../tests/test_motion_assets.py) | 13 | Composição contextual, proteção do sujeito, mesma transformação de alpha, visibilidade, intervalos, integridade e amostras de áudio. |
| [test_motion_workflow.py](../tests/test_motion_workflow.py) | 2 | Produtor real → exportação RGBA → inventário → preparação → pedido de direção, preservando origem, glifos e eventos sonoros. |

O teste de integração dos produtores usa vídeo sintético codificado, arquivos
reais e o mesmo caminho de exportação utilizado pela CLI. A fonte conserva seu
hash. Os candidatos sonoros chegam ao pedido com o hash da receita renderizada;
o mapeamento ao clock da fonte não seleciona um SFX.

## Ambiente efetivamente usado

| Dependência | Versão |
| --- | --- |
| Python | 3.12.14 |
| Node | 24.22.1 |
| FFmpeg/FFprobe | 7.1.5 |
| Blender | 4.3.2, Cycles por CPU exercitado |
| NumPy / Pillow | 2.3.5 / 13.0.0 |
| fontTools / uharfbuzz | 4.61.1 / 0.57.0 |
| Pytest | 9.2.0 |
| Three.js / Canvas Node | 0.180.0 / `@napi-rs/canvas` 0.1.100 |

As dependências Node têm lockfiles próprios. Os testes do OpenKatana passaram
sem `NODE_PATH`; a instalação própria por `npm ci --ignore-scripts --offline`
também foi exercitada. Os quatro arquivos TOML dos agentes foram carregados por
`tomllib`, e `git diff --check` não encontrou erros de whitespace.

## Provas renderizadas durante a integração

As três prévias abaixo são demonstrações técnicas sintéticas. Elas têm recibos
próprios e não representam uma edição de um novo bruto do usuário. Os PNGs RGBA
e passes de glifos são os assets; os MP4s são cópias achatadas para inspeção.

| Prova | Arquivo de apresentação | Execução e inspeção |
| --- | --- | --- |
| Motion 2D | `editor-ultra-motion-2d.mp4` | 48 frames, 640 × 360, 24 fps, 8 subframes; objetos com tracks independentes. Contato inspecionado nos frames 0, 16, 31 e 47. |
| Motion 3D | `editor-ultra-motion-3d.mp4` | 48 frames, 480 × 320, 24 fps, 4 subframes; caixa, toro, grupo e câmera perspectiva. Contato inspecionado nos frames 0, 16, 31 e 47. |
| Tipografia/oclusão | `editor-ultra-tipografia-camadas.mp4` | 48 frames, 640 × 360, 24 fps; título extrudado e oclusor sintético. Contato inspecionado nos frames 0, 12, 24, 36 e 47. |

SHA-256 dos arquivos de apresentação:

```text
editor-ultra-motion-2d.mp4
a79f32fa5cff135db64a79a96b69b46150d7297457cf8d1145c904e2adcfa6bd

editor-ultra-motion-3d.mp4
04d80975820b1552afbe44a627df2f6da908984d7af663792da7a23e9814a4f3

editor-ultra-tipografia-camadas.mp4
669e8a0cdb43d55cf8c0f1cd34c0a1f60a309d48b23bbb86896dc85c17ac6b5c
```

A comparação integral de pixels da prova tipográfica foi feita sobre
`behind.mkv`, em FFV1 sem perdas, SHA-256
`f108f391d1faedb99256eb9cd4e190667cca1854e66e5fb2280a3081fd59f6e1`.
O erro máximo foi zero, inclusive na troca de plano no frame 24; a fonte
permaneceu intacta. A menor visibilidade da palavra foi 92,64%, e a menor
visibilidade individual de glifo foi 66,28%. Essas métricas pertencem ao MKV
verificado. A cópia MP4 usa compressão e não herda a alegação de igualdade exata
de pixels.

O OpenKatana também executou uma prévia de `local_rgb_split` com oito frames
96 × 96 a 10 fps pelo engine upstream em Canvas, análise de referência e DSP
sobre pulsos conhecidos de aproximadamente 120 BPM. A ponte Blender/Cycles
renderizou geometria, câmera, luz e alpha reais em dois frames 64 × 64 a 10 fps.
Uma regressão adicional codifica e verifica a fração **30000/1001** exatamente.

## Correções verificadas na revisão cruzada

- A timeline examina as amostras usadas por shots, rampas e efeitos temporais.
  In-point negativo e fonte esgotada bloqueiam sem repetição explicitamente
  declarada. Repetições autorizadas ficam registradas no relatório.
- O binding de uma fonte verifica todos os pixels dos proxies contra nova
  decodificação do vídeo e sua origem temporal. O SHA de um vídeo não valida
  PNGs que vieram de outro.
- Dependências Blender são comparadas com os hashes registrados antes do
  render. Uma variável de ambiente apontando para executável inexistente não
  torna o backend disponível.
- Scripts explicitamente confiados mantêm uso externo e créditos como
  desconhecidos. O recibo não afirma zero chamadas para código que não observa.
- A proteção contextual mede o alpha pela mesma transformação do compositor,
  incluindo elementos finos e posições fracionárias. Visibilidade por letra
  exige um passe real de IDs dos glifos.
- Arredondamento de um evento sonoro para fora do intervalo semiaberto da fonte
  bloqueia o mapeamento. O sistema não repete frames ou muda uma camada de trás
  para a frente para ocultar cobertura insuficiente.

Os pontos de clock/proxy/Blender tiveram uma segunda revisão independente de
código e seis regressões focadas. A suíte integrada acima foi executada depois
das correções e inclui esses casos.

## Limites que permanecem explícitos

**Chromium/WebGL não executou neste ambiente.** A inicialização foi bloqueada
pelo runtime em IPC/socket. O adaptador mantém esse caminho indisponível; não
troca automaticamente por Canvas ou Blender. Node Canvas e Cycles por CPU são
rotas próprias, com execução comprovada e identificada.

O renderer 3D de Motion Lab usa geometria, perspectiva, z-buffer e iluminação
Lambert por CPU. Não implementa sombras, reflexos, PBR ou antialias espacial e
não é evidência de solve da câmera de uma filmagem. O MOTNGRFX incorporado é o
subconjunto portátil; o pipeline generativo completo de ComfyUI e seus modelos
não foram instalados ou executados. O preflight opcional não equivale a execução.

Nenhum novo peso ou modelo generativo foi baixado e nenhuma API paga foi
acionada para produzir estas provas. Interpretação editorial, escolha semântica
de SFX e revisão com áudio continuam exigindo suas etapas reais. Os testes e
contatos não demonstram playback contínuo, audição, fidelidade global a uma
referência ou aprovação do usuário; esses estados permanecem pendentes.

Para reproduzir o uso, consulte [motion-integration.md](motion-integration.md)
e os três guias de adaptadores. O código, receitas, licenças e instruções ficam
no Git; mídia privada, fontes, pesos e dependências instaladas permanecem fora.
