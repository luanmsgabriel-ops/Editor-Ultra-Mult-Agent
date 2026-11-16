# Aplicação no bruto Flow 330494 — 10 segundos

O motor aplicou a linguagem de máscaras da referência329796 ao novo bruto
330494, em 720 × 1280, 24 fps, 240 quadros. Esta é uma adaptação ao formato
vertical e aos gestos do novo piloto, não a troca do arquivo sob máscaras antigas.

## Conteúdo visual

- Fotografia do piloto, moto, capacete e closes: novo vídeo enviado.
- Recorte do piloto: máscaras novas por quadro, com anotação e refinamento.
- Viseira: contorno novo, acompanhando a rotação do capacete; ampliado junto do vídeo.
- Fundo vazio: imagem gerada a partir do quadro96, removendo piloto e moto para a colagem.
- Código de faixas/X/gradiente/composição: geometric_replay1.0.1.
- Ligação de vídeos, crops, máscaras e recortes: geometric_video1.0.1.
- Nenhuma fotografia do vídeo de referência329796 aparece na nova edição.
- Áudio: primeiros10s do mix da referência, na velocidade original. Áudio bruto
  preservado no arquivo fonte, não sobreposto automaticamente. Uso de teste privado;
  não há verificação de licença pública da música.

## Encaixe e montagem

| Quadros [início,fim) | Efeito |
|---|---|
|0–12 | Apresentação limpa |
|12–52 | Faixa horizontal abre por trás do piloto |
|52–84 | Duas faixas diagonais em X à frente |
|84–104 | Close grande acima e piloto recortado à frente |
|104–108 | Pulso ciano pelo recorte do corpo |
|108–144 | Faixas horizontais em sentidos opostos |
|144–168 | Faixas giratórias |
|168–188 | Faixas verticais |
|188–216 | Portal dentro da viseira |
|216–228 | Cortes de detalhes do próprio bruto |
|228–240 | Faixa fecha e retorna ao plano original |

`timeline.json` registra a imagem, quadro de origem, crop e máscara de cada quadro.
O fluxo principal conserva o relógio do novo bruto; as inserções reutilizam detalhes
em relógios identificados. Closes são ampliações digitais, não novas vistas 3D.

## Reproduzir

Python3.12, FFmpeg com libx264, dependências em requirements-lock.txt.
Executar na raiz do projeto:

```bash
pip install -r requirements-lock.txt
python code/build_timeline.py
python code/render.py
PYTHONPATH=engine python -m unittest discover -s tests
```

O pacote inclui os vídeos, fundo gerado, máscaras, código, parâmetros, relatórios
 e prompts/proveniência. Os renders finais estão separados na mesma pasta da entrega.

Para adaptar a outro bruto, substituir os vínculos de mídia, refazer o recorte do
sujeito e ancorar novamente portais/superfícies. Não presumir que as coordenadas
atuais servem para outro piloto. O arquivo `assets/reference-motion.json` contém
apenas geometria/timing da referência anterior, sem pixels fotográficos.

## Revisão

Aprovação estética pendente do usuário. A nitidez dos closes é limitada pelo
bruto720p. Partes ocultas do cenário limpo são inferidas; não são recuperação
exata do ambiente. Veja os relatórios de máscaras, exportação e revisão para
os intervalos efetivamente conferidos. Testes de código não medem identidade visual.

Pacote completo e renders: https://drive.google.com/drive/folders/1wYeiImVXB2dVG_2hi1622S23iWt_yEd4
