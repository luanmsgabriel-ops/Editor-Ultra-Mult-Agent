# Tipografia e ícones autorais

A referência orienta medidas, estilo e comportamento, não fornece pixels à saída. Crie os assets nesta conversa e entregue seus arquivos ao renderizador por código. Não use gerador externo nem trate uma imagem achatada como fonte editável. Separe autoria do asset, integração e validação final.

## Tipografia

1. Identifique a família e o peso quando houver evidência. Procure primeiro o arquivo exato e confirme direitos de uso e, se for o caso, de distribuição antes de incorporá-lo. Guarde fonte, versão/peso e licença no manifesto. Não use fonte encontrada apenas pelo nome ou por aparência presumida.
2. Quando o arquivo exato não estiver disponível ou autorizado, desenhe aqui os glifos ou a composição. Se os direitos de adaptação não estiverem claros, crie tipografia display **original**, alinhada à direção visual, sem afirmar identidade nem converter contornos proprietários em um arquivo redistribuível.
3. Se só houver evidência para a frase observada ou a frase nova, entregue um **lockup SVG editável** com contornos vetoriais e mantenha o texto em metadados/receita para acessibilidade e revisão; não chame isso de fonte completa. Se o projeto exigir uma fonte reutilizável e houver autorização, entregue **OTF ou TTF** com o alfabeto e a cobertura combinados (caixa alta/baixa, números, pontuação e caracteres portugueses, incluindo acentos e cedilha), ajustes de espaçamento e kerning. Confira a lista de caracteres reais, não só o nome da família.
4. Compare em tamanho de uso: altura e largura dos glifos, peso/contraste do traço, linha de base, espaçamento, acentos, legibilidade, alinhamento e ritmo da revelação. Registre grafia exata, versão/hash do arquivo, caracteres testados e diferenças remanescentes. Não afirme correspondência exata nem cobertura do alfabeto sem a evidência correspondente. Não recorra silenciosamente à fonte padrão do motor.

## Ícones

1. Inventarie os ícones observáveis e o que os distingue: proporção, recorte da silhueta, volumes, material/reflexos, cor, contorno, posição e ação. Separe o que aparece do que precisa ser inferido.
2. Desenhe aqui as versões faltantes. Prefira **SVG editável** com `viewBox` explícita. Para arte complexa ou acabamento raster, use **PNG com fundo transparente** e resolução suficiente para o maior enquadramento; preserve camadas editáveis quando aplicável. Não recorte pixels da referência nem reproduza marca sem autorização.
3. Entregue o arquivo com nome/versão e âncora normalizada 0–1 (por exemplo, `[0.5, 1]` para centro inferior), dimensões, origem e licença. Valide silhueta e material lado a lado em escala e iluminação comparáveis, além de transparência, recorte, posição e movimento nos quadros de entrada, pico e saída.

Quando o modo local não aceitar fonte ou asset externo, ainda entregue o arquivo criado aqui; marque a integração como bloqueada até haver operador compatível. Não finja que o ícone ou a tipografia já saiu no vídeo por existir como arquivo.
