# Editor Ultra dentro do ChatGPT

O pacote `editor_ultra_app` conecta a interface ao motor existente, por um servidor MCP autenticado. A interface não contém chaves, vídeos particulares ou o catálogo privado. Os botões chamam ferramentas do servidor, que mantém projetos, recibos de arquivos, revisões e trabalhos em disco persistente.

A direção criativa continua no ChatGPT: o motor prepara evidências e um contrato de direção; o host observa o material e fornece um plano explícito. O servidor executa esse plano nas operações implementadas. Um pedido preparado, uma demonstração do catálogo e um teste técnico não são uma clonagem aprovada.

## Fluxo conectado

1. `editor_open` abre o painel. `editor_save_project` registra as escolhas sem confiar em aprovações contidas no JSON do navegador.
2. Na home, **Começar projeto** cria o projeto e envia os arquivos selecionados. Nas etapas do fluxo, escolher um novo arquivo inicia seu envio automaticamente. O painel obtém uma autorização curta pelo comando de envio de `editor_save_project` e envia o arquivo diretamente ao motor. Esse comando só emite a autorização; não salva escolhas. Anexos que já vieram pelo chat continuam usando `editor_import_file` e seus file params. A importação confere o tipo real de mídia, a duração e os bytes. Uma URL `blob:` ou o nome de um arquivo não contam como transferência.
3. `editor_prepare` registra um trabalho persistente. A preparação chama `editorial_engine.project`, produz análise real quando a rota permite e devolve as pendências e o pedido de direção.
4. O host usa `editor_get_asset` para inspecionar evidências e `editor_apply_direction` para entregar a direção no contrato solicitado. IDs `asset:<id>` substituem caminhos arbitrários.
5. `editor_render` executa o plano atual. `editor_get_project` e `editor_get_result` retornam o resultado real com links temporários de prévia.
6. `editor_record_review` recebe uma decisão explícita sobre o arquivo atual. Alterar referência, direção, material ou resultado invalida os vínculos pertinentes. Uma revisão técnica não preenche a confirmação do usuário.

Para referência com pessoa nova, os pixels da referência não podem ser aceitos como novo bruto. O estudo técnico de uma referência é identificado como `reference_study`; ele não comprova reconstrução, troca de personagem nem fidelidade estética.

Na rota de geração, o motor prepara e exporta prompts. O usuário gera os vídeos externamente e devolve os clipes. Não há chave de provedor de geração, chamada ao HeyGen ou job de geração de vídeo.

### Envio de arquivos e retomada

O painel acompanha cada arquivo: selecionado, autorizando, enviando, importando no motor, recebido, falha ou resultado incerto. O estado recebido depende do recibo do servidor. Arquivos escolhidos no navegador usam envio direto, sem depender de o upload nativo do ChatGPT aceitar esse formato. O arquivo original permanece na sessão até o recibo ou durante uma falha recuperável.

Cada seleção recebe um UUID estável. A interface usa a ferramenta já estabelecida `editor_save_project(state, project_id, expected_revision)` para pedir a autorização, conservando seu nome e schema externo. O comando é explícito:

```json
{
  "project_id": "ID_DO_PROJETO_EXISTENTE",
  "expected_revision": 12,
  "state": {
    "ui_action": "begin_upload",
    "upload_request": {
      "role": "ref",
      "file_name": "video.mp4",
      "mime_type": "video/mp4",
      "size_bytes": 5767168,
      "upload_id": "UUID_ESTAVEL_DA_SELECAO"
    }
  }
}
```

`shot_id` só é enviado dentro de `upload_request` para o papel `shot`. Projeto e revisão ficam exclusivamente no envelope externo. A presença de qualquer campo reservado (`ui_action` ou `upload_request`) exige o comando completo: ação desconhecida, campos extras, tipos incorretos, ausência de projeto/revisão ou mistura com escolhas do projeto são recusados antes de salvar ou criar qualquer projeto. O ramo de autorização não altera revisão, histórico, escolhas ou aprovações. A ferramenta dedicada `editor_begin_upload` permanece disponível e usa o mesmo helper; a interface não depende de ela aparecer no catálogo nativo do host e não tenta chamá-la antes de usar a ferramenta existente.

A autorização fica vinculada ao arquivo, destino e revisão informados. O ticket expira em cinco minutos e segue apenas em `_meta.editor.upload`, acessível ao componente; não fica no conteúdo do modelo nem no estado persistido do widget. A metadata fornece URL, método `POST`, cabeçalhos `Authorization: Upload …` e `Content-Type`, expiração e tamanho autorizado. A chave do proprietário e o token OAuth não são enviados ao navegador do painel. Os requisitos OAuth, escopos e permissões da ferramenta de salvamento são preservados.

O componente confere a origem HTTPS anunciada em `editor_open.upload_capabilities`, envia o `File` original com `credentials: omit` e recusa redirecionamentos. Somente `/upload-tickets/{upload_id}` permite CORS com origem `*`, sem cookies nem credenciais ambientais: o segredo curto em um cabeçalho é a autorização. O CSP libera conexões apenas à origem configurada do motor. As rotas OAuth, MCP, mídia e upload administrativo não recebem essa política CORS. O servidor confere MIME, número exato de bytes, quota, tomada, revisão e mídia real, reserva atomicamente o ticket e não admite dois recebimentos concorrentes com a mesma autorização.

Se a resposta da importação se perder, o painel consulta o projeto uma vez e recupera automaticamente o recibo confirmado. O motor preserva `hostFileId: direct:<UUID>` no recibo e no estado para que o painel reconheça o arquivo pelo projeto, papel e tomada correspondentes. A interface não reconcilia só por nome ou tamanho nem retransmite bytes automaticamente. Se essa consulta não confirmar o recibo, use **Conferir recebimento** antes de repetir. Uma nova tentativa explícita obtém outro ticket para o mesmo UUID e a revisão atual; isso invalida o ticket anterior. O mesmo UUID não pode ser reaproveitado para outro arquivo ou destino.

Falhas HTTP de envio incluem `code`, `error` e `uncertain`. `revision_conflict` usa 409; arquivo que não pode ser inspecionado (`invalid_media`), duração fora de 0–600 segundos (`media_duration`) e demais restrições conhecidas de mídia usam 422. O painel lê o JSON e apresenta mensagens locais por código: um 409 desconhecido nunca significa automaticamente que o projeto mudou. Texto arbitrário do servidor não é mostrado. Falhas sem classificação, interrupções e erros depois do commit permanecem incertos e exigem reconciliação do recibo. O log `editor_ultra.upload` registra apenas código, status, fase e UUID validado do envio, sem nomes de arquivo, caminhos internos, cabeçalhos ou credenciais. As verificações de revisão no início e no commit permanecem ativas.

Quando o motor já recebeu o arquivo, o comando de autorização devolve o recibo com o estado atual, sem novo ticket, reenvio, incremento de revisão ou restauração de seleções antigas. Um POST repetido com ticket ainda válido também só recupera esse recibo; ticket expirado é recusado mesmo quando há recibo. Após reinício, envios interrompidos não são retomados sozinhos: a consulta autenticada reconcilia o identificador durável com o motor. O ledger guarda hashes das capabilities, destinos e IDs de asset, sem copiar snapshots ou aprovações do projeto.

O player só aparece depois do recebimento confirmado, usando a prévia assinada do motor. Um arquivo ainda na sessão não é apresentado como disponível no servidor. Para anexos do próprio chat, `editor_import_file` mantém o `hostFileId` nativo e confere que uma repetição corresponda aos mesmos bytes e MIME. IDs `direct:` nunca são enviados às APIs de arquivos do ChatGPT. O envio e sua retomada não executam clonagem, renderização ou aprovação: essas etapas continuam dependendo do plano atual e das decisões explícitas pertinentes.

## Execução

Requer Python 3.12 e FFmpeg/ffprobe. O Dockerfile instala as dependências da ponte e dos executores básicos por CPU.

```bash
python -m pip install -r requirements-app.txt
python -m editor_ultra_app
```

Configure as variáveis no serviço, sem gravá-las no Git:

| Variável | Uso |
| --- | --- |
| `EDITOR_ULTRA_BASE_URL` | Origem HTTPS pública, sem `/mcp` e sem barra final |
| `EDITOR_ULTRA_OWNER_KEY` | Chave aleatória privada com pelo menos 32 caracteres, usada somente no formulário de conexão |
| `EDITOR_ULTRA_DATA_DIR` | Diretório persistente privado, por exemplo `/data/editor-ultra` |
| `EDITOR_ULTRA_MAX_STORAGE_MB` | Orçamento local de dados; padrão 850 MiB |
| `PORT` | Porta HTTP; padrão 8000 |

Use uma instância e um worker de renderização. Anexe um volume persistente a `/data`. Não escale horizontalmente a mesma fila SQLite. O serviço do Railway usa `railway.toml`, testa `/healthz` e executa o Dockerfile. A hospedagem utiliza os recursos do plano Railway; a ponte não contrata APIs de geração.

O modo HTTP local exige `EDITOR_ULTRA_ALLOW_LOOPBACK=1` e origem de loopback. Nunca habilite esse modo como substituto de HTTPS na publicação.

## Conectar no ChatGPT

No diretório de Plugins do ChatGPT, adicione um **MCP personalizado** com a URL `https://SEU-SERVICO/mcp` e autenticação **OAuth**. O servidor publica a descoberta e registra o cliente. No formulário privado do Editor Ultra, informe a chave do proprietário e confirme a conexão. Depois abra uma conversa com o plugin e peça para abrir o Editor Ultra.

O código não instala silenciosamente um plugin na conta do usuário. A conexão só está instalada quando a interface do ChatGPT confirmar essa etapa. Se mudar ferramentas, schemas ou recursos, atualize os metadados do conector.

## Abrir o estúdio e atualizar o plugin

A tela inicial do estúdio é o recurso `ui://editor-ultra/studio-v8.html`, associado à ferramenta `editor_open`. Abrir essa ferramenta com `{}` carrega a interface, consulta os projetos e a situação do catálogo e anuncia a capacidade de envio direto, sem criar projeto, iniciar render ou registrar aprovação.

A v8 aplica a direção visual Essencial: cabeçalho horizontal com o símbolo E aprovado, base grafite, seleção violeta, ação principal verde-lima, prévia central e ajustes complementares recolhidos em **Mais ajustes**. Início, Projetos, Templates e Histórico mantêm os mesmos dados e comandos reais. O símbolo é servido somente pela rota fixa pública `/brand/e-mark-v1.png`, com cache imutável; arquivos de projeto continuam protegidos por seus contratos de autenticação e URLs assinadas.

O item **Editor Ultra** declara dois acessos nativos: `global`, na navegação principal do host, e `thread`, como aba de conteúdo da conversa. A interface prefere `fullscreen` e também anuncia suporte a `inline`. O host decide o modo efetivo e quais acessos apresenta. A tela de conexão/configuração do plugin pertence ao ChatGPT; o estúdio é a interface aberta pela ferramenta ou por esses acessos.

Se o host não mostrar o acesso direto, selecione o plugin na conversa e peça **“Abrir Editor Ultra”**. Esse caminho chama a mesma ferramenta e usa o mesmo motor e os mesmos projetos. A disponibilidade dos entrypoints depende da versão e da superfície do ChatGPT; a especificação de extensões define seu suporte web para o navegador Work, sem incluir o ChatGPT clássico.

Depois de publicar a atualização do servidor:

1. Atualize os metadados do plugin/conector nas configurações do ChatGPT para obter os entrypoints e a nova URI do recurso.
2. Feche a instância anterior do painel e abra o Editor Ultra novamente. Uma interface já montada pode continuar executando a versão anterior.
3. Confira a abertura da tela inicial e a navegação no host usado. Uma chamada MCP bem-sucedida não comprova, sozinha, que o host montou a interface.

A URI do recurso funciona como chave de cache. Em mudanças incompatíveis de HTML, JavaScript ou CSS, publique outra URI e atualize tanto o recurso quanto as referências `ui.resourceUri` e `openai/outputTemplate` da ferramenta. A versão v8 preserva o diagnóstico por código e a recuperação automática por leitura do recibo introduzidos na v7. O envio continua usando `editor_save_project`, sem exigir o reconhecimento de uma ferramenta nova. As URIs `ui://editor-ultra/studio-v1.html` até `ui://editor-ultra/studio-v7.html` permanecem como aliases do mesmo HTML e da mesma metadata. Os aliases atendem referências anteriores quando o host busca novamente o recurso; uma interface já montada precisa ser substituída pela versão atual. A permissão CSP de conexão continua restrita à origem do motor.

O bridge usa `tools/call` do MCP Apps. As ferramentas chamadas pelo painel também declaram `openai/widgetAccessible: true` para o fallback `window.openai.callTool`; o caminho de autorização da interface usa `editor_save_project` em ambos os transportes. `editor_begin_upload` conserva visibilidade `app` por compatibilidade com clientes que já o reconhecem, e `editor_import_file` conserva `openai/fileParams: ["file"]`. Essa metadata não altera as verificações de autenticação, revisão ou confirmação do servidor. Só `editor_open` referencia o template, para que chamadas de dados não remontem a interface.

Referências: [UI e versionamento de recursos](https://developers.openai.com/plugins/build/chatgpt-ui), [extensões de plugins](https://developers.openai.com/plugins/build/extensions), [especificação de entrypoints e modos de exibição](https://github.com/openai/mcp-extensions/blob/main/docs/spec.md) e [referência de metadata e bridge](https://developers.openai.com/plugins/reference).

## Catálogo privado

O arquivo de instalação é um ZIP privado que contém `gallery.json` e o pacote original `Clone-Templates-1.0.0/`, com `library.json` e seus caminhos preservados. O catálogo não pertence ao repositório. Envie o pacote ao endpoint autenticado `POST /catalog/install` com um token OAuth de escrita.

A instalação rejeita caminhos externos, links simbólicos, arquivos repetidos e pacotes acima dos limites. Verifica os hashes da biblioteca, guarda um recibo e ativa a nova versão somente após a conferência. As miniaturas são servidas por URLs temporárias vinculadas a cada arquivo.

`editor_list_templates` lista amostras do acervo; `editor_get_template` retorna requisitos, bindings e limitações. Instanciar um template não equivale a renderizá-lo. HTML, GSAP, HyperFrames, fontes, recursos externos, camadas RGBA, tracking, mattes ou operações 3D exigem seus adaptadores e materiais efetivos. A ponte não transforma um MP4 de demonstração em overlay transparente.

## Medir movimento por elemento

`editor_measure_motion(project_id, asset_id, specification, expected_revision, request_id)`
adiciona à fila um trabalho `measure_motion` sobre um vídeo já importado no
projeto. A especificação declara os elementos, as janelas de quadros, o quadro
inicial de rastreamento e a região de cada elemento. O comando mede posição,
escala uniforme e rotação 2D, ajusta as curvas e registra a cobertura. Texto e
painel devem ter IDs próprios quando seus movimentos não são iguais.

```json
{
  "schema": "element-motion-measurement/1",
  "cuts": [],
  "elements": [{
    "id": "painel",
    "range": [30, 60],
    "seed_frame": 30,
    "roi_px": [100, 180, 400, 700]
  }]
}
```

As coordenadas pertencem ao raster orientado da fonte; `[30, 60]` seleciona
os quadros 30 a 59. Declare `rotation_ccw` quando a orientação do contêiner
exigir essa decisão. Uma máscara opcional usa `mask_asset_id`, correspondente
a uma imagem do mesmo projeto. A ferramenta não aceita caminhos locais ou
URLs como substitutos de arquivos importados.

O resultado fica em `motion_measurements` e contém quatro IDs de artefato:
observações, perfil de curvas, auditoria JSON e tabela CSV. Use `editor_get_asset`
para obtê-los. Revisão esperada e `request_id` protegem contra pedidos antigos
ou repetidos. Alterações na revisão do projeto, na fonte, nas máscaras ou nos
artefatos tornam a evidência histórica, com estado `stale`.

Este trabalho tem escopo `evidence_not_applied` e estado de render
`pending_not_applied`: medir não altera automaticamente o plano nativo nem
aprova um vídeo. A aplicação implementada das curvas ocorre por bindings
explícitos nos renderers `geometric_video` e `studio_edit`, conforme o
[manual do perfil de movimento](../visual_fidelity/MOTION_PROFILE.md).
O adaptador para aplicação automática no `native.render_bundle` permanece
pendente; a interface também não recebeu um editor visual de regiões nesta versão.

O servidor aceita até quatro elementos por pedido, 300 quadros por janela e
600 quadros de elementos somados, sujeito a um cache de cinza de 128 MiB. A
fonte precisa caber simultaneamente nos limites de 120 segundos, 3.600 quadros,
120 fps nominais, 2.073.600 pixels por quadro, lado de até 4.096 pixels e quatro
bilhões de pixels decodificados. Se um limite for excedido, o pedido é recusado
com orientação para selecionar uma fonte ou janela menor; não há redução de
resolução ou retiming silencioso. Esses limites pertencem ao servidor, não são
limites matemáticos do perfil.

Depois de implantar o servidor atualizado, renove os metadados do conector
para disponibilizar a nova ferramenta. Testes locais não confirmam que uma
instância hospedada já recebeu essa versão.

## Persistência e recuperação

Cada trabalho tem chave de idempotência e estado `queued`, `running`, `completed`, `failed` ou `interrupted`. Depois de reiniciar, um trabalho que estava executando fica `interrupted`; ele não é repetido automaticamente. Confira o projeto e os artefatos antes de reenviar uma operação com resultado desconhecido.

O servidor confere a revisão esperada antes de mutações. Clientes devem atualizar o projeto após conflito ou timeout. Uploads, resultados e aprovações ficam separados; importar o JSON do painel não importa os vídeos e não autoriza uma aprovação.

Arquivos e estados privados ficam no volume. Backups/restauração e limpeza de projetos precisam preservar os vínculos de caminho do motor; não mova o diretório de um projeto selado manualmente. O limite de upload é de até 512 MiB por arquivo, sujeito ao espaço disponível; vídeos admitidos têm até 10 minutos. Não há execução automática de modelos pesados ausentes.

## Validação

```bash
python -m pytest tests/test_app_auth.py tests/test_app_infrastructure.py tests/test_app_engine.py tests/test_app_server.py tests/test_app_uploads.py tests/test_app_motion.py -q
python scripts/check_app_connection.py https://SEU-SERVICO --key-stdin
```

O helper cria um grant temporário, verifica descoberta e transporte MCP e o revoga ao terminar. Não imprime tokens nem afirma instalar o plugin. A chave pode ser fornecida por stdin ou por `EDITOR_ULTRA_OWNER_KEY`; não a inclua em comandos salvos ou no histórico.

O teste de engine usa mídia sintética identificada para conferir importação, direção, execução FFmpeg, revisões e invalidação. Isso comprova conexão técnica e produção de arquivo; não representa revisão perceptiva ou aprovação de um vídeo do usuário.

O teste de servidor confere por MCP os metadados de abertura, entrypoints, permissão do fallback, preservação de file params e o recurso v8 com preferência por fullscreen. Confere também que os aliases v1 a v7 retornam o mesmo HTML e a mesma metadata, enquanto a ferramenta anuncia a v8. A rota fixa do símbolo E retorna o PNG aprovado, sem expor outros arquivos da aplicação. O schema externo de `editor_save_project` continua contendo apenas `state`, `project_id` e `expected_revision`. O teste abre `editor_open` com `{}` e verifica que essa abertura não cria projeto. A importação nativa usa um MP4 sintético com download substituído por cópia local: recibo e consulta preservam `hostFileId`, e repetir na revisão atual não duplica o asset nem incrementa a revisão.

Os testes de envio direto usam `editor_save_project` pelo MCP autenticado e a rota HTTP real no processo de teste. Conferem segredo somente em `_meta`, preflight CORS e seu isolamento, recebimento de MP4, limites de bytes e MIME, conflito de revisão/destino, repetição e recuperação após falha entre commit e finalização do ledger. O recibo recuperado mantém escolhas posteriores; a ferramenta dedicada recupera o mesmo resultado. Comandos reservados parciais, desconhecidos, misturados ou malformados não criam projetos, tickets ou revisões, e o salvamento normal continua funcionando. Os testes do ledger conferem hash de segredo, expiração mesmo após recebimento, claim concorrente, rotação, reinício e limites; tentativas sem capability válida não consomem a quota de envios legítimos. Isso verifica o contrato técnico sem registrar aprovação de um vídeo do usuário. Envio, reprodução, renderização da interface e navegação no ChatGPT ainda exigem conferência no host real.

