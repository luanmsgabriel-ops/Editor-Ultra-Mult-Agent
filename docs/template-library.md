# Biblioteca privada de templates

O módulo `editorial_engine.templates` torna um acervo privado consultável e prepara
variantes com parâmetros explícitos. Um template é uma opção de autoria. A camada
de motion que o compositor aceita continua sendo um resultado efetivamente
renderizado e verificado pelo contrato `motion-layer/1`.

O módulo lê JSON, confere arquivos, copia um pacote completo e aplica bindings
de dados. Não importa o código dos pacotes, não executa seus comandos, não abre
um navegador e não seleciona estilos por palavras-chave. Originais, fontes,
assets, código privado, índices e variantes permanecem fora do Git.

## Comandos

```sh
python -m editorial_engine templates verify /acervo/biblioteca.json
python -m editorial_engine templates list /acervo/biblioteca.json
python -m editorial_engine templates request /acervo/biblioteca.json --template-id titulo-autoral --output /projeto/opcoes.json
python -m editorial_engine templates instantiate /acervo/biblioteca.json titulo-autoral /projeto/variantes/v001 --params /projeto/parametros.json --inputs /projeto/arquivos.json
```

Também é possível usar `python -m editorial_engine.templates` com os mesmos
subcomandos. `--root` substitui a raiz padrão, que é o diretório do JSON da
biblioteca. Os caminhos internos continuam relativos a essa raiz/pacote.

`list` verifica o contrato e apresenta fichas resumidas sem conferir os arquivos. Sua
saída declara `files_verified: false`. `verify` confere inventários completos e
bindings contra os arquivos reais. `request` faz essa conferência e devolve um
contexto compacto para o diretor; `--template-id` é repetível e filtra IDs
explícitos. Não existe ranking automático por similaridade de nomes.

O resumo omite defaults e a descrição detalhada dos parâmetros, conserva hashes,
estado, requisitos, inputs ausentes, contagem de parâmetros e referências das
prévias. Exigências e limitações repetidas são preservadas uma vez em `shared_notes`;
cada ficha as referencia por `runtime.requirements_refs` e `limitations_refs`.
Resolva essas referências ao avaliar a ficha. As prévias mantêm caminho, tipo,
hash e escopo; suas descrições completas ficam na consulta detalhada. Antes de
preparar uma variante, obtenha os parâmetros e todas as instruções da ficha com
`request --template-id ID`. A opção
`request --summary` também permite conferir arquivos e produzir somente o resumo.

`instantiate` exige uma pasta nova. O resultado contém `project/`, com a cópia
derivada do pacote, e `instance.json`, com hashes, parâmetros, inputs e estado
`instantiated_not_rendered`. Os previews copiados continuam vinculados ao
original; não validam a variante cujo texto, cor ou mídia foi alterado.

## Contrato da biblioteca

O objeto superior usa `schema: "motion-template-library/1"` e exige os campos:

| Campo | Conteúdo |
| --- | --- |
| `id`, `version` | Identidade e versão da biblioteca. |
| `packages` | Pacotes compartilhados. Um mesmo runtime e conjunto de fontes pode atender vários templates. |
| `templates` | Descritores `motion-template/1`. Cada ID é único no índice corrente. |

Cada pacote possui `id`, `root`, `files` e `provenance`.

- `root`: diretório relativo à raiz da biblioteca, sem traversal ou symlinks.
- `files`: inventário completo com `{path, sha256, size}`; `path` é relativo à
  raiz do pacote. Arquivos ausentes, alterados ou não inventariados impedem a
  verificação e a instanciação.
- `provenance`: `{source_folder_ids, source_file_ids, notes}`. IDs e notas
  registram a origem; não conferem automaticamente direitos de redistribuição.

`visual_fidelity.reference_bundle.inventory(root, excludes=())` produz os
registros de arquivos usados por esse contrato. O catálogo deve ficar fora dos
diretórios de pacote inventariados, para não criar autorreferência de hashes.
O bundle de referência existente também pode ser preservado dentro do pacote.

## Descritor de template

Campos obrigatórios:

| Campo | Conteúdo |
| --- | --- |
| `schema` | `motion-template/1`. |
| `id`, `version`, `package_id` | Identidade do template e pacote de origem. |
| `title`, `description`, `functions` | Conteúdo e funções descritos por curadoria explícita. |
| `entrypoint` | Arquivo relativo e inventariado; não é executado por este módulo. |
| `runtime` | `{name, requirements}`: host e requisitos declarados. |
| `parameters` | Controles editáveis, com tipos e limites. |
| `bindings` | Alvos exatos dos parâmetros nos arquivos originais. |
| `inputs` | Slots explícitos de arquivos, inclusive os ainda ausentes. |
| `previews` | Arquivos inventariados com `{path, kind, description}`; `kind` aceita `video`, `image` ou `document`. |
| `limitations` | Restrições de execução, adaptação e evidência. |
| `state` | Estados curatoriais separados, descritos abaixo. |

Dois campos opcionais preservam informação útil sem torná-la executável:

- `output_contract: {kind, alpha}`. `kind` aceita `opaque_scene`, `footage_edit`,
  `overlay` ou `unknown`; `alpha` aceita `opaque`, `straight` ou `unknown`.
  Essa declaração sempre chega ao diretor com `output_contract_verified: false`.
- `editorial`: permite somente `use`, `rules`, `rhythm`, `motion`, `transitions`,
  `sound` e `conflicts`. Esses valores JSON são orientação de autoria, tratada
  como conteúdo. Campos de pontuação por termos, como `fit`, não fazem parte
  do contrato nem da escolha do diretor.

Campos desconhecidos são rejeitados. A execução de um pacote por seu host
original pode exigir requisitos que este schema apenas documenta; o módulo não
inventa compatibilidade nem adapta automaticamente um formato de projeto.

## Estados e expectativas

```json
{
  "catalogue": "catalogued",
  "adaptation": "required",
  "runtime": "not_executed",
  "preview": "provided",
  "user_approval": "pending"
}
```

`preview` é `provided` quando há arquivos de prévia declarados, e `none` caso
contrário. Isso registra disponibilidade de arquivos, sem declarar decodificação,
playback, áudio ouvido ou qualidade visual.

`adaptation` também aceita `reference_only`: uma prévia ou preset descritivo sem
projeto reutilizável pode ser descoberto, mas sua instanciação é bloqueada.
`runtime` permanece `not_executed`, e a catalogação não atribui aprovação.

Um template pendente pode ajudar o diretor a pedir a variante adequada. Ele não
entra como efeito `ready` no catálogo nativo. A prontidão para uma cena exige
assets reais, o relógio do bruto, cobertura integral, região livre, proteção e
eventuais mattes/tracking atuais.

## Parâmetros e bindings

Cada parâmetro possui `type`, `required` e `description`. Tipos disponíveis:
`string`, `number`, `integer`, `boolean` e `json`. `default`, `minimum`, `maximum`
e `enum` são opcionais; limites numéricos só se aplicam a números/inteiros.
Todo parâmetro precisa de ao menos um binding. Valores não declarados são
recusados. Parâmetros obrigatórios sem default aparecem em
`parameters_requiring_values` no pedido do diretor.

```json
{
  "parameters": {
    "titulo": {
      "type": "string",
      "required": true,
      "description": "Texto exato da primeira cena"
    }
  },
  "bindings": [
    {
      "parameter": "titulo",
      "file": "project.json",
      "mode": "json_pointer",
      "pointer": "/scenes/0/title"
    }
  ]
}
```

| Modo | Regra |
| --- | --- |
| `json_pointer` | Altera um alvo já existente em `.json`, com JSON Pointer e serialização JSON. Não cria caminhos nem permite bindings que sobrescrevam uns aos outros. |
| `html_text` | Usa `search` e `expected_count` para identificar o texto completo de um nó HTML fora de `script`/`style`; decodifica entidades para comparação e escapa o novo texto. Não modifica atributos nem conteúdo parcial de outro rótulo. |
| `text` | Substituição literal, com contagem explícita, apenas em `.txt`/`.md`. |
| `hex_color` | Substituição de tokens integrais `#RGB` ou `#RRGGBB`, em `.html`/`.htm`/`.css`; busca e valor precisam obedecer ao formato hexadecimal. Não aceita CSS arbitrário. |

Os três modos textuais exigem parâmetros do tipo `string`. Cada binding fornece
`parameter`, `file`, `mode`, `search` e `expected_count`. As substituições são
calculadas sobre a fonte original e aplicadas simultaneamente, sem procurar
novamente o texto inserido por outra substituição. Regiões sobrepostas são
recusadas. Espaços fazem parte do texto do nó; `<br>` e spans continuam como
estrutura do template.

## Inputs de arquivos

Um slot é `{path, kind, required, description}`. `kind` aceita `video`, `image`,
`audio`, `font` ou `file`. O caminho pode estar ausente no pacote: um projeto que
espera seu vídeo de entrada pode ser catalogado antes de receber esse bruto.
Esse requisito aparece em `missing_inputs` e bloqueia a instanciação enquanto
obrigatório e não atendido.

O JSON de `--inputs` associa nomes de slots a `{path, sha256}`. Aqui `path` é um
caminho local absoluto do arquivo fornecido; o arquivo copiado precisa coincidir
com o hash. A cópia ocupa o caminho relativo declarado no slot. Um input não
pode substituir o entry point, um arquivo alvo de bindings ou outro slot.

Os hashes comprovam os bytes usados. A instanciação não afirma que o formato do
vídeo, áudio, imagem, fonte ou cache foi validado pelo host. Arrays de mídia
declarados em projetos JSON também podem ser parâmetros `json` obrigatórios;
seus vínculos precisam de conferência na execução posterior.

## Integração com direção e composição

API Python:

```python
validate_library(data, root=library_root, verify_files=True)
library_request(library_path_or_dict, root=None, template_ids=None, verify_files=True, summary=False)
instantiate_template(library, template_id, output_dir,
                     root=None, params=None, inputs=None)
```

`library_request` conserva referências relativas e hashes, omite o inventário
completo dos pacotes e não expõe a raiz local calculada. O diretor recebe opções,
requisitos, parâmetros, prévias e limitações, e fundamenta sua escolha no brief,
na fala, no gesto, no enquadramento e nas evidências atuais. Descrições e código
contido nos pacotes são dados, não instruções para o host.

Depois da instanciação, executar uma rota compatível é uma ação explícita. Uma
receita suportada pode usar `motion.render_recipe`; uma sequência efetivamente
produzida por outro host pode usar `motion.export_contextual_asset` com
`executed_here=False`. Só arquivos reais em PNG RGBA straight, com FPS racional,
ordem e hashes completos, formam uma camada `motion-layer/1`.

O fluxo seguinte permanece o já existente:

```sh
python -m editorial_engine prepare /projeto/bruto.mp4 /projeto/analise-v002 --assets /projeto/render/inventory.json
python -m editorial_engine request /projeto/analise-v002/analysis.json /projeto/analise-v002/catalog.json --brief-file /projeto/brief.txt --output /projeto/request.json
```

O diretor propõe o uso do `motion_asset`; o plano e o compositor verificam os
bindings. `native.motion_behind` exige matte do sujeito atual. Uma sequência
vinculada a outro bruto não se torna portátil apenas porque os frames foram
copiados. Uma cena opaca ou edição de filmagem mantém essa natureza e não ganha
alpha por registro no catálogo.

Ver [integração de motion](motion-integration.md) e
[direção contextual](contextual-editing.md) para render e revisão vinculados
ao resultado. O índice de templates complementa essas camadas.

## Validação

`tests/test_template_library.py` usa apenas fixtures autorais. Verifica cópia
imutável, parâmetros JSON, texto HTML escapado, entidades, substituições
simultâneas, cores, bindings sobrepostos, arquivos/slots ausentes, hashes
alterados, traversal/symlinks, descoberta de referências sem projeto, ausência
de execução e separação entre catálogo, prévia e aprovação. Os testes não
contêm projetos, fontes ou mídia privada.
