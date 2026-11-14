# Mapa acústico local

Ferramenta de apoio à escuta e à marcação de efeitos e cortes. Requer Python 3.10+, NumPy, FFmpeg e ffprobe no PATH. O arquivo de entrada pode ser um vídeo com áudio ou uma faixa de áudio local.

```sh
python mapear_audio.py referencia.mp4 --saida analise-audio
python mapear_audio.py referencia.mp4 --saida analise-audio-2 --faixa 1 --separacao-ms 85
python -m unittest -v test_mapear_audio
```

| Saída | Conteúdo |
| --- | --- |
| ataques.csv | Candidatos derivados de picos do fluxo espectral logarítmico positivo em grave (35–180 Hz), médio (180 Hz–2 kHz) e agudo (2–10 kHz). As intensidades são relativas à análise. |
| curva-rms.csv | Nível RMS em dBFS, com janela centrada de 400 ms e medições a cada 50 ms. |
| metadados.json | Relógio, faixa, taxas, janelas e timestamps informativos de origem. |

A análise converte a faixa para PCM estéreo a 48 kHz. A FFT tem janela centrada de 1024 amostras (21,33 ms) e passo de 240 (5 ms). O fluxo usa a maior magnitude entre os canais para preservar sinais em oposição de fase. O tempo impresso é relativo à primeira amostra do PCM decodificado. Some o deslocamento da edição para usar os marcadores na timeline. Verifique PTS descontínuos, deslocamento A/V, transições, listas de edição e sample rates em projetos com relógios diferentes.

O passo de 5 ms descreve a malha de análise. O momento perceptível depende do som e da janela. As bandas e os limiares são pontos de partida e picos próximos em bandas distintas podem representar o mesmo evento. Antes de aplicar qualquer corte, confirme ataque, batida, primeiro tempo do compasso e função do gesto por escuta e revisão da imagem. RMS em dBFS indica energia e responde a transientes sem usar a ponderação do loudness. Para LUFS e true peak, use medição compatível com o perfil da entrega.
