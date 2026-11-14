# Política de edição e rastreabilidade

A CLI roda localmente com Python 3.11+ e biblioteca padrão.

```sh
python extensions/editor_policy.py rank extensions/fixtures/catalog.json extensions/fixtures/need.json extensions/fixtures/scope.json
python extensions/editor_policy.py validate-plan extensions/fixtures/plan.json --catalog extensions/fixtures/catalog.json --scope extensions/fixtures/scope.json
python extensions/editor_policy.py manifest extensions/fixtures/plan.json --file necessidade=extensions/fixtures/need.json
python -m unittest discover -s extensions -p 'test_*.py' -v
```

Os exemplos são sintéticos. O escopo usa o ID da raiz autorizada. O indexador de mídia deve percorrer as raízes fornecidas e registrar a raiz real de cada arquivo. Um atalho para mídia externa exige verificação do destino. A aprovação de direitos é registrada no catálogo, com a origem documental controlada pelo projeto.

O catálogo inclui `id`, `source`, `root_id`, `family`, `license_status`, `uses`, `engines`, `mime_type`, `alpha`, `tags`, `intensity` e `duration_ms`. A necessidade explicita famílias, destinos, duração e outros requisitos. O ranking ordena só os recursos elegíveis por semântica e intensidade. Motivos de exclusão e pesos são auditáveis. Faça uma prévia com o corte limpo e com o candidato para decidir aplicação.

A timeline usa intervalos de fim exclusivo. Cada segmento registra quadros da origem, quadros da sequência, taxa racional e limites do bruto. Use `read` se o efeito consultar quadros além do recorte. O gatilho de áudio usa amostras da sequência, depois das posições de áudio e de qualquer conversão de taxa. O cálculo de SFX considera o ataque interno do arquivo e a posição de trim. `manifest` grava SHA-256 da timeline normalizada e dos arquivos selecionados por papel.

O código valida os dados fornecidos. A verificação de acesso ao Drive, geração de candidatos, licença documental, análise multimodal da montagem e decodificação do render dependem dos demais estágios.

Para uma prévia privada explicitamente autorizada, use `"use":"private_preview"` no pedido e na timeline e `"allow_unverified_private_preview":true` no escopo. Um arquivo com `"license_status":"unknown"` só passa nessa modalidade se a origem estiver no escopo de leitura, o arquivo direto estiver verificado e `"can_download":true` vier do indexador. O resultado registra a restrição. A exceção não vale para publicação, uso comercial ou outros destinos.
