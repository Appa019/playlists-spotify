# playlists-spotify

Ferramentas em Python para a minha conta do Spotify: sincronizar a biblioteca num SQLite, montar playlists a partir de uma lista exata de faixas e gerar aulas de música narradas para ouvir no carro.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # preencha as credenciais do app em developer.spotify.com
```

O app do Spotify roda em Development Mode, que exige Premium na conta dona do app.

## Uso

```bash
.venv/bin/python sync.py                          # biblioteca -> data/library.db
.venv/bin/python aula.py publish lessons/jazz.json
.venv/bin/python aula.py build lessons/jazz.json
.venv/bin/python -m unittest discover tests
```

## Aulas narradas

A API do Spotify não aceita upload de áudio. Por isso cada narração vira um episódio de podcast: o texto da aula passa por TTS (ElevenLabs via OpenRouter), o mp3 e o `feed.xml` vão para um repo público no GitHub Pages ([music-lessons-podcast](https://github.com/Appa019/music-lessons-podcast)) e o Spotify importa o feed. O `build` procura os episódios no show e monta a playlist alternando narração e faixas de exemplo.

- `publish` só paga TTS por narração nova ou editada (o nome do mp3 leva o hash do texto)
- `build` só roda depois que o Spotify importa os episódios, o que leva algumas horas, e recusa montar uma playlist pela metade
- Uma aula é um JSON em `lessons/`: `slug`, `title` e `segments`, cada segmento com `title`, `summary`, `narration` e `tracks` (`artist`, `title` e, se quiser fixar a gravação, `id`)
