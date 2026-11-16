# Leitura e reaplicação de camadas

Depois da [análise de cadência](REFERENCE_CADENCE.md), use `reference-layers`
para distinguir a geometria da faixa, a ordem em relação ao sujeito e a
sequência de imagens que passam dentro dela. O compositor coloca as faixas
de fundo, o sujeito rotoscopado e as faixas de frente nessa ordem.

```sh
python -m visual_fidelity reference-layers analyze referencia.mp4 trajetoria.json \
  'recortes/{frame:04d}.png' efeito.json --clean-frame 285

python -m visual_fidelity reference-layers apply timeline.json efeito.json \
  paleta.json timeline-compilada.json --palette --render teste.mp4
```

A análise usa vídeo CFR, amostras de máscara em quadros contíguos e um
quadro com a cena antes da inserção ou no início de um fade. A geometria
pode vir da medição anterior. Para um X, a união deve conservar a identidade
de suas formas filhas em ordem consistente. Recortes de referência podem vir
da rotoscopia ou segmentação e precisam estar no raster analisado. Quando
há pouca movimentação do sujeito, um único recorte aproximado pode servir
para a análise. Na renderização, use o recorte do novo bruto para cada quadro.

O analisador mede mudanças dentro e fora do sujeito contra o quadro base,
em regiões isoladas das outras faixas. Votos com evidência consistente
definem a profundidade por faixa. A ausência de evidência suficiente fica
registrada como profundidade pendente. O detector de trocas compara os
mesmos pixels nas duas imagens consecutivas dentro de cada faixa e afasta
bordas, intersecções e a silhueta do sujeito. As pontuações e os quadros
usados ficam no template. Valide candidatos em referências em que movimento
interno, mudanças de exposição ou movimento da câmera produzem variações
parecidas com cortes. Este método cobre profundidade estável por faixa.

Na reaplicação, forneça `--subject sujeito.json` para vincular o novo bruto
e seus recortes em toda a faixa do efeito. O JSON recebe `source`,
`start_frame`, `fps`, `matte_pattern` e o `view` opcional. O vídeo e o
alpha usam o mesmo quadro e o mesmo crop. Também é possível vincular o
sujeito diretamente na timeline.
Cada entrada de `paleta.json` seleciona uma fonte existente no projeto
e o crop opcional, por exemplo `{"source":"floresta","view":[0.5,0.5,1]}`.
O motor preenche os espaços automaticamente a partir da aparência visível e
prefere uma fotografia distinta a cada troca quando a paleta permite.
Também aceita um objeto sem `--palette` que vincula diretamente os IDs de
conteúdo às fontes. Para vídeo, a vinculação pode incluir `start_frame` e
`fps` para avançar no tempo dentro do espaço de conteúdo. Use a mesma taxa
do trecho de referência para preservar trocas com um quadro de duração.
O relatório enumera os espaços que não aparecem na saída.

No teste 329796, quadros 285 a 335, o motor inferiu uma faixa na frente
e outra atrás e montou as duas sequências separadas usando as imagens
disponíveis e a filmagem do novo piloto. A geometria veio das duas faixas
rastreadas anteriormente e o recorte aproximado do piloto da referência
foi traçado sobre o quadro de entrada. A reconstrução usa um novo bruto
com recortes individuais por quadro.
