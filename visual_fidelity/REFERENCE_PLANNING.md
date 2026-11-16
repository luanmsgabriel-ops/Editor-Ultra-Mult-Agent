# Música, conteúdo e movimento antes do render

O caso330494V1 foi rejeitado por ritmo e falta de imagens complementares. Uma máscara correta com a fotografia errada não reproduz a cena. Uma troca de foto em intervalo fixo não está sincronizada só porque existe música no export.

Para medir a referência e aplicar os tempos na timeline, use [REFERENCE_CADENCE.md](REFERENCE_CADENCE.md).

## Fluxo obrigatório da adaptação

1. O editor analisa a referência por plano e por camada. Para cada abertura de máscara, registrar conteúdo visível, direção, enquadramento, duração, papel e evidência por quadro. Esta análise é visual/semântica; o validador Python não entende sozinho o conteúdo de uma foto.
2. Classificar cada necessidade: quadro/crop do bruto; recorte com alpha; fotografia complementar gerada; sequência animada; geometria3D. Um novo ângulo, outro cenário ou objeto oculto não surge de ampliar o bruto. Imagem estática com crop animado permanece2D/2,5D, não filmagem nova ou reconstrução3D.
3. Criar um `asset_plan` com slots, intervalos, assets, evidência e quantidade mínima de quadros vinculados. Gerar imagens faltantes pela ferramenta disponível, com referências de identidade, área útil para crop, luz, prompt/proveniência e revisão. Se faltar uma sequência com movimento próprio, marcar como pendente em vez de usar um fundo vazio silenciosamente.
4. Analisar a faixa realmente usada (`music_sync.analyze_audio`): mesmo start, speed e duração. Separar transientes, retornos de energia, pulsação hipotética e pontos selecionados pelo editor. Não impor um BPM quando a evidência for ambígua; permitir cues revisados/manuais.
5. Marcar a função musical de cada ação: start, apex, reveal, cut ou resolve. A preparação pode começar antes do acento; a colisão, pico luminoso ou revelação chega ao acento. Usar `schedule_events` para preservar ordem, janelas e espaçamento. Não cortar automaticamente em todo pico.
6. Reprogramar geometria, imagens e gestos pelos eventos. Preservar fonte, máscara e viewport juntos. Registrar repetição/descarte de quadros. Proteger fala; não retimar diálogos apenas para satisfazer batida.
7. `geometric_video`1.1.0 exige o contrato antes de renderizar. Ele rejeita áudio sem mapa (salvo exceção editorial explícita), hash/offset/velocidade inconsistentes, eventos sem binding, assets ausentes/não consumidos e imagens geradas sem proveniência. O contrato confirma estrutura e consumo, não fidelidade semântica nem apreciação musical.
8. Revisar o MP4 final: áudio codificado e seu atraso, cortes visíveis, máscaras, picos, imagens efetivamente apresentadas e resolução. Medir erro por quadro separado da incerteza do detector. Guardar revisão, limites e aprovação do usuário separadamente.

## Bug de relógio corrigido

Não aplicar `atempo=1`. Os testes com impulsos mostraram redução/deslocamento no áudio mesmo em velocidade nominal unitária. `edited_audio_filter` é compartilhado pelo analisador e renderer e omite essa operação. Para outra velocidade, os cues são medidos no PCM depois da transformação, não apenas calculados dividindo tempos da origem.

## Manifesto mínimo

`music_sync`: hash do áudio, clock `{start,speed}`, events contendo `event_id`, `cue_time`, `frame`, `role`; cada frame correspondente declara `music_events`.

`asset_plan.slots`: `id`, `role`, `evidence`, `status:ready`, `asset_ids`, `interval:[start,end)`, `min_visible_frames`, `semantic_review`. Assets gerados declaram `origin:generated` e caminho de `provenance`.

Exemplo executável: `examples/reference_replays/330494_music_v2/`. Mídia, prompts, máscaras e mapas privados permanecem no pacote de entrega. A V1 fica preservada como regressão; nenhuma revisão recebe aprovação estética por passar testes.
