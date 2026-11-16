# Validação da biblioteca de templates

Registro de 16 de novembro de 2026 para a camada `editorial_engine.templates` e sua integração com o pedido de direção contextual.

## Resultado técnico

```sh
python -m pytest -q tests extensions
```

Resultado: **473 testes e 49 subtestes aprovados**, sem falhas ou skips, em 62,62 segundos. A suíte inclui 20 testes novos de biblioteca e direção. Os avisos existentes tratam de depreciações em AnyIO/Pytest e Pillow.

As regressões novas conferem preservação dos arquivos de origem, inventário completo, alteração de bytes, arquivos ausentes ou extras, portabilidade por caminhos relativos, proibição de saída dentro da fonte, colisões, parâmetros desconhecidos, tipos e limites. Verificam também JSON Pointer, escaping de texto HTML, substituições simultâneas, cores HEX, inputs com hashes explícitos e bloqueio de uma entrada de referência sem projeto.

O inventário usa ordenação consistente por caminho, inclusive para nomes como `licenses.json` e `licenses/arquivo.txt`. A consulta resumida compartilha requisitos e limitações repetidos por referências explícitas; o teste confere sua resolução integral e exige o detalhe completo antes da autoria.

O teste de direção usa uma biblioteca real de arquivos de fixture. Ela entra no pedido com hashes e requisitos, sem modificar o catálogo de efeitos nativos, as capacidades ou a análise. Usar um ID de template como efeito pronto é rejeitado pelo planner. Modificar um arquivo depois do cadastro bloqueia o próximo pedido de direção.

## O que os testes não certificam

O comando de instanciação copia e personaliza arquivos. Ele não executa scripts recebidos, HyperFrames, um navegador ou outro renderizador, nem verifica a aparência do resultado. A entrada de mídia comprova os bytes copiados; duração, FPS, canais, alpha, adequação ao roteiro e rastreamento precisam da etapa de mídia/render.

A biblioteca mantém os estados `catalogued`, `instantiated_not_rendered`, demonstração fornecida e aprovação pendente separados. A demonstração de origem nunca recebe a validação de uma nova variante. O contrato de saída de um template é uma declaração até a inspeção dos arquivos realmente produzidos.

## Prova da coleção privada

A integração foi exercitada com uma coleção privada de 98 entradas: três composições HTML/GSAP e 95 estilos legados. Os 19 arquivos ZIP da distribuição legada conferiram com os hashes declarados. As fontes e as demonstrações permanecem fora do Git.

A verificação completa aprovou três pacotes ativos, com 963 arquivos e 1.450 bindings. Na prova de instanciação de um projeto real, quatro textos e uma cor de destaque alteraram exatamente dois JSONs. Os 931 arquivos de origem e as 55 fontes permaneceram iguais por hash; ritmo, movimento, transições, áudio e overrides de paleta por cena foram preservados. A consulta da coleção passou de 707.730 para 185.765 bytes em JSON compacto, com todos os requisitos e limites preservados, redução de 73,75%.

Foram inspecionados os metadados dos 95 MP4 fornecidos e amostras decodificadas. Isso não representa playback contínuo ou escuta. As duas composições de cinema exigem o vídeo de base ausente no pacote. A entrada VFX sem projeto editável permanece `reference_only`. As referências a mídia e caches externos dos projetos legados exigem novos vínculos explícitos.

Uma tentativa de iniciar o Chromium local falhou por restrição de socket do ambiente. Não houve renderização nova desses templates nem tentativa de contornar essa restrição. A prova de personalização do HTML verifica textos, paleta, preservação de máscaras e tempos, com sintaxe JavaScript conferida; a revisão visual da variante permanece pendente.

Consulte [template-library.md](template-library.md) para os comandos e [motion-integration.md](motion-integration.md) para importar uma sequência realmente renderizada como `motion-layer/1`.
