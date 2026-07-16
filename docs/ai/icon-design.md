# Agent Icon Design Standard

This document defines how the `seed-agent` icon implements the current agent
icon family standard.

## Scope And Ownership

- Ordinary `seed-agent` icon work applies and validates this standard only in
  this repository. It does not require inspecting or modifying sibling repos.
- The values in this document remain fixed until the user explicitly requests
  a family-standard change.
- A dedicated family-standard change session owns synchronizing the revised
  rules and icon assets across all affected agent repositories.

## Canonical Assets

- Editable source: `docs/assets/icon.svg`
- Published runtime asset: `docs/assets/icon.png`

These are the only tracked icon files. Do not add a second PNG, repository-icon
copy, favicon copy, or another editable source. The separate logo and social
preview assets are compositions for different surfaces, not icon sources.

The Web UI uses `/static/icon.png`. The wheel build
includes the canonical PNG at that runtime path, while source-checkout serving
falls back to `docs/assets/`. Do not restore a tracked `favicon.svg` mirror.

The SVG is the source of truth. Do not regenerate the center mark with an image
model or edit a PNG as the canonical source.

## Reference Contract

- Public URL:
  `https://raw.githubusercontent.com/Team-Cyan/seed-agent/main/docs/assets/icon.png`
- DockerMan template: `deploy/unraid/seed-agent.xml`
- OCI image metadata: `Dockerfile`
- Compose OCI metadata: `deploy/docker-compose.example.yml`
- Web UI favicon and sidebar: `/static/icon.png`

All runtime and deployment consumers reference the transparent PNG. The SVG is
never used as the DockerMan or OCI icon URL.

## Shared Canvas And Background

- SVG design canvas: `256 x 256`
- Published PNG: `512 x 512`, RGBA
- Background: `<rect width="256" height="256" rx="56">`
- The rounded rectangle touches all four canvas edges. Do not add an inset or
  transparent padding around its straight edges.
- The four corner regions outside the rounded rectangle remain transparent.
- Gradient direction: top-left `(0, 0)` to bottom-right `(256, 256)`.
- Gradient stops:
  - `0`: `#22C55E`
  - `0.38`: `#2DD4BF`
  - `0.72`: `#38BDF8`
  - `1`: `#60A5FA`

Do not introduce per-repository gradient variants, shadows, gloss, outlines,
textures, or opaque corner backgrounds.

## Shared Foreground Geometry

- Foreground design frame: `140 x 140`
- Foreground bounds: `x=58..198`, `y=58..198`
- Foreground center: `(128, 128)`
- Primary foreground color: `#08111F`
- Highlight color: `#DFFCF7`

The visible subject may contain negative space, but its outer geometry must fit
the shared frame. Preserve comparable visual weight at 64 px and 256 px.

The `seed-agent` subject is a controller/core mark. Preserve that product
meaning when refining the foreground.

## Deterministic Export

Keep explicit `width="256" height="256" viewBox="0 0 256 256"` attributes on
the SVG root. Export at 2x device scale with a transparent browser background:

```sh
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --headless=new \
  --disable-gpu \
  --hide-scrollbars \
  --default-background-color=00000000 \
  --force-device-scale-factor=2 \
  --window-size=256,256 \
  --screenshot=<output.png> \
  file://<absolute-path-to-icon.svg>
```

## Validation Checklist

- SVG parses successfully.
- PNG is exactly `512 x 512` RGBA.
- All four corner pixels have alpha `0`.
- The opaque background reaches the midpoint of every canvas edge.
- The foreground bounds are `x=116..396`, `y=116..396` in the 512 px export.
- Background geometry and colors match the fixed values in this document.
- Any Unraid template or OCI icon references present in this repository point
  to the transparent PNG.
- Review this repository's icon at 64 px, 256 px, and 512 px before publishing.
