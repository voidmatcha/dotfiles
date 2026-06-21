# Video and podcast evidence

Use for public video metadata, subtitles, and best-effort comments.

## YouTube / Bilibili with yt-dlp

```bash
yt-dlp --dump-json "URL"
yt-dlp --write-sub --write-auto-sub --sub-lang "zh-Hans,zh,en" --skip-download -o "/tmp/%(id)s" "URL"
yt-dlp --dump-json "ytsearch5:query"
```

Then inspect generated `/tmp/*.vtt` or JSON files. Manual subtitles are more reliable than auto-generated subtitles.

## Bilibili CLI

```bash
bili search "query" --type video -n 5
bili hot -n 10
bili rank -n 10
```

Some regions require cookies. If blocked, report the block instead of inferring.

## Podcasts

Use installed transcript helpers only when available, write output to `/tmp`, and cite the episode URL plus transcript limitations.
