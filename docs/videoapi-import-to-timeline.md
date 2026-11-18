# P0 | Importar resultados da VIDEOAPI para o Editor Ultra

## Objetivo

Depois da geração VIDEOAPI terminar, o Editor Ultra pode importar o MP4
**já gerado** como arquivo verdadeiro do projeto. O botão
`Importar MP4 para montagem` aparece em `Gerações do projeto` para
um trabalho de tipo vídeo e status `done`. Não faz novo POST e não usa
créditos de geração.

- Em edição de vídeo pronto, entra como `footage`.
- Em `mode=generate`, o usuário seleciona uma tomada e entra como `shot`,
  passando pelo mesmo caminho de admissão e associação de clipes que os uploads.
- Todos os arquivos são examinados com FFprobe pela rotina existente e
  recebidos com SHA-256. O recibo registra job ID, provider ID, destino e
  nome do host, sem URL assinada ou chave.
- O job de importação tem chave de idempotência persistente. Uma tentativa
  duplicada confere o arquivo existente e não refaz o download.
- A tela exibe quando um vídeo já foi importado. Isso NÃO confirma sua
  fidelidade estética nem implica autorização para publicar.

## Origem segura da mídia

A importação NUNCA aceita URL arbitrária do ChatGPT ou do navegador.
Busca o link do job existente, com escopo do projeto, no SQLite da VIDEOAPI.
Aceita somente HTTPS em domínio exato aprovado, hoje:
`videoapi-wheat.vercel.app` e `www.videoapi.com.br`.

Domínios adicionais de CDN, se realmente usados pelo provedor, devem ser
autorizados no **servidor** pela variável de ambiente
`EDITOR_ULTRA_VIDEOAPI_MEDIA_HOSTS`, com nomes exatos separados por
vírgula. Não aceita curingas, hosts de rede privada, DNS para IP privado,
redirecionamento para origem não aprovada ou HTTP.

A transferência utiliza IP público resolvido e fixado no socket com TLS
verificado pelo nome de host, sem proxies. O stream é limitado por bytes
e espaço livre; erros excluem o arquivo temporário. A rotina FFprobe
verifica o conteúdo antes do registro definitivo. Se o domínio ainda
não estiver autorizado, o usuário pode baixar e anexar o MP4 manualmente.

## Operação programática

Ferramenta MCP: `editor_import_videoapi_result`.

```json
{
  "project_id": "UUID",
  "videoapi_job_id": "UUID_DO_TRABALHO_CONCLUIDO",
  "expected_revision": 3,
  "request_id": "import-videoapi-clip-001",
  "shot_id": null
}
```

No modo `generate`, forneça o ID da tomada no campo `shot_id`.
No modo `ready`, omita-o ou use `null` para adicionar como footage.

O trabalho será enfileirado; acompanhe com `editor_get_project` e abra
o arquivo com `editor_get_asset`. Links de reprodução temporários não
são tratados como armazenamento durável; somente o MP4 validado no
projeto passa a ser fonte para as rotas existentes.

## Limites

Esta implementação não faz montagem automática e não cria pessoa nova.
Também não altera a política de aprovação, não inicia VIDEOAPI por conta
própria, não modifica o PR de motion anterior, nem executa merge/deploy.
Se o link do provedor estiver expirado, recupere-o com o comando de
GET já disponível, ou anexe o arquivo manualmente.

## Testes

```bash
python -m pytest -q tests/test_videoapi_import.py tests/test_videoapi.py tests/test_app_server.py
```

O teste de importação é sintético e usa um downloader injetado; não
envia POST real para a VIDEOAPI e não gasta créditos.
