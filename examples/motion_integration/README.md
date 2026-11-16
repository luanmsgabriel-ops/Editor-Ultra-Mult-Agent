# Provas locais dos novos adaptadores

As receitas demonstram movimento e contratos técnicos. Não representam um estilo
obrigatório, reconstrução de referência nem aprovação visual de um vídeo real.
Os exports e fontes ficam no pacote de mídia do projeto, fora do Git.

```sh
python -m editorial_engine motion probe
python -m editorial_engine motion render motionlab examples/motion_integration/motionlab-2d.json out/motion-2d --samples 4
python -m editorial_engine motion render motionlab examples/motion_integration/motionlab-3d.json out/motion-3d --samples 4
python -m editorial_engine motion render motngrfx examples/motion_integration/type-volume.json out/type-volume --font /projeto/fontes/Fonte-Regular.ttf --font-license "Termos da fonte no pacote do projeto"
python -m editorial_engine motion preview /projeto/bruto.mp4 out/effect-proof --effect local_rgb_split --params examples/motion_integration/rgb-split.json --duration-s 2
```

Cada destino deve ser novo. As receitas são de 48 frames a 24 fps. Para usar uma
sequência em um bruto com outro FPS, renderize a receita explicitamente naquele
relógio e ajuste a duração e os keyframes. O importador não repete frames.

Os renders de Motion Lab e MOTNGRFX geram `motion-layer.json`, `inventory.json` e
`motion-contact.png`, além dos arquivos do produtor. O inventário é aceito por
`prepare --assets`, e a direção pode vincular o recurso a `native.motion_layer`
ou `native.motion_behind`. A modalidade com oclusão exige a máscara do novo bruto.
Leia [o guia de integração](../../docs/motion-integration.md).
