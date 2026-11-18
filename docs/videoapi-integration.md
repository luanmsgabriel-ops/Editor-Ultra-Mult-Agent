# VIDEOAPI no Editor Ultra

Integração opcional de geração de MP4 e PNG no Studio, **sem alterar** o fluxo `prompt_export_only` do núcleo editorial. Gerar é uma ação humana explícita, separada de importar, revisar, renderizar, aprovar e publicar.

Documentação do provedor: https://videoapi-wheat.vercel.app/llms.txt

## Configuração

Defina **somente no ambiente do back-end**, por exemplo nas variáveis secretas do serviço Railway:

```text
VIDEOAPI_KEY=(valor secreto configurado no ambiente)
```

Não coloque a chave no repositório, HTML, JavaScript, frontend, URL, logs ou payload de ferramentas. O Studio exibe somente se a integração está configurada. A conta pode ser consultada por `editor_videoapi_account`, que devolve somente saldo e preços de vídeo/imagem (não inclui `api_key_masked`).

## Operação

1. Abra ou salve um projeto e avance para **Seu vídeo → Geração por IA → VIDEOAPI**.
2. Escolha **vídeo** ou **imagem**, formato `9:16` ou `16:9`, e escreva um prompt de até 5.000 caracteres.
3. Para vídeo, escolha exatamente `5`, `10`, `20` ou `30` segundos. Imagem não recebe duração.
4. Opcionalmente escolha até 3 imagens PNG, JPEG ou WebP **já enviadas e verificadas no projeto**. O back-end resolve os IDs dos arquivos e codifica base64 puro; nenhum base64 ou segredo é exposto ao navegador. Corpo total limitado a 4,5 MB (pode inviabilizar três imagens grandes).
5. Consulte os créditos e autorize o consumo; clique **Gerar**. Esse clique chama `editor_videoapi_generate` no servidor. O servidor envia `POST /v1/videos` ou `POST /v1/images` com `Authorization: Bearer VIDEOAPI_KEY`, valida HTTP `202` e salva o ID.
6. Um worker persistente consulta `GET /v1/videos/{id}` ou `GET /v1/images/{id}` **a cada 5 s**, inclusive se o painel for fechado. O Studio recebe os estados no snapshot do projeto e pode exibir o player ou PNG e o link para baixar.
7. Em `done`, use a prévia e `download_url` do provedor. Esses links expiram em cerca de 24 h, portanto salve o MP4 ou PNG; não há importação automática no motor.
8. Em `failed`, exiba a descrição do erro; o provedor devolve os créditos automaticamente. Em `timeout` (15 min), o processamento pode continuar remotamente: **não afirme que houve reembolso**, e confira o histórico no provedor antes de reenviar.

## Segurança, limites e erros

- 401: chave ausente/inválida/bloqueada; corrigir a variável do serviço.
- 402: saldo insuficiente; crédito não reservado na solicitação recusada.
- 413: base64/JSON acima do limite do host; reduzir referências.
- 429: fila cheia (8 pendentes por chave); aguardar antes de novo envio; no polling, aguardar e reconsultar.
- 5xx no `GET`: reconectar com espera exponencial, sem repetir `POST`.
- 5xx, timeout de rede ou resposta inválida ao `POST`: marcar `submission_uncertain`. **Não repetir automaticamente**: a VIDEOAPI pode ter aceitado e debitado a geração sem que o ID tenha chegado ao Editor Ultra.
- `request_id` fornece idempotência local e persistência em SQLite. Reiniciar o servidor não duplica `POST` nem descarta IDs aceitos; estados de envio ainda não confirmado ficam incertos.
- `poll_error` denota falha persistente/autorização na consulta; não é o mesmo que `failed` do provedor. `poll_retry` usa espera progressiva respeitando os 5 segundos mínimos entre consultas.
- Todos os links de retorno são limitados à origem oficial da VIDEOAPI. Os arquivos gerados **não** se tornam automaticamente fontes, versões aprovadas ou renders validados.

## Verificação sem consumir créditos

```sh
python -m pytest -q tests/test_videoapi.py tests/test_app_server.py
```

Os testes usam transporte simulado e cobrem header bearer, JSON/202, 401/402/413/429/503, bloqueio de formatos, idempotência, vídeo/imagem, polling, timeout, falha, resposta incerta, retomada e backoff. São testes de integração local/contrato e **não provam geração paga ao vivo**. A prova ao vivo depende de uma chave real e de uma geração explicitamente autorizada.
