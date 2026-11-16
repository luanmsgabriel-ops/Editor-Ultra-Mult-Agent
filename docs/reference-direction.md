# Dossiê de referência, adaptação e direção multimodal

Esta conexão transforma observações atribuídas de uma referência em dois contextos utilizáveis: um perfil para a direção editorial e um contexto para a autoria de novos clipes. O pedido de geração também pode levar imagens reais a um endpoint multimodal configurado e receber um plano `video-generation-plan/1` validado.

O endpoint é um **diretor de texto/imagens**. Esta chamada não gera o vídeo, não produz imagens, não faz face swap, não executa templates e não aprova a qualidade perceptiva. A produção dos clipes continua usando os prompts, configurações e anexos exportados pelo [fluxo de geração](video-generation.md).

## 1. Observações antes das decisões

`editorial_engine.reference_direction.build_dossier` recebe uma análise existente e observações explicitamente escritas por uma pessoa ou modelo. Não há inferência semântica a partir de nomes, palavras-chave ou contagem de efeitos.

Cada observação informa:

- `id`, `aspect` e `description`: o aspecto realmente observado e seu conteúdo.
- `source_id`, `source_sha256`, `clock: "source"` e `interval`: a fonte exata e o trecho.
- `evidence_ids`: evidências existentes da mesma fonte, com interseção temporal.
- `scope`: `sampled_frames`, `continuous_video`, `audio_listened`, `transcript` ou `human_note`.
- `provenance`: autor, tipo e método efetivamente usado.
- `confidence`: confiança atribuída entre zero e um; não é uma medição automática.

Os aspectos aceitos são narrativa, composição, câmera, ritmo, transição, identidade, roupa, local, objeto, iluminação, cor, tipografia, movimento, áudio e voz, com os identificadores em inglês expostos por `ASPECTS`. Observação visual exige evidência visual; transcrição não estabelece áudio ouvido. Hash, intervalo e escopo são verificados; a veracidade da interpretação depende do revisor.

Exemplo de estrutura de observação, preenchendo o hash com o arquivo real:

```json
{
  "id": "camera-static",
  "aspect": "camera",
  "description": "Enquadramento frontal, com o sujeito no terço esquerdo da amostra.",
  "source_id": "source",
  "source_sha256": "HASH_REAL_DA_FONTE",
  "clock": "source",
  "interval": {"start_s": 0, "end_s": 1},
  "evidence_ids": ["frame:0"],
  "scope": "sampled_frames",
  "provenance": {
    "kind": "human",
    "actor": "Diretor do projeto",
    "method": "Inspeção do quadro identificado; movimento contínuo não conferido"
  },
  "confidence": 0.8
}
```

Nesse exemplo, a descrição se limita à posição e ao enquadramento observados. A amostra isolada não comprova ausência de movimento durante um segundo inteiro. A validação não resolve essa distinção semântica pelo autor; para afirmar movimento contínuo, registre a revisão real correspondente e seu escopo.

```python
from editorial_engine.reference_direction import build_dossier

dossier = build_dossier(
    analysis,
    observations,
    dossier_id="reference-main",
    author={"kind": "human", "actor": "Diretor do projeto", "method": "Decupagem atribuída"},
)
```

O dossiê guarda a análise completa, as observações, o hash da análise e seu próprio `dossier_sha256`. `validate_dossier` revalida as fontes e os artifacts de imagem/transcrição. Alterar um arquivo, observação ou análise invalida o vínculo. O estado permanece `automatic_perception=false` e `user_approval=unverified`.

## 2. Contrato de manter e substituir

`reference-adaptation/1` exige uma decisão para **cada observação**. Ausência de decisão não significa conservar automaticamente. O contrato aponta para a versão exata do dossiê e identifica sua autoria.

```json
{
  "schema": "reference-adaptation/1",
  "id": "adaptation-main",
  "revision": 1,
  "dossier_sha256": "HASH_REAL_DO_DOSSIE",
  "author": {"kind": "human", "actor": "Diretor do projeto", "method": "Decisões do briefing"},
  "replacement_references": [],
  "decisions": [
    {
      "observation_id": "camera-static",
      "action": "keep",
      "rationale": "Preservar a composição observada."
    }
  ]
}
```

`replace` exige `target` textual, por exemplo uma nova pessoa, local, roupa ou função da cena. Pode declarar `reference_ids` apontando para `replacement_references`, com `id`, `kind`, `role`, caminho absoluto e SHA-256 reais. Referências de substituição ainda inexistentes não recebem caminho fictício: descreva o alvo e deixe a direção criar uma necessidade de asset no plano.

`keep` não aceita um `target` que altere silenciosamente a observação. IDs repetidos, decisões ausentes, referências desconhecidas, arquivos alterados e dossiê obsoleto são rejeitados. `validate_adaptation` devolve o contrato normalizado com `adaptation_sha256`; não decide se a alteração respeita a intenção do usuário.

## 3. Projeções para os dois fluxos

```python
from editorial_engine.reference_direction import (
    to_contextual_profile,
    generation_context,
)

reference_profile = to_contextual_profile(dossier, adaptation)
context = generation_context(dossier, adaptation)
```

`to_contextual_profile` produz `reference-contextual-profile/1`, com observações atribuídas e listas explícitas de manter/substituir. Pode ser fornecido como `reference_profile` a `editorial_engine.directions.build_request`. O perfil não cria IDs de efeitos, capacidades de runtime, tracking, máscaras ou assets renderizados.

`generation_context` produz `reference-generation-context/1`. Ele cria IDs portáveis para fontes e observações, preservando caminho, hash, intervalo, escopo e autoria, e transporta as decisões de adaptação. As fontes provenientes da análise editorial são tratadas como vídeo quando a análise não declara outro `kind`, conforme a entrada audiovisual de `prepare_analysis`. Uma referência de substituição conserva seu tipo explícito.

Os textos dos alvos ajudam a dirigir a nova bible, cenas e recursos. Não há verificador semântico que prove, pelo JSON, que uma roupa, personagem ou movimento produzido será fiel. A avaliação continua vinculada ao resultado real.

## 4. Imagens verificadas no pedido de geração

`generation.direction.build_request` aceita novos argumentos opcionais:

```python
from editorial_engine.generation.direction import build_request

request = build_request(
    answers,
    analysis=analysis,
    assets=assets,
    reference_dossier=dossier,
    adaptation=adaptation,
    include_images=True,
    max_frames=24,
    max_image_bytes=4 * 1024 * 1024,
    max_request_bytes=20 * 1024 * 1024,
    template_library=private_library,
    template_root=private_root,
    template_ids=explicit_shortlist,
)
```

`include_images=False` permanece o default da API por compatibilidade. Chamadores que desejam direção multimodal devem ativá-lo explicitamente. Se houver dossiê, seu contrato de adaptação também é obrigatório. Uma análise adicional deve ser idêntica à análise vinculada pelo dossiê.

O pedido inclui bytes reais de amostras visuais da análise, imagens ready do inventário e referências de imagem adicionais. O tipo MIME vem da imagem decodificada, não da extensão: PNG, JPEG e WebP estáticos são aceitos. Texto de referência e identificação dos arquivos permanecem dados de estudo.

`max_frames` limita o total de imagens fornecidas, incluindo assets, até 96. Se a quantidade ultrapassa o orçamento, uma amostragem uniforme determinística seleciona imagens; todos os IDs omitidos ficam em `review_scope.omitted_image_ids`. O caso de uma imagem escolhe a primeira. Nenhuma amostragem é apresentada como seleção semântica dos quadros mais relevantes. O host deve ajustar o inventário e o orçamento quando um momento decisivo precisa ser incluído.

Cada imagem pode ter até 4 MiB e o corpo preparado até 20 MiB. Imagem ou contexto acima do limite bloqueia o pedido, sem truncar instruções ou redimensionar silenciosamente. `image_manifest` enumera bytes, MIME, dimensões, fonte e intervalo. `file_manifest` registra todos os arquivos de entrada autorizados e seus hashes. Preparar isso continua com `model_inference_executed=false`, sem alegar que um modelo viu as imagens, ouviu áudio ou assistiu a movimento contínuo.

## 5. Templates como contexto de autoria

`template_library`, `template_root` e `template_ids` usam o mesmo `templates.library_request` do fluxo editorial. O catálogo privado é verificado antes de fornecer suas fichas. Sem shortlist, usa o resumo do catálogo; com IDs explícitos, inclui os candidatos correspondentes.

Função editorial, composição, parâmetros, requisitos e limites entram na direção. Os arquivos de código do template não são anexados como imagens ou promovidos a recursos ready. A instância, o render e a importação de uma camada `motion-layer/1` continuam etapas separadas. Nenhum template privado precisa entrar no Git para usar essa conexão.

## 6. Chamada configurável para o schema correto

```python
from editorial_engine.generation.provider import call_provider

plan = call_provider(
    request,
    endpoint="https://SEU-ENDPOINT/v1/chat/completions",
    model="MODELO_CONFIGURADO",
    api_key_env="CLONE_DIRECTION_API_KEY",
    timeout_s=45,
)
```

Esta chamada deve ocorrer somente quando o endpoint e envio de contexto estiverem configurados para o projeto. O endpoint precisa usar HTTPS, ou HTTP local. Credencial fica apenas no header de transporte; não entra no plano/recibo. Redirecionamentos não são seguidos para outro destino. Não há retry automático ou fallback por palavras-chave.

O retorno é o **plano na raiz**, `schema=video-generation-plan/1`, acrescido de `provider_receipt`. Pode ser validado e exportado pelas funções existentes. Não é um envelope `{plan: ...}`.

Antes de enviar, a função confere hash do pedido, escopo, limites, bytes de todos os arquivos e igualdade dos bytes incorporados com as imagens locais. O briefing precisa estar pronto para direção. Depois da resposta, os arquivos são conferidos novamente. A resposta deve conter um único objeto JSON de plano e não pode solicitar execução de ferramentas.

A validação também exige:

- Preservar os campos de briefing resolvidos, quantidade/duração dos clipes quando explícitas e `dialogue_text` literal quando fornecido. Para esse campo único, a comparação concatena as falas em ordem com um espaço; outra segmentação precisa de autoria explícita.
- Usar apenas arquivos ready e referências presentes no manifesto de entrada, sem inventar caminhos/hashes/tipos.
- Conservar observações atribuídas, fontes, escopos e intervalos quando reutilizadas por seus IDs.
- Vincular novas observações a imagens efetivamente incluídas da fonte e do intervalo correspondente. Novas observações do modelo só podem declarar `sampled_frames`; não podem alegar áudio ouvido ou vídeo contínuo que não foi enviado.
- Passar pelo `validate_plan(..., verify_files=True)`, incluindo a conta de duração e os contratos bilaterais das emendas.

As restrições explícitas de quantidade, duração gerada e fala literal também estão disponíveis em `generation.provider.validate_editorial_inputs(plan, editorial_inputs)`. A importação manual de planos pode aplicar essa mesma função após `validate_plan`, usando as respostas resolvidas do projeto. Ela não modifica o plano, não lê arquivos e retorna o próprio objeto; campos ausentes não criam limites implícitos. A função não avalia semanticamente estilo, atuação ou a fidelidade da adaptação.

O recibo registra hashes do pedido, resposta, plano, referências, catálogo e manifesto, além da modalidade de transporte e IDs das imagens fornecidas. `provider_input_use`, qualidade perceptiva e aprovação do usuário permanecem não comprovados. Uma resposta válida demonstra recebimento de um plano pelo transporte; não prova que o fornecedor interpretou corretamente as imagens.

O adaptador contextual `editorial_engine.directions.call_provider` conserva seu schema e sua implementação. O novo módulo atende especificamente `video-generation-director-request/1`.

## 7. Testes e limites da entrega

O argumento `transport` permite testar a chamada sem rede: a função recebe `endpoint`, `body`, `headers`, `timeout_s` e `max_response_bytes` como argumentos nomeados e devolve o JSON compatível. Qualquer transporte injetado é registrado como `injected_simulation`, com `model_inference_executed=false`. Uma simulação nunca é apresentada como uso de modelo real.

Os testes `test_reference_direction.py` e `test_generation_provider.py` usam arquivos e observações sintéticas. Exercitam substituição explícita, ausência de decisões, evidência estrangeira, arquivos alterados, escopo de áudio/imagens, manutenção de briefing, caminhos inventados, limites, contexto de templates e o envio de bytes de uma pequena imagem real ao transporte simulado. O teste não observa um vídeo do usuário nem utiliza créditos.

Não foram instalados modelos, chamados provedores reais ou copiados materiais proprietários. A autorização de uma rota de produção não substitui a disponibilidade do gerador escolhido. As etapas seguintes continuam sendo produção/revisão de assets, exportação, geração externa de clipes, ingestão e montagem conforme os contratos correspondentes.
