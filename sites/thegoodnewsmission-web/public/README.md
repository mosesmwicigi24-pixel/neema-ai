# Static assets

Files here are served from the site root — `public/logo.png` becomes `/logo.png`.

Put photographs, the church logo and any downloadable resources in this folder,
then reference them from the content files in `src/content/`.

Suggested layout:

```
public/
├─ logo.png
├─ gallery/       photos for the gallery page
├─ leadership/    portraits, referenced by `photo` in leadership.ts
└─ resources/     PDFs and downloads
```
