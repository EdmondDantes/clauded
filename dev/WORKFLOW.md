# Workflow

How work is done in this repository. Agreed with the owner; do not change
silently.

## Branches

Commit directly to `main`. This is a personal tool repository with no review
round, so a branch per change adds ceremony without adding a check. Feature
branches are allowed for work that is genuinely unfinished; name them
`feat/<topic>` or `fix/<topic>` and merge locally.

## Commits

Conventional Commits with a scope, the scope being the part of the tool:
`web`, `tools`, `server`, `skills`, `dev`.

```
feat(web): code window with syntax colouring
```

One commit per coherent change. Body in English (rule 17), imperative mood not
required.

## Push and releases

Push to `origin/main` on request, not automatically. No tags: the plugin is
consumed from the working tree or from a marketplace entry.

## Maps

`dev/design/clauded.map.yaml` is this project's own design map and is rebuilt
with `tools/build-map.py` whenever it changes. The generated `.map.html` is
committed next to it so it opens without a build step.
