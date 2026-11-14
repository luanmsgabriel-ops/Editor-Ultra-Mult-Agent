---
name: sincronizar-trilha-sfx
description: Ler waveform, energia, ataques e compassos, fazer spotting, curadoria e mix de SFX em transições e gestos, e revisar sincronia no render. Usar para trilha desalinhada, sound design, Foley, whoosh, hit ou riser.
---

1. Use a seção 10 de `docs/Mapa-de-Pos-Producao.md`. Confirme versão da montagem, PTS/offset de áudio, frame rate e o movimento que precisa de pontuação.
2. Extraia PCM para análise. Separe RMS/energia de ataques por banda, batida, downbeat e frase. Guarde a origem, a precisão da ferramenta e a evidência da escuta.
3. Faça spotting com `docs/Spotting-SFX.csv`. Guarde o ritmo da faixa, o gesto, o frame de sequência e as amostras de áudio.
4. Compare uma prévia sem efeito e até duas propostas de áudio verificadas. Julgue o início e a crista do arquivo, não só seu limite. Conserve o ganho da fala, o arco musical, direção, timbre e cauda.
5. A âncora desejada é um instante na sequência. Para mesma taxa de áudio, posicione a entrada do SFX em âncora + offset pretendido − (ataque na fonte − início do recorte). Resolva resampling e latência antes das contas se as taxas divergirem.
6. Valide o arquivo decodificado com precisão densa nas emendas e em playback normal. Compare A/B em volume comparável, verifique mono, LUFS/true peak quando definidos, e identifique o que depende de escuta humana. Entregue marcações, proposta, arquivos e limites.
