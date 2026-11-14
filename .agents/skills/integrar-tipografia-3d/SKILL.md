---
name: integrar-tipografia-3d
description: Classificar e integrar texto, logos e elementos por tela, superfície planar ou espaço 3D. Usar para letreiro preso no chão, rastreamento, oclusão, sombra, perspectiva e reprodução de tipografia de referência em vídeo.
---

1. Leia a seção 11 de `docs/Mapa-de-Pos-Producao.md`. Registre plano, fonte/timecode, composição e ação. Diferencie coordenadas de tela, homografia planar e objeto volumétrico.
2. Reúna evidência de trajetória, lente, paralaxe, escala, âncora, oclusor e luz. Teste proxy com âncora em quadros extremos. Rotação pura e baixa paralaxe exigem declarar incerteza ou testar um método planar/manual.
3. Identifique atributos dos glifos, peso, espaçamento, altura, cor e animação. Verifique direitos de fonte, mídias e modelos. Para letras volumétricas, mantenha parâmetros de extrusão, bevel, luz e material editáveis.
4. Para matchmove com câmera móvel, preserve plate original, separe tracks móveis, resolva câmera/objeto e chão/eixos. Compare reprojeção e drift perto da âncora com pontos independentes. Quando tratar distorção da plate, recomponha no mesmo espaço de lente.
5. Componha sombras, reflexos, holdouts, alpha e motion blur conforme o plano. Valide parallax, legibilidade, contato, continuidade e oclusões em playback e frames críticos.
6. Entregue teste de composição e versão final, cena ou código parametrizado, fontes e licenças aplicáveis, tempos e evidência. Uma cena sintética com câmera conhecida prova o render, enquanto matchmove real exige solve e validação com o vídeo de origem.
