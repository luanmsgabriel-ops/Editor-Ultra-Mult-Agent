# Piloto da cascata de três cards

O template guarda posição, escala, rotação e ordem de composição em `motion.json`. Troque as três imagens pela linha de comando. A entrada A → B → C e a composição C → B → A, do fundo para a frente, seguem os mesmos quadros-chave.

A prova usa o intervalo **[92, 147)** da referência vertical em 720 × 1280 a 30 fps. O quadro 128 define as posições de repouso. Os quadros iniciais de baixa visibilidade usam marcações visuais. O OpenCV revisa os demais com fluxo óptico piramidal, checagem de ida e volta e estimativa de transformação por RANSAC.

## Reproduzir

Instale Python 3.11+, FFmpeg, ffprobe e as dependências do piloto. Use uma cópia autorizada do MP4 de referência sem alterar a ordem dos quadros. A variante aceita um bruto separado e um tempo de entrada em segundos.

```sh
python -m pip install -r pilots/motion_cards/requirements.txt
python -m pilots.motion_cards \
  --reference /caminho/referencia.mp4 \
  --cards /caminho/A.png /caminho/B.png /caminho/C.png \
  --background /caminho/bruto.mp4 --background-start 3.55 \
  --out out/motion-cards
```

Confirme a identidade das mídias no inventário antes de rodar. Para a prova original, o bruto da Clara começa em 3,55 s. Os três cards de troca são ilustrações. Mídia, recortes e resultados ficam fora do Git. A comparação visual é sem áudio.

Saídas em `out/motion-cards`

- `comparacao.mp4`, com referência, reconstrução isolada e variante sobre outro bruto.
- `motion.json`, cópia do template usado na execução.
- `relatorio.json`, com hash da fonte, intervalo, medições por card e estado dos adaptadores.
- `hyperframes/index.html` e três imagens, uma composição editável com os mesmos valores por quadro.

## Adaptadores

| Ferramenta | Entrada e verificação |
| --- | --- |
| OpenCV | O comando principal mede os cards na referência e gera os passes. O teste de troca compara os pixels de suporte da camada em quatro fases para confirmar que a troca preserva a geometria. |
| HyperFrames | Com `--hyperframes /caminho/hyperframes`, a CLI mede cortes e registra `diff` em JSON. A composição exportada usa `hf-seek`. No piloto, medições funcionaram na versão 0.9.52. O render HTML depende de Chromium com acesso a sockets locais. A prova foi renderizada com OpenCV e FFmpeg. |
| MotionClone | `--motionclone` lê uma pasta extraída de exportação editável e identifica composições, dependências e cenas. Com `--motionclone-render` e `--hyperframes`, compara-se também o MP4 exportado do mesmo trecho. O piloto aguarda um export real desse fluxo. |
| SAM 2 | `python -m pilots.motion_cards.sam2_mask` gera PNGs RGBA a partir de quadros JPEG, uma caixa no primeiro quadro e um checkpoint local. `--foreground` coloca esses PNGs na composição antes dos cards. O teste local verificou o passe RGBA. A inferência com checkpoint real fica para um ambiente com as dependências do SAM 2. |
| CoTracker | `--cotracker` registra a cobertura de visibilidade de um export NPZ de pesquisa com `pred_tracks` e `pred_visibility`. A licença CC BY-NC da maior parte do projeto reserva esse comparador aos testes não comerciais. O fluxo de produção usa OpenCV. |


- [MotionClone](https://github.com/blixvip/MotionClone)
- [HyperFrames](https://github.com/heygen-com/hyperframes)
- [SAM 2](https://github.com/facebookresearch/sam2)
- [CoTracker](https://github.com/facebookresearch/co-tracker)

## Revisão da prova

Os cards aparecem nos quadros 93, 101 e 105. A mediana da diferença de centro entre o fluxo óptico e o template foi de 0,19 px em A, 0,40 px em B e 0,75 px em C nos quadros medidos. O card C chegou a 5,36 px no percentil 95. Os picos estimados de escala após a entrada foram 18,75%, 19,98% e 22,21%.

O HyperFrames registrou SSIM médio de 0,8488 no quadro inteiro, abaixo do limiar padrão. A referência inclui pessoa, texto e fundo e o render de prova isola os cards. Use o vídeo comparativo e as medições por camada para avaliar a cascata. A comparação por pixels do quadro inteiro inclui partes fora do escopo. A primeira aplicação sobre outro bruto verifica o transporte do movimento, a ordem e os rebotes sem misturar sua avaliação com a identidade visual das imagens trocadas.
