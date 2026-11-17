# Movimento medido por elemento — versão 1

Este módulo conecta observações do vídeo às curvas que controlam o render.
Posição, escala e rotação têm canais próprios. Um zoom com centro parado tem
velocidade de translação zero e velocidade dos cantos diferente de zero.
Variação de brilho entre imagens continua sendo atividade visual, sem unidade
de velocidade geométrica.

O recurso `measured-element-motion` pertence ao Motion Kit **0.9.0**. Manifestos
0.7 e 0.8 continuam válidos para suas capacidades anteriores. O renderer
geométrico passa a **1.3.0**; os contratos antigos sem binding de movimento
mantêm sua composição. O novo código usa NumPy, SciPy, OpenCV, Pillow e FFmpeg
já presentes nas dependências do projeto. Não baixa modelos nem submete vídeo
a um gerador externo.

## Fluxo executável

1. Selecionar o elemento, intervalo, geometria de referência e pontos visíveis.
2. Medir a trajetória com tracking ou importar quadriláteros medidos/revisados.
3. Ajustar curvas por canal e por segmento contínuo.
4. Vincular curvas ao elemento de destino e ao relógio de saída.
5. Renderizar com o mesmo avaliador usado na auditoria.
6. Medir o vídeo codificado e comparar geometria, velocidade e cobertura.

O rastreador não decide sozinho se uma letra pertence ao painel que está atrás
dela. Se houver movimento independente, cada parte recebe um ID e uma curva.
Uma ROI contendo dois movimentos não cria uma identidade confiável por si só.

## Medição por tracking

```bash
python -m visual_fidelity motion-profile measure referencia.mp4 selecao.json observacoes.json
python -m visual_fidelity motion-profile fit observacoes.json curvas.json
python -m visual_fidelity motion-profile inspect curvas.json auditoria.json --csv curvas.csv
```

Exemplo de `selecao.json`, com coordenadas em pixels do raster orientado:

```json
{
  "schema": "element-motion-measurement/1",
  "rotation_ccw": 0,
  "cuts": [90],
  "elements": [{
    "id": "painel",
    "range": [30, 60],
    "seed_frame": 45,
    "roi_px": [180, 220, 320, 560],
    "reference_box_px": [180, 220, 320, 560],
    "mask_path": "mascara-da-borda.png"
  }]
}
```

`range` é início inclusivo/fim exclusivo. `seed_frame` pode ficar no meio ou no
fim do intervalo, permitindo rastreamento para os dois lados. `roi_px` e a
interseção com `mask_path` selecionam features; `reference_box_px` declara a
geometria completa. Uma seleção estreita de textura não deve virar o tamanho
do objeto. O caminho da máscara no CLI é relativo ao JSON da seleção.

`motion_observation.measure_video()` executa LK com verificação forward/backward,
RANSAC de similaridade e reancoragem da textura ao quadro seed compensado pela
transformação provisória. Essa reancoragem reduz a deriva de passos acumulados.
São registrados suporte de pontos, erros de reprojeção, cobertura espacial e
atividade de luminância. Esses valores não são probabilidades calibradas.

Depois de uma perda, a rota exige um novo seed explícito. Cortes declarados não
são atravessados. O detector simples de mudança de imagem é somente um candidato
diagnóstico; um flash não é automaticamente convertido em deslocamento.

### Observações de quadriláteros

```bash
python -m visual_fidelity motion-profile import-quads observacoes-com-source.json quads-medidos.json observacoes-quads.json
```

`motion_quad_observation.observations_from_quads(source, spec)` converte quatro
cantos ordenados de cada quadro para o mesmo contrato de observações. Isso
permite consumir contornos de máscaras, marcações revisadas e resultados de
outros trackers sem acoplar o ajuste de curvas a um único modelo.

O adaptador mede resíduos contra uma similaridade 2D. Perspectiva incompatível,
quad incompleto e quad inválido não devem ser reduzidos silenciosamente a zoom.
A origem das marcações e máscaras precisa acompanhar a observação; a conversão
não comprova como esses dados foram obtidos.

## Contratos e relógio

| Artefato | Schema | Papel |
|---|---|---|
| Observações | `element-motion-observations/1` | Geometria e evidência por quadro |
| Curvas | `element-motion-curves/1` | Coeficientes, intervalos válidos e resíduos |
| Binding | `element-motion-binding/1` | Elemento de destino, pivô, escala base e tempo |
| Consumo | `element-motion-consumption/1` | Curvas e quadros realmente usados no render |
| Auditoria | `element-motion-audit/1` | Velocidades, acelerações e cobertura por canal |
| Comparação | `element-motion-comparison/1` | Erros geométricos no relógio declarado |

`source` conserva SHA-256, largura, altura, orientação, `time_base` racional e
`first_pts`. Cada amostra possui `frame`, `pts`, `segment`, posição, escala,
ângulo desenrolado, visibilidade, status e confiança quando disponível.

```text
time_s = (pts - first_pts) × time_base
```

A subtração e conversão racional precedem o float usado na interpolação. PTS
precisam crescer estritamente. VFR é preservado pela medição; imagens repetidas
com PTS distintos podem representar uma pausa real. Rotação de contêiner não
nula exige declaração explícita do raster; pixels não quadrados exigem
normalização documentada antes da análise.

Ausência de posição não obriga a inventar posição zero. Ausência de escala não
é escala 1. `confidence: null` permanece desconhecida. `visibility` descreve
evidência/oclusão e não é um canal de opacidade da camada.

## Ajuste e derivadas

`fit_profile()` oferece PCHIP e interpolação linear. A escala é ajustada em
logaritmo e volta por exponencial; o ângulo já desenrolado mantém voltas completas.
O tracking usa a hipótese declarada de menor passo angular desde o seed; um
vídeo achatado não revela voltas extras ocorridas entre dois quadros.

PCHIP conserva os pontos e reversões observados. Não é um filtro universal de
ruído. RANSAC e reancoragem atuam antes do ajuste; rastros ainda ruidosos precisam
de revisão ou outro método explícito. Resíduos de interpolação nos próprios
knots não medem precisão do tracker.

`max_gap_frames=1` exige índices consecutivos. Um valor 2 autoriza interpolar
sobre um quadro omitido, com isso registrado. Amostra explicitamente ausente,
oculta ou rejeitada sempre interrompe o canal; uma mudança de segmento também.
Fora da cobertura, o avaliador devolve `None` e o binding recusa o render. Não há
congelamento, extrapolação ou preenchimento silencioso.

`evaluate_element()` e `evaluate_kinematics()` avaliam os mesmos coeficientes.
As métricas usam px/s, px/s², graus/s e log-escala/s separadamente. Velocidade
normalizada usa uma única medida espacial, a diagonal da imagem, para ambos os
eixos. Os quatro probes de canto exigem posição, escala, ângulo e geometria de
referência suficiente. Uma única observação tem pose, mas não velocidade medida.

PCHIP tem derivada primeira contínua dentro do segmento; a aceleração pode
mudar nos knots. A implementação informa a derivada da direita nos knots
internos e da esquerda no último. Não derive através de cortes ou gaps.

## Aplicação real na timeline

```bash
python -m visual_fidelity motion-profile bind timeline.json curvas.json bindings.json timeline-medida.json
python -m visual_fidelity.geometric_video timeline-medida.json prova-v1.mp4
```

`bindings.json` é uma lista, por exemplo:

```json
[{
  "target": "insert",
  "interval": [0, 30],
  "element_id": "painel",
  "channels": ["position", "scale", "angle"],
  "pivot_px": [360, 640],
  "base_scale": 0.5,
  "time_map": [
    {"output_time": 0, "source_time": 1},
    {"output_time": 0.9666666666666667, "source_time": 1.9666666666666666}
  ]
}]
```

O exemplo supõe 30 quadros a 30 fps e observações suficientes até o último
timestamp. Não confundir a duração do trecho (`30/30`) com o tempo de sua última
amostra (`29/30`). O mapa liga segundos de saída a segundos decorridos da fonte,
preservando amostras fracionárias. Dobrar a duração reduz a velocidade à metade
e a aceleração a um quarto dentro de trechos lineares do mapa temporal.

No renderer geométrico, o estágio `masked_canvas` aplica a transformação após
viewport e máscara, sobre o canvas já composto da camada. Portanto:

- `pivot_px` pertence a esse raster; a posição medida define o destino do pivô.
- `base_scale` liga a dimensão da camada nesse estágio à geometria de referência.
- RGB e alpha/cobertura recebem juntos a mesma transformação premultiplicada.
- Os alvos são `insert`, `foreground` e `layer:<id>`.
- Uma `foreground.box` adicional conflita com esse posicionamento e é recusada.
- Quando há `layers`, vincule `layer:<id>`; o `insert` do topo não é consumido.

`Transform.x/y` são deslocamentos OpenCV, não posições absolutas. O binding
subtrai o pivô local da posição desejada. A escala aplicada é a escala observada
multiplicada por `base_scale` e pelo `spatial_scale` uniforme declarado. Para
outro formato, declare também o enquadramento por `spatial_offset_px`; não
estique 9:16 para 16:9.

`studio_edit` recebe binding inline em `layer.motion` ou `person.motion`, com
estágio `local_rgba`. O pivô fica depois do resize da camada. O relógio vem do
frame absoluto de saída, não do `u` normalizado do plano. Canais autorados que
conflitam, `quad_file`, animação adicional de entrada e lentes não implementadas
são recusados explicitamente.

Na timeline geométrica, `motion_profiles` armazena cada perfil uma única vez,
indexado por SHA-256. Cada binding de quadro guarda a referência compacta.
O pool cria um snapshot privado e valida relógio, coeficientes e hash antes
do render. O relatório registra somente transformações realmente consumidas.

Escolha nomes distintos para manifesto e sidecar: `timeline-medida.json` e
`prova-v1.mp4`. O renderer grava `prova-v1.json`; colisões com inputs, sidecars,
temporários ou exports anteriores são recusadas antes da codificação.

### Cadência e música

```bash
python -m visual_fidelity reference-cadence apply timeline.json cadencia.json marcos.json timeline-retimada.json \
  --motion-profile curvas.json --motion-bindings bindings-sem-time-map.json
```

Nesse caminho, a cadência fornece o mapa temporal. O binding não deve fornecer
outro. O SHA da fonte precisa coincidir. A rota de cadência continua exigindo
seu relógio CFR compatível; para VFR, use o binding com mapa explícito.

O flow agregado por regiões permanece diagnóstico. Ele não tem a identidade e
a geometria necessárias para virar uma trajetória automaticamente. Janelas
candidatas de transição ficam registradas como não classificadas até revisão;
movimentos contínuos podem ser medidos pelo novo comando dentro dessas janelas.

## Comparar o resultado codificado

Meça novamente o MP4 exportado, ajuste o perfil observado desse arquivo e use:

```bash
python -m visual_fidelity motion-profile compare curvas-referencia.json curvas-do-mp4.json comparacao.json --spec alinhamento.json
```

O alinhamento opcional usa `time_map` com pares `reference_time/candidate_time`,
um `spatial_map` uniforme e pares explícitos de IDs. Sem mapa temporal, os tempos
são comparados diretamente. Não existe DTW nem busca automática de um atraso
que esconda erro de timing. As velocidades respeitam a regra da cadeia do mapa.

A grade contém os knots de ambos os perfis alinhados e subamostras declaradas,
para não ignorar uma excursão entre endpoints iguais. Cada linha informa quais
canais são observados, interpolados ou ausentes. Mais amostras da curva não
produzem nova evidência do vídeo. Cobertura e erro permanecem separados.

A auditoria relata translação, cantos, escala, ângulo e aceleração. A comparação
relata posição, cantos, tamanho relativo, ângulo e velocidades por canal. Picos
amostrados, platôs e intervalos sem suporte devem ser identificados antes de
atribuir erro temporal. Nenhum relatório produz uma porcentagem universal de
fidelidade ou aprovação estética.

`peak_timing` compara separadamente velocidade do centro, dos cantos, angular
e de log-escala. Um horário único exige pico interior com vizinhos válidos dos
dois lados. Platôs recebem intervalos; gaps, máximos nas bordas e picos ambíguos
não recebem um erro temporal escalar. A tolerância e a grade ficam no relatório.

## Ferramenta do aplicativo

O servidor MCP expõe `editor_measure_motion` para medir vídeos já importados
por ID de projeto e de arquivo. A fila usa revisão esperada e chave de
idempotência. Uma máscara chega por `mask_asset_id` do mesmo projeto, e não por
um caminho arbitrário. O trabalho entrega observações, perfil, auditoria e CSV
como artefatos, verificando os hashes da fonte e das máscaras.

O estado `evidence_not_applied` distingue essa medição da aplicação. A nova
ferramenta não vincula curvas automaticamente ao executor nativo do aplicativo.
Os bindings deste manual são consumidos por `geometric_video` e `studio_edit`;
a conexão automática com `native.render_bundle` ainda exige um adaptador.
Alterações no projeto ou nos arquivos invalidam a atualidade da evidência,
sem apagar o histórico. Veja os limites de CPU e o contrato do servidor em
[Editor Ultra dentro do ChatGPT](../docs/chatgpt-app.md#medir-movimento-por-elemento).

## Limites desta versão

Esta versão executa similaridade 2D: translação, escala uniforme e rotação. Não
recupera câmera física, profundidade, homografia geral, morph, deformação,
curvas de wipe ou separação de alpha de um fade achatado. Essas rotas continuam
exigindo observações e executores próprios. `device_scene` e `device_camera`
mantêm sua função 3D; não recebem uma curva 2D como se fosse câmera resolvida.

Provas sintéticas e resíduos internos demonstram contratos e funcionamento
técnico. A comparação visual contínua do render, a audição e a aprovação do
usuário têm registros separados. Os arquivos originais e as revisões anteriores
continuam preservados.
