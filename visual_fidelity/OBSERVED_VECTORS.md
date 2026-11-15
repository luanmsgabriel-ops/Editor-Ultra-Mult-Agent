# Contornos observados para tipografia

Quando a fonte original não está disponível, esticar uma fonte parecida conserva o glifo errado. `observed_vectors` preserva os contornos das palavras efetivamente visíveis e suas coordenadas por quadro. Funciona como camada de composição, sem carregar o vídeo de referência na renderização.

```python
from visual_fidelity.observed_vectors import (
    contours_from_mask, mask_from_contours, svg_from_contours,
)
paths = contours_from_mask(mask_uint8, tolerance=0.27)
lettering = mask_from_contours(paths, (width, height), supersample=2)
svg = svg_from_contours(paths, (width, height), color="#c20009")
```

A máscara precisa ser selecionada e revisada antes da vetorização. Registre quadro, FPS, caixa do recorte, método de separação e confiança. Guarde `paths`, cor e caixa por quadro em um manifesto. Na composição, rasterize no espaço local e aplique o deslocamento da caixa. Retenha a ordem dos contornos para conservar os vazios e ilhas dos glifos.

Isso não recupera uma família tipográfica completa. Os contornos cobrem apenas as palavras observadas. Não reutilize esses vetores como se escrevessem textos inéditos. Palavras ocultas, motion blur, highlights, transparência e partes confundidas com o fundo exigem revisão ou intervenção manual. Use uma fonte aproximada somente identificando o fallback.

Valide o render codificado, não apenas o SVG. Uma IoU da máscara em um recorte mede sobreposição naquela região. Ela não mede fidelidade do vídeo completo, materiais, iluminação ou movimento fora dela. A referência pode conter pessoa, enquanto uma reconstrução autorizada remove essa pessoa; isso torna a diferença RGB global insuficiente para avaliar o efeito isolado.

Teste integrado de referência329687

-720×1280,24fps,1135quadros.
-Geometria MoGe de três vistas executada de fato. Frame0 tem blur e não serve de câmera confiável;450 e1134 oferecem apenas estimativas iniciais.
-Cadeiras, painéis, objetos, títulos extrudados, sala de madeira e superfícies dobradas renderizados no Blender/Cycles com geometria e shaders escritos em Python.
-Títulos visíveis preservados em contornos por quadro. Ilustração da gravura vetorizada separadamente como desenho2D.
-Câmeras, materiais, superfícies escondidas, fontes de partes ocluídas e trajetórias de objetos continuam aproximados. A translação de sprites renderizados em3D não equivale a recuperar toda animação3D original.
-Mídia, contornos da referência e comparativo ficam fora do Git. O projeto completo acompanha a entrega privada.
