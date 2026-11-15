# Movimento e captura de interface

Use esta referência nos momentos de animação em que o olhar precisa acompanhar uma mudança. O ritmo da cena decide os tempos finais.

- Defina posição inicial, destino e duração. Use entrada suave, saída acelerada ou aceleração seguida de desaceleração conforme a ação. Separe movimentos deliberadamente contínuos, como progresso e rotação.
- Use uma antecipação curta em trocas maiores e um pequeno excesso seguido de assentamento quando houver sensação de peso. Preserve a leitura e a intenção da referência.
- Escalone elementos subordinados quando isso ajudar a revelar a hierarquia. Um intervalo de 40 a 80 ms pode servir de ponto de partida em interfaces. Mantenha a ação secundária discreta e preserve luz, sombra e perspectiva entre planos.
- Revele um foco por vez. Em legendas, reserve tempo de leitura. Marque o quadro do gesto, clique ou impacto. Posicione o ataque do som com a régua de áudio e confira o volume com a voz junto.
- Audite antes de exportar. A velocidade constante pode ser intencional, e um salto entre planos pertence ao corte. Compare as curvas e assista à composição no ritmo original.

## Medir velocidade

O comando aceita quadros-chave desejados ou um relatório `*.anchors.json` do editor. No modo de quadros-chave, calcula a velocidade quadro a quadro em px/s para a interpolação informada. Os avisos rápidos são heurísticas. Por exemplo, um `ease-out` de entrada pode começar rápido de propósito. No modo de observação, calcula deslocamento médio entre amostras disponíveis. Em trechos esparsos a curva interna continua desconhecida. Os cortes ficam sem medida de velocidade.

Entrada mínima:

```json
{
  "fps": 30,
  "resolution": [1080, 1920],
  "tracks": [
    {
      "id": "entrada-do-card",
      "keyframes": [
        {"frame": 0, "x": 300, "y": 950, "ease": "ease-in-out"},
        {"frame": 18, "x": 540, "y": 950}
      ]
    }
  ]
}
```

Cada curva pertence ao segmento que parte daquela chave. Use `linear`, `ease-in`, `ease-out`, `ease-in-out` ou `[x1, y1, x2, y2]` para Bézier cúbica. Informe `normalized: true` quando x e y forem frações da tela, `cut_before: true` em chaves que abrem um plano e `continuous: true` para dispensar os avisos de partida e chegada em movimentos contínuos.

```sh
python -m visual_fidelity.motion_qa quadros-chave.json --output out/motion.json --csv out/motion.csv
python -m visual_fidelity.motion_qa out/reel.anchors.json --output out/motion-medicao.json
```

## Gravar a interface real

Configure no OBS a cena e a fonte de captura da janela do aplicativo que vai aparecer na gravação. Use a proporção prevista para a edição. Ative o WebSocket do OBS, instale `obsws-python` no ambiente opcional e defina `OBS_WEBSOCKET_PASSWORD` na sessão local quando houver autenticação. O adaptador consulta a cena em programa e confirma a fonte esperada. A interação com a interface acontece durante a captura. Depois da gravação, use o caminho retornado para importar a mídia no projeto e aplique zoom ou contorno aos elementos reais da tela.

```sh
python -m visual_fidelity.obs_capture inspect
python -m visual_fidelity.obs_capture start --scene Interface --require-source 'Janela do app'
python -m visual_fidelity.obs_capture stop
```

Para um OBS em endereço autorizado, passe `--host` e `--port` antes da operação. O caminho devolvido por `stop` pertence à máquina que gravou. O adaptador usa o [WebSocket oficial do OBS Studio](https://obsproject.com/kb/remote-control-guide) por meio do [cliente Python](https://github.com/onyx-and-iris/obsws-python).
