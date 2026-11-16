# Direção de planos: duração, ambientes e composição

O módulo editorial_engine.generation.shot_design transforma uma direção
autorada em decisões verificáveis de duração e composição. Os tempos vêm dos
intervalos de ações e voz fornecidos pelo autor. O módulo não atribui dois
segundos por ação, não interpreta emoção por palavras-chave e não escolhe
câmera a partir de adjetivos.

O resultado é planejamento. A duração efetiva dos vídeos devolvidos pertence
ao importador de geração; performance, enquadramento, continuidade e som
precisam de revisão no arquivo.

## API

    from editorial_engine.generation.shot_design import (
        validate_design, plan_shots, shot_prompt, validate_generation_mapping,
    )

    design = validate_design(authored_design)
    planned = plan_shots(design, profile=capabilities, verify_files=False)
    binding = validate_generation_mapping(
        planned,
        directed_generation_plan,
        {"clip-arrival": "arrival", "clip-walk": "walk", "clip-reveal": "reveal"},
    )

- Entrada: video-shot-design/1.
- Resultado: video-shot-design-plan/1, selado com plan_sha256.
- Vínculo: video-shot-generation-binding/1.
- Status planned: decisões autoradas e aritmética passaram. Isso não atesta
  que uma ferramenta aceitou ou executou a geração.
- Status blocked: issues indicam o impedimento; questions registram decisões
  ainda ausentes. Dados malformados, hashes alterados e intervalos inválidos
  geram ValidationError.
- Nenhuma das funções chama providers ou altera arquivos.

O profile reutiliza video-generation-capabilities/1: ferramenta, modelo, modo,
interface, fonte e data de verificação declarados. O planner não consulta o
provider nem atesta que a declaração continua atual.

## Relógios e duração

Cada shot representa uma tomada autorada. A ligação desta API com geração é
um clipe por plano. Outras rotas do projeto atendem arranjos mais complexos.

| Campo | Significado |
|---|---|
| actions[].start_s/end_s | Intervalo da ação no relógio do conteúdo mantido |
| voice[].start_s/end_s | Janela de fala no mesmo relógio |
| use_duration_s | Duração útil explicitamente escolhida pelo autor |
| handles.in_s/out_s | Margens antes/depois da faixa útil, inclusive zero |
| duration_candidates_s | Durações discretas autoradas ou recebidas do profile |
| generated_duration_s | Opcional: escolha explícita entre as candidatas |
| excess_policy: tail_handle | Atribuição explícita do excedente à margem final |
| joins[].overlap_s | Sobreposição descontada da duração final |

Ações simultâneas são permitidas. Sua cobertura temporal não é a soma de
durações que acontecem ao mesmo tempo. Uma lacuna visual exige uma ação ou
pausa descrita; o planner não a preenche congelando um quadro.

A duração mínima de geração é a margem inicial mais a duração útil mais a
margem final. Sem escolha explícita, seleciona-se a menor candidata que
comporta esse intervalo. A lista 4/6/8/10 é um exemplo, não uma capacidade
universal. Sem candidatas e sem profile com durações discretas, o módulo
pergunta pelas opções. Um profile com apenas mínimo/máximo precisa de
candidatas explícitas; não se inventam incrementos.

Exemplo: conteúdo de 4 s, margem inicial de 0,5 s e final de 0,25 s exigem
4,75 s de geração. Entre 4/6/8/10, selecionam-se 6 s, usando [0,5; 4,5).
Os 1,25 s excedentes precisam de atribuição explícita. Com tail_handle, a
margem final efetiva será 1,5 s. Sua direção também precisa existir, como
continuar respirando e manter o objeto aberto. É performance adicional,
sem repetição de frames.

Se nenhuma candidata comporta o plano, o resultado pede revisão, divisão
ou outra capacidade. Não acelera fala nem reduz ações para caber.

## Vários ambientes

Cada plano declara location_ids. Ambientes sucessivos normalmente recebem
planos próprios e uma entrada em joins, mesmo em corte seco com sobreposição
zero. Mais de um ambiente na mesma tomada exige passagem contínua autorada:

    {
        "environment_transition": {
            "mode": "continuous",
            "start_s": 1,
            "end_s": 3,
            "description": "A pessoa sai do café pela porta e chega à rua sem corte.",
            "camera_path": "A câmera acompanha por trás, mantendo a distância."
        }
    }

Esse objeto registra a decisão do diretor. A viabilidade da passagem no
gerador e sua execução no vídeo continuam pendentes de verificação.

## Composição 9:16 e 16:9

Cada proporção solicitada exige composição própria. Uma versão não é
obtida cortando a outra automaticamente. Cada composição contém:

- framing: plano e enquadramento.
- rationale: função desse enquadramento na ação.
- subject_zone: área planejada para a pessoa ou objeto.
- gesture_zone: área necessária para mãos, gestos e objetos em movimento.

As zonas usam [left, top, right, bottom], normalizado entre zero e um,
com origem no canto superior esquerdo. São direções, não detecções. Não
existem pixels universais, tamanho obrigatório de rosto ou posição fixa.

camera.purpose explica a função da câmera; camera.movement descreve o
movimento, inclusive câmera fixa. Luz, sujeito e atuação são campos próprios.
Faltar um deles gera pergunta, sem emoção ou câmera inventada.

## Exemplo completo: três ambientes, 4 + 6 + 8 segundos

Este exemplo cria duas composições por plano. Tempos e zonas são decisões
demonstrativas, sem se tornarem padrões automáticos.

    from editorial_engine.generation.shot_design import plan_shots

    design = {
        "schema": "video-shot-design/1",
        "id": "three-environments",
        "revision": 1,
        "author": {
            "kind": "human",
            "actor": "Diretor do exemplo",
            "method": "Ações e intervalos explicitamente autorados"
        },
        "aspect_ratios": ["9:16", "16:9"],
        "duration_candidates_s": [4, 6, 8, 10],
        "target_duration_s": 18,
        "locations": [
            {"id": "cafe", "description": "Café com janela lateral."},
            {"id": "street", "description": "Rua tranquila diante do café."},
            {"id": "studio", "description": "Estúdio com fundo azul contínuo."}
        ],
        "shots": [],
        "joins": [
            {"id": "outside", "from": "arrival", "to": "walk",
             "kind": "cut", "execution": "post", "overlap_s": 0,
             "rationale": "Levar a apresentação para a rua."},
            {"id": "reveal-cut", "from": "walk", "to": "reveal",
             "kind": "cut", "execution": "post", "overlap_s": 0,
             "rationale": "Passar à demonstração no estúdio."}
        ]
    }

    authored_shots = [
        ("arrival", "cafe", 4, [
            (0, 1.2, "Ergue o caderno fechado."),
            (1.2, 4, "Abre o caderno e o apresenta com os dedos visíveis.")
        ]),
        ("walk", "street", 6, [
            (0, 3, "Caminha dois passos com o caderno junto ao corpo."),
            (3, 6, "Para, volta o olhar à câmera e mostra a capa.")
        ]),
        ("reveal", "studio", 8, [
            (0, 4, "Abre as mãos para revelar o desenho no caderno."),
            (4, 8, "Sustenta a revelação com respiração natural.")
        ])
    ]

    for shot_id, location_id, duration, actions in authored_shots:
        design["shots"].append({
            "id": shot_id,
            "purpose": "Apresentar a ação definida neste ambiente.",
            "subject": "A nova pessoa com identidade e figurino próprios.",
            "performance": "Executar os gestos descritos sem ocultar o objeto.",
            "lighting": "Luz suave coerente com o ambiente.",
            "camera": {
                "purpose": "Tornar mãos, objeto e expressão legíveis.",
                "movement": "Câmera fixa; a ação acontece dentro do quadro."
            },
            "location_ids": [location_id],
            "use_duration_s": duration,
            "handles": {"in_s": 0, "out_s": 0},
            "actions": [
                {"id": "action-" + str(index), "start_s": start,
                 "end_s": end, "description": description}
                for index, (start, end, description) in enumerate(actions)
            ],
            "compositions": {
                "9:16": {
                    "framing": "Plano médio com ambas as mãos no quadro vertical.",
                    "rationale": "Preservar o gesto de abertura do caderno.",
                    "subject_zone": [0.2, 0.12, 0.8, 0.9],
                    "gesture_zone": [0.1, 0.3, 0.9, 0.8]
                },
                "16:9": {
                    "framing": "Plano aberto com o ambiente visível à direita.",
                    "rationale": "Mostrar contexto mantendo leitura das mãos.",
                    "subject_zone": [0.12, 0.1, 0.55, 0.95],
                    "gesture_zone": [0.1, 0.2, 0.65, 0.9]
                }
            }
        })

    planned = plan_shots(design)
    assert planned["status"] == "planned"
    assert planned["timing"]["final_duration_s"] == 18
    assert [s["generated_duration_s"] for s in planned["shots"]] == [4, 6, 8]
    vertical_prompt = planned["shots"][0]["prompts"]["9:16"]
    horizontal_prompt = planned["shots"][0]["prompts"]["16:9"]

Para duas transições de 0,5 s, a duração final será 17 s:

    design["revision"] = 2
    design["target_duration_s"] = 17
    for join in design["joins"]:
        join.update(kind="dissolve", overlap_s=0.5)
    planned = plan_shots(design)
    assert planned["timing"]["generated_duration_s"] == 18
    assert planned["timing"]["overlap_duration_s"] == 1
    assert planned["timing"]["final_duration_s"] == 17

A transição está planejada para pós. Este resultado não a renderiza.
Sobreposições que consomem um plano ou colidem no plano intermediário
são bloqueadas.

## Voz: estimativa e medição

voice é uma lista opcional de falas literais com janela e proveniência:

    {
        "id": "line-1",
        "text": "A fala precisa permanecer exatamente assim.",
        "start_s": 0.5,
        "end_s": 3.5,
        "timing_basis": "estimated",
        "provenance": {
            "kind": "human",
            "actor": "Diretor",
            "method": "Estimativa de leitura; áudio ainda não produzido"
        }
    }

O planner preserva texto e declaração estimated. Não estima por contagem
de palavras nem transforma estimativa em medição.

Para timing_basis measured, source precisa conter caminho absoluto, SHA-256
e start_s/end_s do trecho de áudio. A duração desse trecho deve ser igual à
janela, pois não há retime implícito. verify_files=True confere bytes e
cobertura pela duração real do áudio. Sem essa opção, a medição permanece
declaração atribuída ainda não verificada.

A checagem não transcreve, não atesta correspondência da frase ao áudio,
não confirma escuta e não resolve sincronismo labial. Janela que ultrapassa
a faixa útil bloqueia o plano, sem cortar fala.

## Ligação com geração

validate_generation_mapping recebe um mapa explícito clip_id -> shot_id,
com cobertura completa e na ordem autorada. Confere schema, hash,
recomputação do design, ausência de bloqueios, duração, faixa útil,
proporção autorada e sobreposições em todos os pares consecutivos.

O validador completo video-generation-plan/1 continua responsável pelo
restante do contrato. A função de vínculo não o chama novamente e pode
ser invocada por ele sem recursão. Seu recibo mantém semantic_prompt_review
como pending: igualdade de duração não demonstra que a prosa preservou
gesto, figurino, ambiente ou intenção.

O host deve levar design, prompts por formato, câmera, composições e joins
ao diretor. Os blocos preservam a prosa fornecida e usam rótulos neutros,
sem tradução. Duração e anexos ainda precisam ser configurados nos campos
reais da ferramenta.

Depois de validar o vínculo, o exportador pode obter o bloco visual original:

    visual_prompt = shot_prompt(
        planned, "arrival", "9:16", include_voice=False
    )

O helper usa os campos autorados de ação, intervalos, câmera, enquadramento,
zonas, atuação, luz e emendas, sem depender de uma paráfrase resumida pelo
diretor. include_voice=False omite as falas estruturadas. O exportador pode
então inserir o diálogo do contrato de geração uma única vez, ou encaminhar
esse diálogo somente à pós quando essa for a rota de áudio.

O helper não remove palavras de prosa visual nem deduz se uma descrição
solicita fala por engano. Ele não chama o validador completo de geração,
evitando recursão na exportação; o vínculo deve ser validado antes.

No projeto persistente, vincule o hash do design à requisição, ao plano e
aos exports para invalidar dependências quando houver revisão. Não
transfira aprovação do design para vídeos devolvidos.

## Verificação focada

    python -m pytest tests/test_shot_design.py -q

A suíte cobre 4/6/8 s entre candidatas 4/6/8/10, 18 s com cortes e 17 s com
sobreposições, margens, excedentes, direção ausente, vários ambientes,
composição por proporção, ações simultâneas e lacunas, voz estimada/medida,
capacidades declaradas e adulteração do vínculo.
