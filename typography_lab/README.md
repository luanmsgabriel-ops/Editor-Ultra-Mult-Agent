# Tipografia híbrida — primeira família de teste

Entrega: **Motion Referencia Condensada Regular**, versão 0.100, arquivo TrueType instalável. A fonte tem 138 caracteres codificados, 141 glifos internos, maiúsculas, minúsculas, números, acentos portugueses e pontuação declarada em `glyph-manifest.json`.

O desenho parte da tipografia vermelha alta do vídeo 329687, especialmente o quadro 48. O alfabeto foi gerado como imagem RGBA, depois separado, normalizado e convertido em curvas e contornos TrueType. É uma interpretação coerente do estilo; **não é a fonte original identificada nem uma promessa de igualdade visual**. Há espaço para refinamento óptico de desenho e kerning. Letras ausentes e partes ocultas não foram recuperadas magicamente: foram interpretadas.

## Usar

Instale `fonts/MotionReferenciaCondensada-Regular.ttf` no sistema ou importe o arquivo no editor que aceite fontes personalizadas. Procure a família **Motion Referencia Condensada**. Para renderizar por código, passe o caminho da TTF ao Pillow/FreeType ou ao mecanismo de texto utilizado.

`Previa-Fonte-Motion-V5.png` foi renderizada com a TTF efetiva. Ela mostra QANDAY, Omad, alfabeto, números, acentos e frases inéditas. Os desenhos não estão apenas colados nessa prévia.

## Letterings preservados

A pasta `letterings` contém os títulos cursivos `qilib`, `ushbu` e a composição `Ushbu Xulosalar yordamida`, em SVG e PNG transparente. Os SVGs refinados usam curvas Bézier; arquivos `.raw.svg` e `contours.json` guardam a extração anterior. São palavras fixas observadas, não alfabetos. Mantêm a inclinação observada; não equivalem a uma fonte cursiva completa.

## Reproduzir a fonte

Instale Python 3 com `fonttools`, `numpy`, `scipy`, `opencv-python` e `Pillow`.

```sh
python scripts/build_font.py
python scripts/preview_font.py
python scripts/validate_font.py
```

O construtor também aceita outro atlas compatível e diretório de saída:

```sh
python scripts/build_font.py --atlas /caminho/atlas.png --output-dir /caminho/pacote
```

O protótipo exige um atlas RGBA de 64 glifos em 8 linhas e 8 colunas na ordem abaixo. Ele detecta separações vazias e recusa contagens incompatíveis. Não é um reconhecedor universal de qualquer imagem de alfabeto; imagens com letras extras, unidas ou ordem incorreta exigem revisão antes da conversão.

```
A B C D E F G H
I J K L M N O P
Q R S T U V W X
Y Z a b c d e f
g h i j k l m n
o p q r s t u v
w x y z 0 1 2 3
4 5 6 7 8 9 ? !
```

Acentos e pontuação adicional são construídos em vetor. As letras i acentuadas usam base sem ponto. As métricas normalizam capitais em 800 unidades, altura-x em 560 e descendentes em -180, em um em de 1000 unidades. Kerning inicial cobre 15 pares; não é uma revisão tipográfica completa.

## Fluxo aplicado ao projeto

1. Identificar a fonte original quando possível e distinguir desenho de efeitos.
2. Preservar palavras especiais como letterings quando conexões e floreios forem decisivos.
3. Usar geração para propostas de desenhos e caracteres ausentes quando necessário.
4. Vetorizar, ajustar curvas, normalizar métricas e codificar os caracteres.
5. Exportar uma fonte real e verificar carregamento, cobertura, acentos, espaçamento e renderização de frases.
6. Guardar fonte, atlas, prompt, SVGs, cobertura, versão e limitações. Separar materiais e animação da fonte.

O arquivo `assets/glyph-atlas-generated.png` é a imagem de letras gerada no chat com fundo transparente; `assets/generation-prompt.txt` registra o prompt. Os SVGs de cada caractere ficam em `glyphs`. O nome desta família é próprio do protótipo, não uma identificação comercial da referência.

A orientação foi registrada em AGENTS.md na branch `pilot/motion-cards-hibrido`. Os scripts e esta documentação são mantidos em `typography_lab`; a mídia gerada acompanha este pacote. Esta etapa não substitui automaticamente as fontes de todo o vídeo de 47 segundos.
