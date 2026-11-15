# Clara — motion em português, revisão PT2

47,291667 segundos, 720 × 1280, 24 fps, 1.135 quadros. Referência de montagem: 329687.mp4. Filmagem: 329271.mp4. Esta é uma composição híbrida executada pelo motor, com recorte real, tipografia editável, imagens transparentes e passes de câmera/objetos do Blender.

## Reproduzir

Instalar Python3.11+, numpy, Pillow, opencv-python-headless, scipy; FFmpeg no PATH. As imagens/câmeras já estão renderizadas, então Blender não é necessário para reproduzir este MP4. Os fontes Blender e receitas permanecem no pacote para alterações de geometria.

```bash
python render_pt.py output/visual-final.mp4
ffmpeg -y -i output/visual-final.mp4 -i audio/mix47.wav -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k -t 47.291667 -movflags +faststart output/Clara-Motion-PT2-47s.mp4
```

`render_pt.py` chama `pt_scenes.py`, que usa o snapshot `engine/visual_fidelity`. O original `reconstruir.py` pertence à reconstrução anterior da referência e NÃO é o comando desta adaptação portuguesa. Não executar `composite_v6.finish` sobre esta edição: isso recolocaria os letterings estrangeiros.

## Onde encaixar cada coisa

| Quadros / segundos | Composição e ordem, de trás para frente | Fonte de verdade |
|---|---|---|
| 0–101 / 0–4,25 | Fundo creme; CLARA condensado e criativa cursiva; recorte real; desfoque; calendário curvo 4+3; frases de frente | pt_scenes.opening, pt_typography, pt_panels.calendar_layer |
| 102–165 / 4,25–6,917 | Fundo; símbolo pessoas; título; verso da faixa CRIAR; recorte real; frente da faixa; clarão | pt_scenes.orbit; orbit_type.OrbitSpec |
| 166–218 / 6,917–9,125 | CRIAR monumental com brilho; cursivas; Clara e cadeira inclinadas; clarão | pt_scenes.omad; pt_typography |
| 219–231 / 9,125–9,667 | Cartão Cada detalhe conta; transição de faixas | pt_scenes.deadline |
| 232–404 / 9,667–16,875 | Fundo rosado; folhagem distante; vidro audit→funnel287→flow333; lupa móvel; folhagem desfocada em frente | pt_panels.py; localized/audit.png; hybrid/panels |
| 405–532 / 16,875–22,208 | Passes da câmera Blender; seis linhas PT reprojetadas na mesma parede; recorte real e sombra | pt_wall.py; hybrid/camera-fit.json; hybrid/camera_frames |
| 533–645 / 22,208–26,917 | Fundo vermelho escuro; relatório533–579, presente580–616, computador617–645; títulos serif/cursiva e headline de vídeo no617 | pt_glass.py; pt_typography |
| 646–678 / 26,917–28,292 | Faixas diagonais; close real; fade inferior; Clara vermelha INTEIRA; direção criativa branca acima; Eu sou cursivo | pt_scenes.name; complete-word-layers |
| 679–721 / 28,292–30,083 | Sala azul; quatro placas; papel com VÍDEOS; recorte real; mesa/laptop/caneca de frente; câmera/clarão | pt_scenes.blue; localized/desk-laptop.png |
| 722–798 / 30,083–33,292 | Fundo; arcos com métricas reais; close real; fade inferior; grupo PROCURAMOS/EDITORES; alvo e flecha animados | pt_scenes.value; pt_typography; objects_v7.target_layer |
| 799–845 / 33,292–35,25 | Sala de madeira; Cada corte/importa cursivo; close real; mesa e xadrez em primeiro plano | pt_scenes.chess; localized/chess-table.png |
| 846–882 / 35,25–36,792 | Gravura preservada dentro da máscara; moldura metálica com iluminação animada; saída | objects_v7.render_keyhole |
| 883–919 / 36,792–38,333 | Alvo de vidro com perspectiva; histórias que/conectam cursivo | target_v6; pt_typography |
| 920–1134 / 38,333–47,292 | Creme; três títulos sucessivos; close real; fade; setas sobre o peito, sem cobrir rosto | pt_scenes.cta; pt_typography |

## Fontes e composição

Anton: títulos condensados. Great Vibes/Pinyon Script: cursivas reais, não serif italic improvisada. Bodoni Moda: contraste editorial do vidro. Montserrat: arcos e palavras brancas fortes. Liberation Sans: nome bold italic e textos leves italic. Arquivos/licenças e hashes: `fonts/PT-font-provenance.json`.

As fontes são substitutas declaradas. Tradução usa palavras completas; não reutiliza contornos mutilados pela oclusão da referência. O motor conserva o glifo e deixa a camada frontal cobri-lo. Pesos, posição, largura, perspectiva, entrada e brilho ficam separados no código. A fonte experimental do pacote original não é aplicada automaticamente aos textos PT.

## Recorte e relógio

Clara e sua cadeira marrom são uma única camada proveniente do vídeo real. Não há uma segunda cadeira substituta por baixo. `subject-bindings.json` separa planos abertos de closes e registra escala/translação em coordenadas finais de tela. O relógio de origem está explícito; não há loop automático escondido. Tratamento do contorno estende cor do interior em faixa de4px e suaviza alpha0,45px; não é recuperação neural de fios de cabelo.

Áudio: fala original, sem nova voz. Três cláusulas em0s,9,6667s e29,375s; a última foi antecipada3quadros para terminar no corte do xadrez. A imagem usa source_start115 no azul e158 no valor, preservando continuidade e sincronismo. Música e efeitos procedurais próprios, seed329271. Stems e receita na pasta audio.

## Persistência e limites

O pacote-base foi verificado antes da adaptação:782arquivos/14cenas. Esta revisão tem manifesto próprio; não substitui a referência congelada nem a versão anterior rejeitada. `bundle.json` verifica bytes e dependências; não certifica semelhança visual.

O motor ganhou `reference_replay.py`: relógio explícito sem repetição silenciosa, recorte com alpha, composição por funções/camadas obrigatórias e reprojeção pela câmera física. Testes e fonte estão no repositório. Os adapters e todos os assets desta revisão ficam juntos neste pacote.

Limites: não é uma cópia idêntica. Pessoa, cadeira, gestos e textos são novos; o vídeo de origem não contém ações de digitar/jogar xadrez. As fontes são substitutas. Ícones/laptop/xadrez são imagens em2,5D; a arquitetura, alvo/flecha e moldura usam passes de geometria Blender. Movimento e brilho tipográfico são composições calculadas. Aprovação visual do usuário permanece pendente.
