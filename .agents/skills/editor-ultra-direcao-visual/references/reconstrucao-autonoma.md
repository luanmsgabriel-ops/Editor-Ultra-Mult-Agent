# Reconstrução autônoma: uma referência, nenhum vídeo-alvo

**Pedido típico:** “Use este vídeo de referência e recrie só os efeitos em um vídeo novo.” O resultado é uma demonstração autoral montada do zero. Não é sobrepor efeitos no vídeo bruto, recortar a pessoa original ou exportar o vídeo de referência transformado. Não retome um vídeo encerrado nem use seu material por conveniência.

## Entrada, execução e saída

1. **Entrada:** vídeo de referência legível. Opcionalmente, pessoa fornece formato de saída, direção visual neutra ou materiais próprios. Sem esses dados, comece com o formato da referência e material autoral neutro. Documente relógio, orientação, áudio e duração. Se o original for VFR e o motor só exportar CFR, registre o mapeamento de PTS para a grade do render e o erro de arredondamento (não apresente como identidade de relógio).
2. **Inventário:** anote por efeito seu ID, frames `[início, fim)`, PTS, regiões, tipo de controle e assinatura mensurável. Exemplos: curva de deslocamento, variação de largura/transparência, face à frente de placa, texto revelado em batidas, ângulo de sombra, deformação e refração, entrada/saída de flashes e filtro no intervalo. Não atribua software, shader ou fonte a partir do RGB achatado.
3. **Palco e camadas:** crie cenário/objetos neutros no mesmo plano de câmera e reconstrução volumétrica apenas quando o efeito exigir. Se o efeito depender de mão, pulso, profundidade, movimento externo ou de um recorte, monte um equivalente com personagem neutro, objeto ou geometria autoral. Exemplo: caderno e papel originais do projeto, sombra de contato e forma 3D emergindo da página, em camadas separadas. Para um corte exterior/interior, construa dois planos autorais distintos; não simule o corte adicionando um flash em um único plano. Revele texto próprio/neutro com a mesma lógica de máscaras, cor e ritmo; se faltar o arquivo exato com licença, crie a solução tipográfica aqui no chat. Crie também os ícones que faltarem. Siga [o protocolo de tipografia e ícones](tipografia-e-icones.md), sem copiar pixels da referência.
4. **Motor:** transforme a receita em camadas e chame os operadores suportados. Se não houver operador nativo para um efeito, indique o que falta; um render local feito por um adaptador é demonstração, não integração do motor. Não mande referência ou assets a serviços externos por padrão.
5. **Saídas:** vídeo independente (mudo por padrão; use áudio autoral/licenciado se solicitado e suportado), receita executável para a versão usada, inventário de efeitos, origens dos ativos e evidência com frames/timecodes. Se o motor indisponível impedir render, entregue o que pôde produzir e registre o bloqueio. Não apresente a referência junto como se fosse o MP4 novo; provas comparativas locais são artefatos separados.

## Portão de qualidade

- **Referência × candidato:** alinhe pelo evento e compare assinatura por camada. Não exija RGB idêntico entre cenas diferentes. Meça, quando pertinente, desvio de timing na grade, escala/posição e suavidade, cor em zona comparável, bordas da máscara, ordenação e estabilidade temporal, blur e retorno após oclusão.
- **Controle × candidato:** mesmo palco, ativos, frames e relógio. Primeiro isole o efeito nas matrizes/passes anteriores ao encode; compare dentro e fora da máscara. Depois decodifique o MP4 e compare de novo com controle exportado nas mesmas condições. Verifique contagem de quadros, PTS de exibição, áudio e regiões protegidas. Se houver splice, cheque também DTS, parâmetros AVC, fronteiras de GOP, priming e continuidade. Se não preservar os invariantes, mantenha a alteração em prévia ou reexporte com controle compatível; não promova ao master.
- **Falha → próxima ação:** anote timecode, região, hipótese/causa, técnica testada, medidas, regressões e aprovação/rejeição antes de repetir. Use teste negativo para não disparar tracking ou efeitos quando a evidência some. Não confunda contagem de efeitos com identidade estética.
- **Testes separados:** use fixture sintética/autoral para provar o caminho técnico e a medição. No próximo vídeo inédito enviado pelo usuário, sem reaproveitar mídia encerrada, valide o inventário, a generalização e o resultado em movimento. Fixture sintética não prova generalização nem exige uso de mídia cliente em Git.

## Prova local do modo autônomo

Numa cópia do motor que inclua o módulo `editorial_engine.effects_only` e a fixture `fixtures/effects-only-synthetic.json`, use Python 3.11+, Pillow, FFmpeg e FFprobe. Rode na raiz da cópia:

```sh
python -m editorial_engine.effects_only fixtures/effects-only-synthetic.json --out out/efeitos-sinteticos
```

Use um diretório de saída novo/vazio. A receita `editor-ultra-effects-only/1` só aceita o hash da referência marcado como `analysis_only`, não o arquivo de vídeo, caminho, URL ou asset externo. Cada efeito traz `id`, `kind`, `start_frame`, `end_frame`, `z`, `provenance` e `params`; o intervalo é semiaberto e a pilha é ordenada por `z` e, em caso de empate, por `id`. A versão inicial aceita primitivas autorais: texto estático por janela (`caption`, que pode ser escalonado com várias janelas), painel em movimento (`panel`) e pulso colorido (`pulse`). Use coordenadas inteiras em pixels e cor opaca `#RRGGBB`. Parâmetros: legenda `x,y,color,text`; painel `x,y,x_end,y_end,width,height,color`; pulso `x,y,width,height,color`. Não suporta áudio, ingestão/análise automática da referência, transferência para bruto, fonte externa, recorte, tracking, 3D ou B-roll real. Efeitos não suportados ficam fora do manifesto de execução (marque-os como bloqueados ou não testados no inventário); não os substitua em silêncio.

Arquivos esperados: `effects.mkv` (master FFV1 sem áudio), `manifest.json` e `receipt.json`. O master sem perdas preserva os pixels do palco gerado e é base para comparar revisões. Se precisar de um MP4 para visualização, trate-o como derivado e valide-o separadamente; não presuma que pixels do MP4 correspondem ao master.

Depois de renderizar duas receitas de mesmo palco em diretórios separados, verifique a janela de alteração permitida:

```sh
python -m editorial_engine.effects_only --compare out/controle out/candidato --window 17 18
```

Essa comparação protege relógio, áudio e frames fora de `[17,18)` (ajuste o intervalo para a mudança real). Para proteger também a área fora de um retângulo no frame alterado, acrescente `--region LEFT TOP RIGHT BOTTOM` (limites direito e inferior exclusivos). O comparador não mede semelhança com a referência nem valida a máscara em si: confira bordas, métricas locais e movimento separadamente.
