# Validação das conexões do Projeto Clone

Registro de 16/11/2026. Esta etapa conecta os módulos existentes por projeto persistente, dossiê de referência, direção de geração, produção tipada, montagem real, acabamento e entrega. Os contratos e o uso estão em [clone-project.md](clone-project.md).

## Gate executado

```sh
python -m pytest -q tests extensions --tb=short --disable-warnings
```

Resultado: **538 testes passaram, 57 subtestes passaram, 2 avisos, nenhuma falha**. Tempo registrado: **96,40 segundos**. A suíte anterior desta base registrava 473 testes e 49 subtestes; esta etapa acrescentou 65 testes e 8 subtestes ao gate completo.

Os testes exercitam arquivos reais e regras de integridade. Os relatórios sintéticos de revisão usados para testar o protocolo não representam aprovação estética, escuta de uma campanha real nem confirmação do usuário.

## Evidências por conexão

| Conexão | O que foi exercitado |
| --- | --- |
| Projeto e retomada | Onze rotas declaradas; perguntas essenciais quando falta briefing; retomada sem repetir a preparação já atual; revisões e artefatos persistidos |
| Edição contextual | Vídeo real preparado, direção de preservação explicitamente autorada, render com fonte intacta, revisão por hash, bloqueio de entrega antes da cobertura completa |
| Referência | Observações atribuídas, escopo real, decisão manter/substituir, contexto ligado ao pedido; rejeição da rota com referência quando falta o pedido atual |
| Direção de geração | Imagens reais incorporadas e verificadas, orçamento de amostras, contexto de templates, restrições de briefing, rejeição de arquivos prontos inventados e alegações incompatíveis com a evidência |
| Provedores | Transporte injetado identificado como simulação; rejeição de alterações de arquivos durante a chamada; nenhuma chamada paga ou modelo externo usada no gate |
| Produção | Callback de imagem, receita local de motion, importação tipada, vínculo ao pedido, custos e execução incerta, idempotência e reconciliação sem duplicar callback |
| Template | Instância preservando o pacote, renderer explícito, sequência RGBA real, importação manual ligada à instância e rejeição de preview reaproveitado como variante renderizada |
| Montagem | FFmpeg real: trims, cortes, crossfade, wipes/slides declarados, contain/cover e FPS opt-in; vídeo, PCM, padding AAC, fontes preservadas e dependências atuais |
| Acabamento | Montagem → análise do filme → edição contextual; segunda passagem sem ciclo; importações externas sucessivas; arquivo medido depois da cópia |
| Revisão e entrega | Orçamento e relatórios anteriores preservados; pós não encerrada por conferência parcial; pacote novo com arquivos e hashes conferidos; adulteração e sobrescrita bloqueadas |

### Montagem medida

As verificações de montagem incluem corte e trim com **14 quadros / 67.200 amostras PCM**, sobreposição visual e sonora com **16 quadros / 76.800 amostras PCM**, e sequências a **30000/1001 FPS** com **19 quadros / 30.430 amostras PCM**. O áudio é explicitamente reamostrado quando solicitado, e a duração final desconta as sobreposições. Os fixtures são cores e tons sintéticos, sem avaliação de linguagem cinematográfica.

### Demonstração reproduzível

```sh
python -m examples.project_flow.demo --output /caminho/novo/prova-clone
```

Executada nesta etapa com três clipes sintéticos locais de um segundo, duas transições crossfade de 0,2 s e saída a 10 FPS. O resultado medido foi **2,6 segundos / 26 quadros**. Foram criados prompts, três recibos de retorno, plano de montagem, MP4, revisão técnica e pacote de prévia com dependências. O estado final permaneceu `awaiting_review`; nenhuma revisão perceptiva ou aprovação do usuário foi inventada.

O exemplo produz `proof.json` e `delivery/preview.mp4`. O diretório precisa ser novo. Não utiliza templates privados, credenciais, provedor de vídeo ou arquivos do usuário.

## Correções verificadas durante a integração

- O render de uma segunda passagem congela a cadeia de dependências anterior; reutilizar nomes de etapas não cria autodependência.
- Os selos canônicos de pedidos e recibos JSON não são confundidos com hashes dos bytes de seus arquivos. Recursos com pares explícitos de caminho/hash, inclusive o PCM, entram no inventário da entrega.
- Planos anteriores precisam manter os bytes registrados antes de aceitar sua próxima revisão.
- Planos importados manualmente respeitam quantidade e duração dos clipes, diálogo literal e respostas explícitas do projeto, como os retornos do provider.
- Receber um recurso simulado não satisfaz uma necessidade real. Receber um render de template exige vínculo à instância correspondente.
- A conclusão de pós exige uma passagem de acabamento com bytes novos e um relatório próprio contínuo de movimento, áudio e edição, com IDs conhecidos e status `resolved`.

## Limites da evidência

Esta validação não demonstra inferência de um modelo de direção em vídeo de cliente, execução em um gerador externo, qualidade de voz, lip-sync, troca de rosto, atuação de personagem ou render de todos os templates privados. Esses processos dependem do host, de um adaptador configurado ou de mídia produzida externamente, com sua revisão real.

O pacote de entrega conserva manifests e mapa de caminhos. Não instala fornecedores, publica automaticamente no Drive, restaura um projeto em outro caminho nem promove resultados à biblioteca. Os pontos G01–G10 e as dependências restantes estão descritos no [manual](clone-project.md#11-estado-das-inclusões-g01g10).
