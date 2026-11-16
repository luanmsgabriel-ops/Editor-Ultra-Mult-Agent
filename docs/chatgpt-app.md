# Editor Ultra dentro do ChatGPT

O pacote `editor_ultra_app` conecta a interface ao motor existente, por um servidor MCP autenticado. A interface não contém chaves, vídeos particulares ou o catálogo privado. Os botões chamam ferramentas do servidor, que mantém projetos, recibos de arquivos, revisões e trabalhos em disco persistente.

A direção criativa continua no ChatGPT: o motor prepara evidências e um contrato de direção; o host observa o material e fornece um plano explícito. O servidor executa esse plano nas operações implementadas. Um pedido preparado, uma demonstração do catálogo e um teste técnico não são uma clonagem aprovada.

## Fluxo conectado

1. `editor_open` abre o painel. `editor_save_project` registra as escolhas sem confiar em aprovações contidas no JSON do navegador.
2. A interface envia cada arquivo ao ChatGPT e usa `editor_import_file` para transferi-lo ao motor. A importação confere o tipo real de mídia, a duração e os bytes. Uma URL `blob:` ou o nome de um arquivo não contam como transferência.
3. `editor_prepare` registra um trabalho persistente. A preparação chama `editorial_engine.project`, produz análise real quando a rota permite e devolve as pendências e o pedido de direção.
4. O host usa `editor_get_asset` para inspecionar evidências e `editor_apply_direction` para entregar a direção no contrato solicitado. IDs `asset:<id>` substituem caminhos arbitrários.
5. `editor_render` executa o plano atual. `editor_get_project` e `editor_get_result` retornam o resultado real com links temporários de prévia.
6. `editor_record_review` recebe uma decisão explícita sobre o arquivo atual. Alterar referência, direção, material ou resultado invalida os vínculos pertinentes. Uma revisão técnica não preenche a confirmação do usuário.

Para referência com pessoa nova, os pixels da referência não podem ser aceitos como novo bruto. O estudo técnico de uma referência é identificado como `reference_study`; ele não comprova reconstrução, troca de personagem nem fidelidade estética.

Na rota de geração, o motor prepara e exporta prompts. O usuário gera os vídeos externamente e devolve os clipes. Não há chave de provedor de geração, chamada ao HeyGen ou job de geração de vídeo.

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

## Catálogo privado

O arquivo de instalação é um ZIP privado que contém `gallery.json` e o pacote original `Clone-Templates-1.0.0/`, com `library.json` e seus caminhos preservados. O catálogo não pertence ao repositório. Envie o pacote ao endpoint autenticado `POST /catalog/install` com um token OAuth de escrita.

A instalação rejeita caminhos externos, links simbólicos, arquivos repetidos e pacotes acima dos limites. Verifica os hashes da biblioteca, guarda um recibo e ativa a nova versão somente após a conferência. As miniaturas são servidas por URLs temporárias vinculadas a cada arquivo.

`editor_list_templates` lista amostras do acervo; `editor_get_template` retorna requisitos, bindings e limitações. Instanciar um template não equivale a renderizá-lo. HTML, GSAP, HyperFrames, fontes, recursos externos, camadas RGBA, tracking, mattes ou operações 3D exigem seus adaptadores e materiais efetivos. A ponte não transforma um MP4 de demonstração em overlay transparente.

## Persistência e recuperação

Cada trabalho tem chave de idempotência e estado `queued`, `running`, `completed`, `failed` ou `interrupted`. Depois de reiniciar, um trabalho que estava executando fica `interrupted`; ele não é repetido automaticamente. Confira o projeto e os artefatos antes de reenviar uma operação com resultado desconhecido.

O servidor confere a revisão esperada antes de mutações. Clientes devem atualizar o projeto após conflito ou timeout. Uploads, resultados e aprovações ficam separados; importar o JSON do painel não importa os vídeos e não autoriza uma aprovação.

Arquivos e estados privados ficam no volume. Backups/restauração e limpeza de projetos precisam preservar os vínculos de caminho do motor; não mova o diretório de um projeto selado manualmente. O limite de upload é de até 512 MiB por arquivo, sujeito ao espaço disponível; vídeos admitidos têm até 10 minutos. Não há execução automática de modelos pesados ausentes.

## Validação

```bash
python -m pytest tests/test_app_auth.py tests/test_app_infrastructure.py tests/test_app_engine.py -q
python scripts/check_app_connection.py https://SEU-SERVICO --key-stdin
```

O helper cria um grant temporário, verifica descoberta e transporte MCP e o revoga ao terminar. Não imprime tokens nem afirma instalar o plugin. A chave pode ser fornecida por stdin ou por `EDITOR_ULTRA_OWNER_KEY`; não a inclua em comandos salvos ou no histórico.

O teste de engine usa mídia sintética identificada para conferir importação, direção, execução FFmpeg, revisões e invalidação. Isso comprova conexão técnica e produção de arquivo; não representa revisão perceptiva ou aprovação de um vídeo do usuário.
