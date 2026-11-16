# Calibração de pessoa e ilustração

`visual_fidelity.subject_alignment` 1.0.0 resolve o encaixe de uma fonte visual
na pessoa do vídeo base com escala uniforme, rotação e deslocamento medidos.
A cabeça e os ombros participam do ajuste. O resultado preserva a proporção;
não estica um eixo para esconder diferenças anatômicas.

## Correção que originou o componente

Na revisão do teste 331237, o usuário apontou uma ilustração maior que a pessoa
e pediu um leve recuo para encaixá-la. O adaptador anterior acompanhava posições
com um campo de deslocamento, sem calibrar a escala relativa do sujeito. A
correção reutilizável é medir os mesmos pontos na fonte e no alvo, resolver a
transformação e bloquear encaixes incompatíveis. A regressão verifica a escala,
a rotação, o pivô, a proporção, a vinculação aos arquivos e as lacunas de dados.

O percentual deve vir das medidas do plano. Não existe redução universal de
10% ou 20%. A mesma referência pode exigir escalas distintas ao longo do gesto.
Um recuo autorado adicional usa `scale_adjustment`, identificado separadamente
da escala medida. Isso é alteração de composição 2D, não distância 3D estimada.

## Contrato de entrada

```python
from visual_fidelity.subject_alignment import (
    calibrate_alignment, validate_alignment_binding,
    alignment_for_frame, warp_aligned_rgba,
)

plan = calibrate_alignment(request)
validate_alignment_binding(plan, runtime_binding)
sample = alignment_for_frame(plan, frame)
layer = warp_aligned_rgba(source_rgb_or_rgba, sample["matrix"], (width, height))
```

`request` tem `schema: "subject-alignment/1"`, `source`, `base`, `timeline`,
`settings` e `samples`. Todos os campos de vínculo descritos abaixo são
obrigatórios. A aplicação calcula SHA-256 dos arquivos realmente importados;
um hash diferente, sozinho, não prova conteúdo ou identidade independente.

| Campo | Conteúdo |
| --- | --- |
| `source` e `base` | Objeto com `kind`, `sha256`, `raster`, `viewport_xywh`, `fps`, `frames`, `revision` e `clock`. |
| `kind` | `image`, `video` ou `sequence`; sequência usa hash de sua lista ordenada e verificada de frames. |
| `raster` | `[largura, altura]` dos pixels reais do asset. |
| `viewport_xywh` | `[x, y, largura, altura]` da região útil dentro desse raster. |
| `fps` | String racional explícita, por exemplo `"30/1"`. Todos os relógios devem concordar. |
| `frames` | Contagem real da mídia; imagem estática tem um frame. |
| `revision` | Revisão do asset/base, independente da revisão da timeline. |
| `clock` | `{"start_frame": 0, "step": 1}` para vídeo/sequência. Imagem exige `{"start_frame": 0, "step": 0}`. |
| `coordinate_mapping` | Opcional: raster e viewport em que os landmarks foram medidos, com `units: "pixels"` ou `"normalized"`. O padrão é o próprio raster/viewport do asset. |
| `timeline` | Objeto com `revision`, `raster`, `fps`, `frames`; base e canvas têm o mesmo raster. |
| `samples` | Lista cronológica sem duplicatas: `frame`, `source_frame`, `base_frame`, `source_landmarks`, `base_landmarks`. |
| `evidence` | Metadados preservados, por exemplo hash do tracking, método, frames e observação visual. Não substituem a inspeção. |

As coordenadas normalizadas são relativas ao **raster de medida inteiro**.
Primeiro convertem-se em pixels; em seguida o viewport de medida é mapeado ao
viewport do asset. Por exemplo, landmarks medidos no vídeo 720×1280 podem ser
usados com uma imagem de 720×406 extraída da faixa `[0, 437, 720, 406]`:

```json
{
  "raster": [720, 406],
  "viewport_xywh": [0, 0, 720, 406],
  "coordinate_mapping": {
    "raster": [720, 1280],
    "viewport_xywh": [0, 437, 720, 406],
    "units": "pixels"
  }
}
```

Esse mapeamento remove o offset de 437 pixels. O módulo rejeita mudanças de
aspecto entre viewports. A matriz resultante mapeia **pixels reais da imagem
fonte para pixels reais do canvas**; não é uma posição normalizada do portal.

Cada landmark tem `xy`, `state` e `confidence`:

```json
{"xy": [382.0, 539.0], "state": "detected", "confidence": 0.94}
```

`confidence: null` permanece desconhecida e não autoriza um ponto detectado.
Uma medição manual pode conservar esse valor nulo quando possui
`state: "measured"`, `reviewed: true` e um `method` explícito. O peso de uma
medição revisada não se apresenta como probabilidade de acerto do detector.
Pontos `inferred` exigem `allow_inferred: true`; a origem inferida continua
registrada. Não há detecção, tracking nem interpolação dentro deste módulo.

## Ajuste e limites

Os controles padrão são os olhos, nariz, orelhas e ambos os ombros. Os olhos e
ombros são obrigatórios. É possível selecionar controles manuais como
`head_top`, `chin`, `head_left`, `head_right` e `head_center`; continuam
obrigatórios ambos os ombros e pelo menos dois controles de cabeça.

Cabeça e ombros recebem metade do peso total cada. Dentro do grupo, a
confiabilidade dos pares distribui os pesos. A solução por mínimos quadrados
usa todos os pontos válidos. Um ponto discrepante não é apagado para fabricar
uma aprovação. Controles colineares, reflexão, baixa confiança e ausência de
âncoras obrigatórias bloqueiam o ajuste.

| Parâmetro | Padrão | Função |
| --- | --- | --- |
| `min_confidence` | `0.6` | Limite de aceitação de controles detectados/inferidos. |
| `max_rmse_px` | `12` | Erro ponderado máximo, em pixels do canvas. |
| `max_anchor_error_px` | `24` | Erro máximo de qualquer controle usado. |
| `min_scale`, `max_scale` | `0.25`, `4` | Limites da escala medida e da escala final. |
| `max_rotation_deg` | `25` | Rotação máxima absoluta no plano da tela. |
| `scale_adjustment` | `1` | Recuo/ampliação autorada adicional, aplicada depois do fit. |
| `pivot` | `head_center` | Centro dos olhos, ou média dos controles de cabeça quando olhos não selecionados; alternativa `shoulder_center`. |
| `allow_inferred` | `false` | Permite controles explicitamente inferidos, preservando sua classificação. |

Tolerâncias em pixels precisam corresponder ao raster e ao objetivo do projeto.
São limites técnicos configuráveis, não um critério universal de beleza.
Resíduos antes e depois de `scale_adjustment` são conferidos. Um ajuste
adicional exagerado também bloqueia o plano. A tolerância não deve ser alargada
apenas para esconder um erro observado.

O plano inclui matriz 2×3, escala, rotação, deslocamento, pivô, resíduos por
controle, RMSE, gaps, confiança declarada, footprints e status. A cópia integral
é selada por SHA-256. O selo detecta alteração acidental; não é assinatura de
autoridade nem aprovação perceptiva. Recalibrar produz uma nova revisão.

## Integração com a composição

`validate_alignment_binding(plan, runtime_binding)` exige `source`, `base` e
`timeline` atuais. Todos os campos de mídia da tabela são conferidos.
`coordinate_mapping` pode ser omitido no runtime; se fornecido, precisa ser
igual ao mapeamento selado. Trocar bruto, imagem, raster, crop, FPS, relógio ou
revisão invalida o vínculo. Cada `source_frame`/`base_frame` precisa corresponder
ao relógio explícito da composição.

`alignment_for_frame` rejeita plano bloqueado e frame ausente. Um conjunto
esparso pode servir para diagnóstico, com `complete_coverage: false`; ele não
autoriza os quadros intermediários. Não se congela o último controle, não se
interpolam perdas e não se transpõem controles de uma pessoa para outra.

`warp_aligned_rgba` recebe RGB ou RGBA straight de 8 bits e devolve RGBA straight.
O redimensionamento usa alpha premultiplicado, evitando que cores invisíveis
contaminem a borda. Matriz com shear, reflexão ou escalas distintas por eixo é
recusada.

O portal e a máscara de oclusão continuam no canvas e no relógio do vídeo base;
a calibração transforma somente o conteúdo. Não aplicar depois um `placement`
que estique a camada já calibrada. A camada deve entrar no canvas com posição e
tamanho unitários, ou ser consumida diretamente pelo compositor.

**Reduzir um plate opaco deixa bordas sem imagem.** `coverage` calcula a
cobertura geométrica do viewport alvo, informa os cantos cobertos e sinaliza
`requires_background`. Isso é conservador: o portal ativo pode ocupar apenas
parte do viewport. O compositor verifica a máscara efetiva e o alpha real em
cada frame. O módulo não inventa cenário, não amplia o fundo junto do sujeito
e não preenche falhas com pixels da referência. Para a produção, usar sujeito
com alpha e backplate independente, ou gerar a cena já no enquadramento medido.

## Manifesto nativo de portal

`visual_fidelity.planar_portal` 1.1.0 aceita o plano diretamente em
`subject_alignment.plan`. O plano é um objeto JSON incorporado ao manifesto;
não é um caminho de arquivo resolvido implicitamente. Esta configuração usa
`screen_reveal` e exclui `placement` e `source_quad`, pois a matriz já posiciona
o conteúdo em pixels do canvas. O polígono de visibilidade e a oclusão continuam
no sistema de coordenadas do vídeo base.

Exemplo de montagem do manifesto quando o plano vincula uma imagem de
ilustração e um vídeo base novo. `plan` deve vir de `calibrate_alignment` e
conter uma amostra válida para **cada frame com opacidade maior que zero**:

```python
manifest = {
    "schema": "planar-portal/1",
    "revision": plan["timeline"]["revision"],
    "width": plan["timeline"]["raster"][0],
    "height": plan["timeline"]["raster"][1],
    "fps": plan["timeline"]["fps"],
    "frames": plan["timeline"]["frames"],
    "base": {
        "kind": "video",
        "path": "base-nova-pessoa.mp4",
        "sha256": plan["base"]["sha256"],
        "origin": "Vídeo base novo, com atuação e origem documentadas",
        "revision": plan["base"]["revision"],
        "viewport_xywh": plan["base"]["viewport_xywh"],
        "clock": plan["base"]["clock"],
    },
    "insert": {
        "kind": "image",
        "path": "ilustracao.png",
        "sha256": plan["source"]["sha256"],
        "origin": "Ilustração produzida para a nova personagem",
        "revision": plan["source"]["revision"],
        "viewport_xywh": plan["source"]["viewport_xywh"],
        "static": True,
    },
    "mapping": "screen_reveal",
    "subject_alignment": {
        "plan": plan,
        "uncovered_policy": "reject",
    },
    "geometry": {"keyframes": authored_portal_keyframes},
}
```

`authored_portal_keyframes` conserva quad, frame, opacidade e easing autorados;
deve cobrir o primeiro e o último frame da timeline. A imagem estática declara
`static: true` e não recebe `clock` no manifesto de portal. Seu vínculo de
calibração conserva o relógio estacionário explícito com `step: 0`.
Uma inserção em vídeo ou sequência usa `clock` com `step: 1`, como os demais
recursos temporais do motor. Isso não converte a ilustração estática em atuação.

O render nativo calcula o vínculo a partir dos arquivos realmente importados:

| Parâmetros vinculados | Origem na execução |
| --- | --- |
| Hash e tipo | Arquivo verificado ou lista ordenada verificada da sequência. |
| Raster e contagem | Cabeçalhos das imagens ou inspeção/decodificação do vídeo. |
| Viewport e revisão do recurso | Campos explícitos da base e da inserção no manifesto. O viewport omitido significa o raster inteiro. |
| FPS e relógio | Cadência validada e `start_frame`/`step` do recurso. |
| Revisão, raster e duração da montagem | Campos superiores do manifesto. |

Mudar um desses parâmetros exige recalibração ou nova vinculação revisada.
Não copiar uma revisão antiga apenas para satisfazer o validador. Os objetos
`source`, `base` e `timeline` do plano são comparados com os parâmetros atuais
do manifesto e a mídia efetiva.

### Tratamento explícito das áreas descobertas

`uncovered_policy` é obrigatório ao ativar a calibração:

| Política | Comportamento |
| --- | --- |
| `reject` | Bloqueia se uma região visível do portal precisar de cobertura que a inserção não fornece. Produzir o fundo necessário ou rever o asset antes de renderizar. |
| `reveal_base` | Mantém a transparência da camada e deixa o vídeo base atual aparecer. Registra os frames e a quantidade de pixels descobertos no recibo. |

`reveal_base` é uma decisão de composição explícita. Na recriação com outra
pessoa, o vídeo base deve ser o novo material autorizado pelo projeto; essa
política não permite reintroduzir a pessoa da referência. O render de portal
valida bytes e geometria, enquanto o fluxo de recriação verifica o papel e a
proveniência dos recursos. Arquivos com hashes exclusivos não comprovam
independência semântica.

A cobertura final considera a janela efetiva, opacidade e oclusão de cada
frame. Uma fonte menor que o viewport pode cobrir completamente um portal
menor. Uma região totalmente ocultada não exige preenchimento invisível.
Opacidade parcial e oclusão parcial não eliminam a obrigação de cobrir a
parcela ainda visível. A comparação aceita arredondamento de três níveis de
alpha de 8 bits; não é um detector de diferenças perceptivas.

O caminho nativo aplica a matriz diretamente no warp da região útil, sem
gerar uma segunda imagem float do canvas inteiro. O plano é validado uma vez
antes de produzir saídas. Frames sem portal visível podem dispensar amostra;
frames ativos ausentes são bloqueados, sem hold ou interpolação automática.
O recibo inclui hash do plano, política adotada, ocorrências de área descoberta
e `depth_reconstruction: false`. A aprovação visual permanece pendente.

O adaptador `bundled.planar_portal` continua sendo a rota nativa na fila de
produção. Registrar como inputs com hash o manifesto e todas as mídias
referenciadas, incluindo cada arquivo de uma sequência. Incorporar o plano
ao manifesto também o vincula ao hash desse input. Consultar
`docs/planar-portal.md` para o contrato da operação `planar_portal`.

## Evidência e limites do teste 331237

A prova privada reaproveita uma imagem e frames da referência exclusivamente
para medir o erro relatado. Ela não demonstra uma nova pessoa, nova atuação ou
recriação independente. O recorte ilustrado extraído do frame 450, medido contra
o frame 400, resultou em escala `0.825643`, rotação `-9.384920°`, RMSE `8.542418 px`
e erro máximo `10.723861 px` sob os controles MediaPipe disponíveis. Os pontos
são estimativas do detector, não ground truth anatômico. A diferença entre
olhos desenhados e olhos humanos exige inspeção da silhueta.

Os controles do frame 64 pedem escala `0.757866`; o frame 128 pede `0.624332`.
Os frames 0 e 312 excedem o limite padrão de RMSE e permanecem bloqueados.
Esses valores demonstram por que não se impõe uma redução constante à tomada.
Um contato marcado mostra pontos e cobertura, sem alegar playback contínuo ou
aprovação do usuário. Fotos, vídeos e tracking permanecem fora do Git.

Nos trechos de revelação total do MP4 achatado, o detector passa a observar a
ilustração. Esses controles não medem a pessoa oculta. O frame 450 serve como
fonte ilustrada neste diagnóstico; o frame 400 ainda mostra a pessoa alvo.
O tracking contínuo da pessoa deve vir do vídeo base completo, antes de inserir
o portal. Não tratar a troca de conteúdo detectado como tracking do mesmo corpo.

Para gerar com outra pessoa, é necessário um vídeo base novo desde o início,
com os gestos planejados, e controles/máscaras obtidos desse próprio vídeo.
O módulo não substitui essa etapa por uma fotografia animada nem comprova
identidade diferente por meio de hashes distintos.

## Verificação

```bash
python -m unittest discover -s tests -p 'test_subject_alignment.py' -v
python -m unittest discover -s tests -p 'test_planar_portal_alignment.py' -v
```

Os testes cobrem medição de escala/rotação, mapeamento crop/raster, pivô,
proporção, transparência, confiança desconhecida, revisão manual, perda de
controles, lacunas temporais, vínculos e rejeição de anatomia incompatível.
São verificações técnicas; a conferência visual e a confirmação do usuário
precisam de registros próprios na revisão da montagem.
