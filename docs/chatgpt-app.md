# Editor Ultra dentro do ChatGPT

O pacote `editor_ultra_app` conecta a interface ao motor existente, por um servidor MCP autenticado. A interface não contém chaves, vídeos particulares ou o catálogo privado. Os botões chamam ferramentas do servidor, que mantém projetos, recibos de arquivos, revisões e trabalhos em disco persistente.

A direção criativa continua no ChatGPT: o motor prepara evidências e um contrato de direção; o host observa o material e fornece um plano explícito. O servidor executa esse plano nas operações implementadas. Um pedido preparado, uma demonstração do catálogo e um teste técnico não são uma clonagem aprovada.

## Fluxo conectado

1. `editor_open` abre o painel. `editor_save_project` registra as escolhas sem confiar em aprovações contidas no JSON do navegador.
2. Na home, **Começar projeto** cria o projeto e envia os arquivos selecionados. Nas etapas do fluxo, escolher um novo arquivo inicia seu envio automaticamente. A interface envia cada arquivo ao ChatGPT e usa `editor_import_file` para transferi-lo ao motor. A importação confere o tipo real de mídia, a duração e os bytes. Uma URL `blob:` ou o nome de um arquivo não contam como transferência.
3. `editor_prepare` registra um trabalho persistente. A preparação chama `editorial_engine.project`, produz análise real quando a rota permite e devolve as pendências e o pedido de direção.
4. O host usa `editor_get_asset` para inspecionar evidências e `editor_apply_direction` para entregar a direção no contrato solicitado. IDs `asset:<id>` substituem caminhos arbitrários.
5. `editor_render` executa o plano atual. `editor_get_project` e `editor_get_result` retornam o resultado real com links temporários de prévia.
6. `editor_record_review` recebe uma decisão explícita sobre o arquivo atual. Alterar referência, direção, material ou resultado invalida os vínculos pertinentes. Uma revisão técnica não preenche a confirmação do usuário.

Para referência com pessoa nova, os pixels da referência não podem ser aceitos como novo bruto. O estudo técnico de uma referência é identificado como `reference_study`; ele não comprova reconstrução, troca de personagem nem fidelidade estética.

Na rota de geração, o motor prepara e exporta prompts. O usuário gera os vídeos externamente e devolve os clipes. Não há chave de provedor de geração, chamada ao HeyGen ou job de geração de vídeo.

### Envio de arquivos e retomada

O painel acompanha cada arquivo: selecionado, enviando ao ChatGPT, importando no motor, recebido, falha ou resultado incerto. O estado recebido depende do recibo do servidor. Uma falha conhecida mantém o arquivo disponível para nova tentativa; quando já existe um `fileId`, a tentativa reutiliza esse identificador e solicita um link temporário novo.

Se a resposta da importação se perder, confira o projeto antes de repetir. O motor preserva `hostFileId` no recibo e no estado para que o painel reconheça o arquivo recebido pelo projeto, papel e tomada correspondentes. A interface não reconcilia só por nome ou tamanho nem repete automaticamente uma operação incerta. Se a conferência não encontrar o recibo, o usuário pode tentar novamente. Com a revisão atual, repetir o mesmo identificador, papel, tomada, bytes e MIME recupera o asset existente; conteúdo divergente para o mesmo identificador é recusado.

Após o recibo, a prévia assinada do motor tem preferência sobre o `blob:` local. Uma falha de reprodução local não significa expiração do acesso remoto. O envio e sua retomada não executam clonagem, renderização ou aprovação: essas etapas continuam dependendo do plano atual e das decisões explícitas pertinentes.

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

A tela inicial do estúdio é o recurso `ui://editor-ultra/studio-v3.html`, associado à ferramenta `editor_open`. Abrir essa ferramenta com `{}` carrega a interface e consulta os projetos e a situação do catálogo, sem criar projeto, iniciar render ou registrar aprovação.

O item **Editor Ultra** declara dois acessos nativos: `global`, na navegação principal do host, e `thread`, como aba de conteúdo da conversa. A interface prefere `fullscreen` e também anuncia suporte a `inline`. O host decide o modo efetivo e quais acessos apresenta. A tela de conexão/configuração do plugin pertence ao ChatGPT; o estúdio é a interface aberta pela ferramenta ou por esses acessos.

Se o host não mostrar o acesso direto, selecione o plugin na conversa e peça **“Abrir Editor Ultra”**. Esse caminho chama a mesma ferramenta e usa o mesmo motor e os mesmos projetos. A disponibilidade dos entrypoints depende da versão e da superfície do ChatGPT; a especificação de extensões define seu suporte web para o navegador Work, sem incluir o ChatGPT clássico.

Depois de publicar a atualização do servidor:

1. Atualize os metadados do plugin/conector nas configurações do ChatGPT para obter os entrypoints e a nova URI do recurso.
2. Feche a instância anterior do painel e abra o Editor Ultra novamente. Uma interface já montada pode continuar executando a versão anterior.
3. Confira a abertura da tela inicial e a navegação no host usado. Uma chamada MCP bem-sucedida não comprova, sozinha, que o host montou a interface.

A URI do recurso funciona como chave de cache. Em mudanças incompatíveis de HTML, JavaScript ou CSS, publique outra URI e atualize tanto o recurso quanto as referências `ui.resourceUri` e `openai/outputTemplate` da ferramenta. A versão v3 é a URI primária da correção de envio automático. As URIs `ui://editor-ultra/studio-v1.html` e `ui://editor-ultra/studio-v2.html` permanecem como aliases do mesmo HTML e da mesma metadata, para atender instalações que ainda referenciem versões anteriores durante a atualização. Os aliases preservam a leitura desses recursos; obter os metadados atuais e substituir uma interface já montada ainda exige atualizar o plugin e reabrir o painel.

O bridge usa `tools/call` do MCP Apps. As ferramentas chamadas pelo painel também declaram `openai/widgetAccessible: true` para o fallback `window.openai.callTool`; `editor_import_file` conserva `openai/fileParams: ["file"]`. Essa metadata não altera as verificações de autenticação, revisão ou confirmação do servidor. Só `editor_open` referencia o template, para que chamadas de dados não remontem a interface.

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
python -m pytest tests/test_app_auth.py tests/test_app_infrastructure.py tests/test_app_engine.py tests/test_app_server.py tests/test_app_motion.py -q
python scripts/check_app_connection.py https://SEU-SERVICO --key-stdin
```

O helper cria um grant temporário, verifica descoberta e transporte MCP e o revoga ao terminar. Não imprime tokens nem afirma instalar o plugin. A chave pode ser fornecida por stdin ou por `EDITOR_ULTRA_OWNER_KEY`; não a inclua em comandos salvos ou no histórico.

O teste de engine usa mídia sintética identificada para conferir importação, direção, execução FFmpeg, revisões e invalidação. Isso comprova conexão técnica e produção de arquivo; não representa revisão perceptiva ou aprovação de um vídeo do usuário.

O teste de servidor confere por MCP os metadados de abertura, entrypoints, permissão do fallback, preservação de file params e o recurso v3 com preferência por fullscreen. Confere também que os aliases v1 e v2 retornam o mesmo HTML e a mesma metadata, enquanto a ferramenta anuncia a v3. Ele abre `editor_open` com `{}` e verifica que essa abertura não cria projeto. A importação nativa usa um MP4 sintético com download substituído por cópia local no teste: o recibo e a consulta preservam `hostFileId`, e a repetição na revisão atual não duplica o asset nem incrementa a revisão. Isso verifica o contrato do servidor, sem simular uma aprovação do usuário ou comprovar upload e reprodução no host real. A renderização e a navegação oferecidas pelo ChatGPT exigem conferência visual no host.
