# Fidelidade visual por referência

O motor mede tipografia no frame, aceita wordmarks vetoriais, renderiza produtos em 3D e insere uma fotografia ou um render RGBA na timeline. Mantém fontes, fotos, perfis extraídos, texturas e filmagens no projeto local. O piloto Origins testa a troca dos materiais preservando o monograma e a cadência dos cortes.

## Instalação

Python 3.11+, FFmpeg com libx264 e `python -m pip install -r visual_fidelity/requirements.txt`. Para ranquear fontes, Pillow deve ter RAQM/HarfBuzz. Para o render de produto, Blender 4.3+ no PATH. Para importar SVG no piloto, Inkscape no PATH. Servidores ou Windows sem as fontes DejaVu nos caminhos padrão podem configurar as constantes FONT e MONO em origins/scenes.py.

## Tipografia e marca

O ranking renderiza a palavra de referência usando HarfBuzz via RAQM. Compara contorno, distribuição horizontal e largura. FontTools fornece metadados e eixos variáveis. Use um recorte de uma linha e fontes candidatas já disponíveis ou licenciadas. No caso de arte desenhada sob medida, prefira o SVG de origem e use o modo trace em um recorte plano quando só houver uma imagem.

```sh
python -m visual_fidelity typography rank quadro.png --crop 310 848 595 881 \
  --text 'Origins Of is a home' --font /assets/Satoshi-Medium.otf \
  --font /assets/OutraFonte.ttf --output out/fontes.json --preview out/fontes.png

python -m visual_fidelity typography trace wordmark.png \
  --crop 0 0 1024 300 --output out/wordmark.svg
```

Para Origins, o [estúdio original](https://www.slsh.studio/works/origins-of) documenta Satoshi nos textos e um wordmark desenhado para a marca. A [família Satoshi](https://www.fontshare.com/fonts/satoshi) é uma entrada local do render. O modo trace preserva os vazios das letras. Ele estima somente o desenho visível.

## Produto

```sh
python -m visual_fidelity cap --output out/bone.png --scene out/bone.blend \
  --logo /assets/monograma.png --base-color /assets/tecido-color.png \
  --normal /assets/tecido-normal.png --roughness /assets/tecido-roughness.png

python -m visual_fidelity reconstruct colmap /assets/views out/colmap --gpu --dense
python -m visual_fidelity reconstruct trellis /assets/bone.png out/bone.glb \
  --python /ambientes/trellis2/bin/python

python -m visual_fidelity asset out/bone.glb --output out/bone-asset.png --yaw 12 --pitch 14
```

O boné usa malha, costura, trama e câmera configuradas no Blender/Cycles. Os mapas externos são opcionais. O logo PNG pode ser aplicado à superfície no Blender. O comando asset lê GLB, glTF ou malha PLY com faces. A placa RGBA também pode vir de uma foto recortada e posicionada na tela vertical do plano final.

COLMAP precisa de fotos nítidas, sobrepostas, com múltiplos ângulos e captura consistente. Sem `--dense`, o provedor retorna modelos esparsos. A opção densa usa uma instalação COLMAP com CUDA e produz `dense/mesh.ply`, que ainda pode precisar de material e acabamento. TRELLIS.2 roda no ambiente oficial instalado separadamente e gera um GLB texturizado. Provedores 3D opcionais podem exigir GPU, modelos e um ajuste posterior de escala, câmera e textura.

## Montagem e verificação

```sh
python -m visual_fidelity origins out/origins --reference /projeto/origins.mp4 \
  --font /assets/Satoshi-Medium.otf --wordmark out/wordmark.svg \
  --cap-plate out/bone.png --cap-logo baked

python -m visual_fidelity measure /projeto/origins.mp4 out/origins/motion.mp4
```

A grade, a posição do monograma, os cortes de 30 fps e os sons sintetizados do piloto usam `origins/timeline.json`. O parâmetro `--reference` extrai apenas o monograma dessa referência conhecida no quadro calibrado. Para repetir usando um perfil local, passe `--mark-profile`. Use `--cap-logo baked` se o PNG já contiver o logo, ou `overlay` se o motor for aplicar o monograma. Os casos que omitem a placa externa ou wordmark usam a versão procedural ou texto editável como alternativas. O comando de medida compara 28 cortes e seis amostras locais do monograma Origins. Para outra referência, comece pela decupagem e pelos comandos genéricos de tipografia e produto, depois calibre a timeline e as regiões de medição correspondentes.
