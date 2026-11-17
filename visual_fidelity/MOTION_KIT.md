# Motion Kit 0.9.0 — recursos reutilizáveis

## Movimento medido por elemento

A versão 0.9 conecta observações de posição, escala e rotação às curvas usadas
pelos renderers studio e geometric/cadence. `measured-element-motion` exige
relógio PTS, identidade de elemento, perfil de curvas, binding e cobertura.
Use `python -m visual_fidelity motion-profile --help` e leia
[MOTION_PROFILE.md](MOTION_PROFILE.md). Um zoom com centro fixo passa a ter
movimento de cantos auditável; atividade de luminância não é velocidade.

Manifestos 0.7 e 0.8 preservam suas capacidades originais. Nenhum deles pode
declarar a capacidade nova sem fixar 0.9. Evidência de execução continua
separada de revisão visual e aprovação do usuário.

## Palco de produto e oclusores geométricos

A versão0.8 acrescenta `device-screen-stage`, `measured-device-projection` e
`curved-metal-blades`. Os manifestos0.7 continuam válidos somente para suas seis
capacidades originais; uma técnica nova deve fixar0.8. A validação continua sem
certificar semelhança visual ou aprovação do usuário.

- `python -m visual_fidelity device-scene render recipe.json`: câmera e aparelho
  independentes, chassis/lentes em geometria, UV estável, cards filhos no espaço,
  tela preta/texturizada, materiais clay/matte/studio, PNG RGBA e projeções.
- `visual_fidelity.device_camera.fit_device_pose`: ajusta a projeção a quatro
  cantos medidos sob intrínsecos explicitamente assumidos. Não recupera de forma
  única a câmera original ou a escala física; devolve resíduos e proveniência.
- `python -m visual_fidelity blade-scene recipe.json`: lâminas metálicas curvas
  fechadas, iluminação, câmera e trajetórias por quadro. São oclusores próprios,
  separados do telefone e da tipografia.

Leia [device_scene.md](../docs/device_scene.md),
[device_camera.md](../docs/device_camera.md) e
[blade_scene.md](../docs/blade_scene.md). A geração sintética por provedor mantém
o contrato `prompt_export_only`; estes comandos executam render procedural local.


Este kit incorpora seis classes de defeito observadas na revisão de uma referência. O motor contém os algoritmos; o projeto contém palavras, fontes licenciadas, assets, medições e parâmetros. Ajustar um projeto não deve criar uma cópia divergente do algoritmo.

## Descobrir e executar

```bash
python -m visual_fidelity motion-kit list
python -m visual_fidelity motion-kit check caminho/motion-manifest.json
python -m visual_fidelity motion-kit sweep palavra-completa.png brilho.png --phase .5 --angle 76 --width .095 --intensity .55
python -m visual_fidelity motion-objects --help
```

Requisitos CPU: NumPy, Pillow, OpenCV e FFmpeg para vídeo; Blender 4.3.2/Cycles para objetos físicos. Consulte requirements.txt. Nenhum vídeo de referência, fonte derivada, PNG privado ou credencial deve ser enviado ao Git.

## Componentes

| Defeito que motivou o recurso | Implementação | Contrato reutilizável |
|---|---|---|
| Texto sobreposto sem circular o objeto | orbit_type.OrbitSpec / render_orbit_type / composite_orbit | Centro, raios, câmera, inclinação, fase, fonte e oclusor independentes. Projeção cilíndrica 2,5D, passes traseiro/frontal; não é uma malha extrudada recuperada. |
| Brilho chapado ou fora das letras | light_sweep.Sweep / light_sweep | Faixa em luz linear limitada ao alpha; intensidade, largura, direção e fase. Preserva vazios e transparência. Aplicar antes da oclusão e, preferencialmente, antes da projeção do texto. |
| Palavra com buracos permanentes | type_layout.LetteringLayer / compose_layers | Fonte/palavra completa por camada. Oclusão ocorre somente na composição. Contorno observado parcial não equivale a alfabeto ou palavra completa. |
| Letras igualmente espaçadas em arco | type_layout.glyph_metrics / layout_arc / render_arc | Avanços e kerning da fonte, tracking, raio e tangente. Para scripts unidos ou ligaturas complexas use lettering moldado completo. |
| Alvo plano, flecha sem autonomia | blender_motion_objects, modo target | Cilindros/aneis, flecha e cauda com parent; movimento interno independente. motion_layers.compose_group agrupa o passe com valor e legendas. |
| Abertura sem contorno metálico | blender_motion_objects, modo keyhole | Silhueta parametrizada, bevel, material ouro, luz móvel e abertura com máscara; preserve a imagem aprovada no interior. |

`motion_layers.Transform`, `transform_layer` e `compose_group` oferecem transformação comum de grupo após compor os filhos, com warp de alpha pré-multiplicado. Assim objeto, número e legendas se movem juntos sem destruir seus movimentos internos.

## Uso em um vídeo novo

1. Classifique cada elemento por movimento: tela, plano projetado ou malha 3D. Use o perfil correspondente; não chame zoom de PNG de câmera 3D.
2. Identifique fonte e desenho antes de animar. Separe a camada inteira de sua máscara de visibilidade. Registre o que foi observado, reconstruído ou inferido.
3. Fixe engine_version e required_features no manifesto. Ligue os adaptadores aos módulos acima. O verificador rejeita recursos omitidos, rotas divergentes e fragmentos declarados completos.
4. Ajuste parâmetros por tomada: geometria, fontes, cores e tempo são da referência. Nenhuma frase, nome, contagem ou frame específico está embutido nos algoritmos.
5. Teste primeiro um ciclo completo, incluindo passagem traseira/frontal, passagem do brilho, revelação da palavra coberta, movimento da flecha e reflexão do metal.
6. Exporte, decodifique e compare amostras críticas. Assista e escute ao intervalo inteiro quando houver reprodução; registre explicitamente se somente amostras foram inspecionadas.

## Critérios de regressão visual

- Órbita: letras mudam de perspectiva e tamanho; o objeto encobre o trecho traseiro; não há salto na fase nem brilho fora do alpha.
- Brilho: pico percorre a superfície; cor-base permanece legível; interior dos vazios fica transparente; nenhum retângulo ilumina o cenário.
- Camadas: mova a palavra frontal e confirme que a de trás continua inteira. Não preencha automaticamente pixels ocultos como se tivessem sido observados.
- Curva: verifique pares estreitos/largos, inclinação tangente e espaço entre palavras. Acertar o arco não identifica a fonte original.
- Grupo: valor e palavras herdam a mesma transformação; flecha se move separadamente; sombras/reflexos e espessura aparecem durante o movimento.
- Fechadura: abertura reconhecível em miniatura, imagem interna preservada, metal com regiões claras/escuras e reflexão que muda.

## Aprendizado e estado

Um teste automatizado aprova comportamento técnico, não semelhança. `implemented`, `tested` e `reviewed` não significam aprovação do usuário. A revisão da referência continua pendente até o usuário avaliar a nova exportação.

Registre cada novo defeito com timecode, causa, componente genérico, configuração local, teste de regressão e evidência exportada. Se um ajuste só existe no script privado, o aprendizado ainda não foi incorporado ao motor. Publique código/documentação no branch do motor, inclua a revisão no projeto e atualize este catálogo.

Fontes técnicas: [Pillow — métricas e kerning](https://pillow.readthedocs.io/en/stable/reference/ImageFont.html), [Blender 4.3 — Principled BSDF](https://docs.blender.org/manual/en/4.3/render/shader_nodes/shader/principled.html), [Adobe — CC Light Sweep](https://helpx.adobe.com/after-effects/desktop/apply-effects-and-animation-presets/list-of-effects/cycore-plugins.html). O efeito CPU implementa composição própria; não executa After Effects.
