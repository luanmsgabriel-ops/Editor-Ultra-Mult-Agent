# Reaplicação de referência com assets preservados

A adaptação ClaraPT1 foi rejeitada porque o compositor genérico descartou relações da referência:3painéisviraram1cartão, sequência de vidro perdeuobjetos, tipografia virouapenasfontesgenéricas e closesviraramplanosabertos.

`reference_replay.py` oferece peças reutilizáveis para reaplicar a mesma composição:

- `SourceClock`: mapeia relógios por cena e falha se exceder a fonte. Não aplica loop/freeze sem declaração.
- `MatteFootage`: carrega RGB real e alpha por quadro. Transformação fica em tela final e não deve receber uma segunda câmera global por acidente.
- `decontaminate_matte_edge`: estende cores do interior na borda de recorte. Alpha é preservado; a suavização opcional de0,45px acontece no loader antes desse passo. Não é hairmatting neural.
- `compose_bound_layers`: compõe papéis em ordem explícita; ausência de uma camada obrigatória é erro.
- `camera_plane_homography` e `warp_rgba`: projetam textura/lettering pelo mesmo R/t/focal do cenário físico, com alpha premultiplicado.

Esta extensão usa motion_layers, orbit_type, light_sweep e type_layout do motor existente. Os atributos da referência — ativos, funções, ordem, escala, câmera e tempos — continuam obrigatórios no adaptador e no pacote congelado. A extensão não recupera automaticamente uma composição.

Exemplo real: `examples/reference_replays/329687_pt2/`. Mídia e pacote completo no Drive referenciado por profile.json. Não incluir vídeo/rostos/credenciais em Git.

Validação:7testes adicionais (relógio de fala/corte, ausência de loop, reprojeção de câmera, alpha semhalo preto, roles ausentes, ordem não destrutiva, correção estreita de cor de borda). Testes funcionais não equivalem à aprovação visual.
