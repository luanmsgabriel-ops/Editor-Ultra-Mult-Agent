# Biblioteca SFX original ElevenLabs — Lote 01 (20/200)

## Status auditado em 16/11/2026
- **Geração:** 20/20 concluídos, 0 falhas, um som por prompt.
- **Modelo:** `eleven_text_to_sound_v2`.
- **Flow:** `6vW2IdHZ022mvWvUMSoA` (ElevenLabs).
- **Créditos reais:** 20 × 16,665 = **333,3 créditos**.
- **Custo monetário registrado:** 20 × US$ 0,00303 = **US$ 0,0606**.
- **Duração:** 1–4 segundos por item.
- **Catálogo fonte:** `assets/sfx/elevenlabs/catalog.json`.
- **Pasta de destino existente:** `Banco Audiovisual/01 Áudio/Efeitos sonoros/ElevenLabs — SFX originais (IA)`, Drive ID `1alTWYCtwbpvN7ODtfs2-EF6TILR07yes`.
- **Mídias no Drive:** **não enviadas**. O conector de geração fornece link temporário de mídia, não a referência de arquivo exigida pelo upload do Google Drive. Esta limitação não pode ser ocultada. O usuário acessa os sons no projeto ElevenLabs e exporta os MP3.
- **Direitos:** aguardando verificação dos termos do plano antes de uso comercial.
- **Qualidade:** geração técnica concluída; revisão humana por escuta, clipping, timbre e adequação ao vídeo ainda pendente.

## Categorias
2 exemplos por grupo: `whoosh`, `impact`, `transition`, `typography`, `glitch`, `riser`, `ui`, `spatial`, `texture`, `cinematic`.

## Transferência e ingestão

1. Abrir o flow `6vW2IdHZ022mvWvUMSoA` na conta ElevenLabs que gerou os assets. Baixar cada MP3 diretamente do produto (não usar URL assinada expirada).
2. Renomear cada export com seu `filename` no `catalog.json` (`SFX-001_whoosh_AIRY_FAST.mp3` etc). Manter os originais sem alterações.
3. Colocar os 20 MP3 numa pasta de exportação e conferir:
   ```sh
   python -m audiovisual.elevenlabs_sfx inspect --catalog assets/sfx/elevenlabs/catalog.json --exports /caminho/mp3
   ```
4. Copiar arquivos para staging com hashes, sem reencodificação e com nomes compatíveis com o projeto:
   ```sh
   python -m audiovisual.elevenlabs_sfx stage --catalog assets/sfx/elevenlabs/catalog.json --exports /caminho/mp3 --assets assets/elevenlabs --output out/elevenlabs-staged.json
   ```
5. Fazer revisão de escuta A/B; confirmar licença efetiva e permissão de uso. Enviar MP3 à pasta do Drive indicada; registrar IDs reais de arquivo e metadados de licença. Nunca marcar `approved` sem verificação.
6. Reconstruir catálogo do Drive com `python -m audiovisual.drive_catalog --snapshot ... --local assets/ --output drive-catalog.json`. Seguir a política de elegibilidade em `extensions/editor_policy.py` e a skill `.agents/skills/sincronizar-trilha-sfx/SKILL.md` para timing por ataque do áudio.
7. Validar sincronização e mix: onset/ataque, frame da transição, ganho, ducking, pan, cauda, true peak, A/B e resultado de escuta humana.

## Garantias e limitações

O manifesto registra **o que realmente foi gerado**. Como os MP3 não estão no Drive, o motor **não deve considerá-los elegíveis** para ranking, render ou publicação. O importador só faz staging **depois** que os exports reais são fornecidos. O catálogo possui IDs de geração para localizar cada item sem depender de links de CDN temporários. A deteção de eventos visuais/efeitos de camadas não equivale a um clone sonoro exato da referência e precisa de avaliação separada.
