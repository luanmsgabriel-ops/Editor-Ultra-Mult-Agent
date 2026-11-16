# Calibração de projeção de um aparelho

`visual_fidelity.device_camera.fit_device_pose` recebe quatro cantos em pixels,
na ordem superior esquerdo, superior direito, inferior direito, inferior esquerdo.
Os pontos representam o retângulo externo extrapolado antes do arredondamento,
e não a tela interna. Informe `side="back"` para o verso; a ordem local de X é
invertida de forma explícita.

```python
from visual_fidelity.device_camera import fit_device_pose

fit = fit_device_pose(
    [[190,295], [440,319], [479,852], [210,873]],
    side="front", resolution=(720,1280),
    width=.78, height=1.634, depth=.0875,
    lens_mm=50, sensor_width_mm=36, max_error_px=12,
)
device_override = fit["device"]
camera_override = fit["camera"]
evidence = fit["evidence"]
```

O resultado segue a convenção do palco: X direita, Y cima, Z saindo da tela.
A câmera fica em `(0,0,camera_distance)` e olha para a origem. O ajuste resolve a
pose sob a lente fornecida, converte os eixos OpenCV/Blender, reprojeta os pontos
e registra o erro por canto. Rejeita geometrias degeneradas, dados não finitos,
pontos atrás da câmera e resíduos acima da tolerância definida.

Esses dados não provam a lente ou escala física do arquivo original. Registre o
quadro e como cada canto foi medido, mantenha os resíduos e revise vários frames.
Uma prova sintética confirma a convenção de coordenadas, sem confirmar fidelidade
ao vídeo. Câmeras de planos distintos devem ser ajustadas separadamente.

Testes dirigidos em `tests/test_device_camera.py` usam um projetor pinhole próprio
em coordenadas Blender para verificar frente/verso, rotações e resolução vertical
e horizontal, sem reutilizar a função de reprojeção interna.
