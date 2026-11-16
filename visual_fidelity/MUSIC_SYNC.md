# Sincronização musical reutilizável — 1.0.1

`music_sync.py` vincula relógio musical, eventos de motion e relógios dos recortes.
Uma montagem não está sincronizada apenas porque áudio e vídeo duram o mesmo tempo.
O responsável deve escolher o acento que cada entrada, ápice, revelação ou corte acompanha.

## Uso

```python
from visual_fidelity.music_sync import analyze_audio, schedule_events, retime_binding_schedule
analysis = analyze_audio('mix.wav', duration=10, start=0, speed=1)
events = [dict(id='revelacao', role='reveal', target_time=3.67,
               max_shift=.12, cue_id='accent-1')]
selected = [dict(id='accent-1', time=3.67, strength=1, kind='energy_accent',
                 evidence='Ataque escolhido pela revisão musical do trecho')]
schedule = schedule_events(events, selected, fps=24, total_frames=240)
```

`analyze_audio` decodifica o trecho e a velocidade da trilha efetivamente usados.
Entrega `cues` com id, tempo relativo à saída, força relativa e banda; `pulse` contém
hipótese de periodicidade, score heurístico, alternativas e estado de ambiguidade.
Janelas FFT centralizadas de1024 amostras, passo240 a48kHz e refinamento de energia
em1ms localizam ataques. O máximo entre canais evita anular estéreo em oposição de fase.
Essas resoluções não são uma promessa de precisão perceptiva de1ms.

O score periódico não é probabilidade nem confirmação de BPM, compasso ou primeiro
tempo. SFX, gaguejos, voz, síncopes e subdivisões podem dominar a detecção. Não usar
todos os transientes como cortes: selecionar acentos, hierarquia e pausas segundo a
música. Cues `manual`/`energy_accent` usam o mesmo esquema e preservam `evidence`.

Cada cue contém `pre_rms_dbfs`, `post_rms_dbfs` e `energy_change_db`. As janelas
de energia são −80 a−15ms e+15 a+80ms, excluindo o ataque central. Um aumento de
pelo menos6dB, com ambas as janelas completas, recebe `suggested_priority=energy_return`;
os demais recebem `texture_attack`. Esse rótulo sugere uma volta sustentada de
energia; não confirma um downbeat. Cliques estreitos podem ser fortes sem elevar
a energia posterior. Silêncio usa piso numérico de−120dBFS e contexto cortado pela
borda do trecho aparece como `energy_context_complete=false`. A anotação não muda
os tempos dos cues nem decide automaticamente quais efeitos usar.

`schedule_events` usa programação dinâmica para a atribuição conjunta ordenada:

- `target_time`: intenção editorial no relógio final;
- `max_shift`: janela de busca em segundos, antes de quantizar;
- `min_gap_frames`: distância mínima do evento anterior, pelo menos1;
- `role`: `start`, `apex`, `reveal`, `cut` ou outro rótulo editorial;
- `cue_id`: fixa um cue previamente escolhido, quando fornecido.

O resultado registra tempo do cue, frame da saída, erro de quantização e deslocamento
editorial. A quantização mais próxima pode acrescentar até meio quadro à janela.
Conflitos, ordem inválida, IDs duplicados e eventos sem cue admissível causam erro;
o módulo nunca empurra silenciosamente um corte para longe do acento. Cues cujo
frame seria o fim exclusivo da saída não são admissíveis.

## Relógio único da trilha

`edited_audio_filter(start,speed,duration)` é compartilhado por análise e render.
Não aplicar `atempo=1`: em teste de cliques esparsos, essa operação deslocou ataques
17–22ms e encurtou5s para4,978667s. Velocidade unitária agora ignora o processador
WSOLA. Para outra velocidade, analisar o PCM realmente processado, pois o mapeamento
`start + time * speed` é apenas nominal. `clock.complete` sinaliza se há amostras
suficientes; o consumidor deve rejeitar ou resolver áudio curto explicitamente.
Fades e mix final exigem conferência adicional na exportação codificada.

## Reutilizar sem perder o recorte

`retime_binding_schedule(bindings,anchors,total_frames)` recebe anchors inteiros
`{output_frame,source_frame}` e copia todos os dados de cada binding juntos. O primeiro
anchor de saída é0; o último pode ser239 para240 amostras, ou240 como fronteira
exclusiva. Os índices de fonte devem crescer. A função registra
`retime_template_frame`, deixando explícitos quadros repetidos/omitidos.

Fonte, matte, foreground, viseira e crop devem viajar juntos. Nunca alterar apenas
o índice do vídeo enquanto a máscara permanece no relógio anterior. Máscaras cuja
animação depende da variável `frame` devem ser previamente resolvidas em geometria
estática por quadro. Falas, gestos protegidos e trechos sem máscara disponível não
podem ser acelerados automaticamente; marque restrições ou use apenas a camada
gráfica no relógio musical. A função não faz interpolação óptica nem beat-aware
time-stretch de voz.

## Validação e limites

Testes sintéticos cobrem ataque/offset, silêncio, estéreo em oposição, conflitos,
escolha global, FPS fracionário, filtro de áudio e conservação dos relógios das
máscaras. Rodar `PYTHONPATH=. python -m unittest discover -s tests -p test_music_sync.py`.
Medir a trilha da exportação e conferir os frames dos impactos na montagem final.
Ausência de audição confirmada deve aparecer no relatório. Um erro de quantização
pequeno não prova que o acento escolhido é musicalmente correto; aprovação estética
continua pendente até revisão audiovisual.

Fontes técnicas consultadas para distinguir onset e beat:
- https://librosa.org/doc/main/api/generated/librosa.onset.onset_detect.html
- https://librosa.org/doc/main/api/generated/librosa.beat.beat_track.html

O módulo usa implementação própria em NumPy/SciPy; não declara executar o tracker
Librosa nem recuperar uma batida verificada por audição.
