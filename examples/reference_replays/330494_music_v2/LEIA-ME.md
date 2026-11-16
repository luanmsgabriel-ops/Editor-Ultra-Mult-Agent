# Moto330494 — V2: ritmo e cenas complementares

A V1 foi rejeitada por não seguir o ritmo e repetir apenas crops do bruto/fundo vazio. Esta revisão aplica os ajustes ao motor reutilizável e renderiza novamente o vídeo vertical de10s,720×1280,24fps. Aprovação estética do usuário pendente.

## O que mudou

- Música:29eventos selecionados por análise de ataques/energia; quatro acentos principais nos quadros88,134,180,226. As transições têm início, ápice/revelação e resolução explícitos. A hipótese de BPM automático foi considerada ambígua e não foi usada como grade confiável.
- Relógio: analisador e renderer compartilham o filtro de trim/velocidade. `atempo=1` foi removido, pois o teste com impulsos encontrou deslocamento mesmo nessa configuração.
- Conteúdo: quatro fotografias complementares geradas — costa, floresta frontal, industrial em ângulo baixo e piloto/moto de costas no campo. O bruto continua fornecendo o sujeito móvel, gesto e viseira. A chapa limpa anterior sustenta a colagem sem uma terceira pessoa sobreposta.
- Motor: `geometric_video`1.1.0, `music_sync`1.0.1, `edit_contract`1.0.0. O contrato barra mapa musical incompatível, evento sem vínculo, asset planejado ausente/não consumido e geração sem proveniência. A análise semântica da referência é feita pelo editor; o validador não reconhece sozinho objetos em fotos.
- Persistência: componentes genéricos e adaptador no Git; mídia, máscaras, prompts, mapas, relatórios e instruções neste pacote. A V1 permanece preservada.

## Onde encaixa cada coisa

| Quadros [início,fim) | Composição e evento |
|---|---|
|0–11|Bruto limpo|
|11–77|Faixa atrás do piloto; imagens trocam nos cues11/23/34/46/57/69|
|77–88|X com três acentos77/80/84|
|88–130|Colagem de capacete ampliado + recorte sobre chapa limpa; inserts104/119|
|130–138|Preparação do ciano, pico134, alpha zero137; capacete protegido|
|138–180|Faixas horizontais e giratórias, industrial/coast/rear/forest|
|180–195|Tomada frontal na floresta com divisões verticais|
|195–215|Portal da viseira do bruto, revelação concentrada203, troca211|
|215–226|Detalhes nos cues215/219/222|
|226–234|Faixa de fechamento, troca230|
|234–240|Seis quadros finais limpos|

`timeline.json` contém todos os vínculos por quadro. `timeline-v1.json` é o molde congelado para retiming. Fonte e máscara viajam juntas; quadros repetidos/descartados ficam registrados em `retime_template_frame`. Sem fala nova. Música do teste anterior preservada em velocidade normal; esta entrega mantém o escopo de comparação privada.

## Reproduzir

Python3.12, FFmpeg com libx264 e bibliotecas do `requirements-lock.txt`.

```bash
pip install -r requirements-lock.txt
python code/build_timeline.py
python code/render.py
python code/compare.py
python code/validate.py
python code/audit_audio_sync.py
PYTHONPATH=engine python -m unittest discover -s tests -v
```

Os arquivos finais ficam em `output`. O comparativo usa `media/v1-review.mp4`, também incluído. Os relatórios de render guardam hashes dos inputs, manifesto, módulos realmente utilizados e MP4.

## Limites da revisão

As quatro novas tomadas são fotografias inferidas e animadas com crops/máscaras2D. Não são filmagens recuperadas, movimento próprio do piloto ou novas vistas3D calibradas. Modelo da moto e identidade visual são aproximações guiadas pela referência do bruto. A nitidez dos closes do bruto é limitada a720p.

O sincronismo foi verificado matematicamente no áudio codificado e por inspeção visual dos eventos; não houve confirmação auditiva perceptiva. As distâncias entre cue e quadro são quantização a24fps, não garantia de musicalidade nem de fidelidade100%. Consulte `analysis/encoded-audio-sync-v2.json`, `visual-review-v2.json` e `tests-v2.log`.

Pasta da revisão: https://drive.google.com/drive/folders/11-iMF3gBOBdxRS9uD6RPgFVusPeYr1Z5
