# Validação do portal planar — 16/11/2026

## Execução e integração

O produtor `bundled.planar_portal` foi exercitado pelo projeto persistente com
fontes reais separadas de base, inserção e oclusão. Uma referência vertical de
720 × 1280, com imagem horizontal central, foi decomposta em camadas declaradas.
A composição completa produziu 504 quadros a 30 fps, cobrindo 16,8 segundos.
As mídias, coordenadas, recibos e comparativos desse caso permanecem privados.

A inserção de referência foi recuperada de um quadro e animada por deformação 2D
guiada por cabeça e ombros medidos. Ela não foi recortada do próprio quadro de
destino e recolocada na mesma máscara. A fotografia preservada fora do portal
vem da referência; os pixels ocultos da base foram inferidos de quadros limpos.
Essa recomposição não demonstra recuperação do bruto original nem generalização
para outra pessoa. Uma segunda inserção com paleta azul/dourada permite verificar
a substituição do conteúdo usando a mesma geometria.

## Verificação automatizada

```bash
python -m pytest -q tests/test_planar_portal.py \
  tests/test_planar_portal_production.py tests/test_production.py \
  tests/test_clone_project.py
```

**56 testes passaram**, com um aviso de depreciação do plugin de testes do ambiente.
O conjunto cobre relógios, projeção, orientação, alpha, oclusão, geometria inválida,
fontes ocultas, hashes, arquivo alterado durante leitura, produção real e regressão
da fila de produção e do projeto. `git diff --check` não encontrou erros.

Entradas malformadas, inclusive FPS com denominador zero e geometria com tipo
incorreto, falham como erro local conhecido. Não são registradas como execução
externa de resultado desconhecido. JSON e hash do manifesto derivam dos mesmos
bytes. A saída conserva revisão visual, playback e aprovação do usuário pendentes.

## Memória e preservação dos pixels

O primeiro render integral expôs uso excessivo de memória. A tentativa local
interrompida foi conciliada como falha confirmada, sem resultado utilizável e sem
chamada de provider externo. O produtor passou a calcular warp e máscara na região
visível, compor em faixas de 64 linhas, limitar threads e evitar o buffering de
quadros futuros no encoder. A conversão RGB para YUV BT.709 é explícita.

Um probe com as três fontes reais, 96 quadros de 720 × 1280 e encoder ativo terminou
em 14,05 segundos. O pico conjunto de Python e processos filhos foi 210,17 MiB;
essa medição se refere ao probe, não ao render integral. Duas amostras reais de
camada permaneceram idênticas, byte a byte, antes e depois da otimização. A
composição por faixas também foi exata. Nos casos sintéticos gerais, diferenças
de arredondamento foram limitadas a um nível em oito bits.

## Limites perceptivos

Mãos recortadas por landmarks e cor ainda precisam de rotoscopia precisa.
Uma imagem animada não reproduz automaticamente as expressões e deformações de
um vídeo transformado. Regiões invisíveis, bordas sob dedos e cantos fora da tela
permanecem inferências. A fonte já contém glitches e sobreposições de mãos; sua
reprodução não é certificada pelo compositor.

O áudio pertence à timeline de acabamento e não é gerado pelo portal. Neste caso,
a faixa original foi reutilizada com padding explícito no fim. Validação de
amostras, duração e alinhamento não substitui escuta. Os resultados são prévias
técnicas; este documento não constitui aprovação estética ou do usuário.
