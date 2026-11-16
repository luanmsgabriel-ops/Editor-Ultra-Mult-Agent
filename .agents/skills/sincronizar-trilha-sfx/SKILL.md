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

## Biblioteca original ElevenLabs

- Para consultar o lote original, leia `assets/sfx/elevenlabs/catalog.json` e `docs/ElevenLabs-SFX.md`. O manifesto contém gerações, prompts, duração e custo observados; não contém bytes MP3 nem autorização editorial.
- **Nunca** tratar `generated_pending_audio_export` ou `awaiting_manual_audio_export` como efeito elegível para edição/render. Consultar o Drive e conferir IDs, duração por ffprobe e SHA-256 da cópia local antes de propor um ativo.
- Se os MP3 forem exportados, usar `python -m audiovisual.elevenlabs_sfx inspect` e `stage` com os caminhos documentados. Nenhum staging aprova licença, nem altera o motor de política.
- Na leitura de referência, identificar evento visual, começo da animação, ponto de máxima velocidade e instante de impacto. Recomendar efeitos por função acústica e testar posicionamento em amostras, nunca somente pelo rótulo do template.
- Separar camadas `whoosh`, `hit`, `riser`, `foley` na timeline e anotar a origem independente de cada uma. Evitar som excessivo que encubra voz; fazer escuta A/B e medir o ataque/cauda antes da aprovação.
