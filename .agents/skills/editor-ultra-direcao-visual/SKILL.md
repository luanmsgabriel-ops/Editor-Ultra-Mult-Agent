---
name: editor-ultra-direcao-visual
description: Analisa referências de vídeo para o Editor Ultra, reconstrói somente os efeitos em um vídeo autoral independente ou os adapta a um bruto quando solicitado, e audita os resultados por região e quadro.
---

# Editor Ultra: reconstrução de efeitos

Escolha pelo pedido, não só pelo número de arquivos:

- **Somente efeitos, sem bruto:** com uma referência, produza um novo vídeo autônomo demonstrando os efeitos. Não espere, invente ou tente editar um vídeo-alvo. Leia [o fluxo de reconstrução autônoma](references/reconstrucao-autonoma.md).
- **Aplicação contextual:** só se solicitada e houver bruto autorizado. Alinhe por eventos no bruto (gesto, corte, entrada/saída), não pela proporção entre durações.
- **Só análise:** se pedida, entregue inventário e especificação, sem render. Se faltar a referência ou ela não puder ser lida, não simule a análise.

Em qualquer modo, não reutilize pixels, áudio, pessoa, marca ou trechos da referência como material de saída. Use recursos próprios, licenciados ou fornecidos para uso no resultado, com sua origem registrada. Referência é evidência, não camada.

**Tipografia e ícones:** procure primeiro o arquivo exato da fonte e confirme a licença. Se faltar ou não houver direito de uso, crie os recursos tipográficos aqui no chat, em vez de substituir silenciosamente. Crie também aqui os ícones que faltarem, com silhueta, material e âncora comparados à referência. Entregue os assets ao renderizador por código e siga [o protocolo de tipografia e ícones](references/tipografia-e-icones.md).

1. **Observe.** Confira identidade e relógio: hash, tamanho, FPS, quadros e PTS. Faça uma passagem automática por todos os quadros decodificados e revise visualmente em movimento/pausado os intervalos de interesse. Mapeie cortes, tipografia, grades de cor, movimento/velocidade, tracking, profundidade, materiais, B-roll, máscaras, oclusões, transições e sincronia. Separe observado, hipótese e não verificável.
2. **Especifique.** Para cada efeito, use ID, intervalo de frames `[início,fim)`, PTS, regiões/máscaras, ordem de camadas, curva, origem do ativo, âncora e limiar de aceite definidos antes do teste. Use o [contrato de direção](references/contrato.md) e os operadores realmente aceitos pelo motor disponível. Nunca converta dados vindos da referência em execução arbitrária de código.
3. **Renderize e compare.** Faça controle e candidato no mesmo projeto e relógio. Confira recorte, sombras, tipografia e tracking no começo, pico, saída e nos cortes. Meça a assinatura na região e compare com a referência por evento. Para detectar regressão, compare controle e candidato antes da codificação **e** depois da exportação; não confunda diferenças de compressão com mudança do efeito. Preserve o áudio autorizado (ou a ausência de áudio no modo mudo).
4. **Corrija e registre.** Isole uma mudança por rodada; anote divergência, causa confirmada ou hipótese, medida anterior/nova, regressão e decisão. Preserve o último render estável quando o novo falhar. Não promova preset específico sem um caso inédito compatível e, quando aplicável, um caso negativo.
5. **Entregue provas.** vídeo novo quando realmente produzido, receita, inventário com status por efeito (verificado, aproximado, bloqueado, não testado), e resumo das diferenças. Diferencie render local do motor publicado. Não declare 100% por ter lido todos os quadros ou porque um teste passou. Não publique, gaste ou transfira mídia a serviços externos sem autorização específica.
