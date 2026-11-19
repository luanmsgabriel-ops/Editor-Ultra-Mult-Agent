# Contrato de direção e aprendizado

Cada render recebe uma receita versionada, sem comandos de shell e sem mídia extraída da referência. Registre, para cada efeito:

- Identidade: ID do efeito, versão do motor, hash da referência e, se houver, do bruto. No modo autônomo, manifeste hashes, direitos e origem de todos os ativos autorais. Registre relógio e tamanho de entrada e saída.
- Evidência: intervalo `[início, fim)` em quadros e PTS, regiões/máscaras, observação, hipótese e confiança.
- Execução: ID e versão de operador existente, parâmetros com limites, arquivos autorizados, ordem de pilha, âncora no material de saída (bruto ou palco autoral), intervalo e mapeamento por evento (não por mera proporção das durações).
- Aceite: teste do operador ligado/desligado, critério de fidelidade da assinatura, regiões/quadros protegidos, preservação de relógio e áudio e comportamento se tracking, recorte ou cenário não permitirem.
- Prova depois do render: hash da receita consumida e do MP4, quais camadas saíram, números antes/depois, revisão visual e decisão.

Não use “sucesso” para uma execução que só escreveu o plano. Não aceite o recibo do produtor como verificação independente; coteje-o com o MP4 e o controle. Diferenças fora da máscara podem vir da compressão. Isole-as sem eliminar dados do relatório.

## Padrão reutilizável vs caso local

Uma receita pode ser **local** (ajustada para um vídeo), **candidata** (mesmo operador já parametrizado, ainda sem novo caso real), **reutilizável** (passou em outro bruto real não usado no ajuste) ou **rejeitada**. Salve o que não funcionou também, com métricas e cenário de falha. Quando a fonte exata não estiver disponível para uso, criar aqui no chat a solução tipográfica, sem fonte substituta silenciosa. Criar também os ícones que faltarem. Aplique o [protocolo de tipografia e ícones](tipografia-e-icones.md) e registre origem, direitos, formato, alcance e evidência de teste de cada asset. Não declarar que é a fonte original sem confirmação.

## Auditoria local

Requer Python 3.11+, NumPy, FFmpeg e FFprobe no PATH. Na pasta da skill:

```sh
python scripts/audit.py referencia.mp4 --expected-frames 404 --out referencia.json
python scripts/audit.py anterior.mp4 --compare novo.mp4 --same-edit-clock --expected-frames 240 --compare-expected-frames 240 --threshold 24 --min-pixels 100 --out regressao.json
```

Os números nos exemplos são ilustrativos; para novos vídeos, use as contagens verificadas, sem depender de executar mídia antiga. A segunda chamada é para dois renders do mesmo material de saída e relógio, não para a referência versus o vídeo novo. Um relatório sem erro comprova a auditoria, não a fidelidade estética. Use regiões explícitas e métricas locais para dar o veredito de cada camada.

Exemplo real de correção localizada: [receita C03](exemplo-c03.json). É uma receita de um adaptador local, não o contrato de todas as versões do motor.
