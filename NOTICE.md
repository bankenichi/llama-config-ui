# Notice and source lineage

## Original project

Llama Config UI originated in:

- <https://github.com/bankenichi/llama-config-ui>
- Author and repository owner: `bankenichi`

The original Python server, generic `llama-args.txt` editor, profile handling,
HTML/CSS/JavaScript interface, and Homelab deployment assumptions remain in this
repository with their Git history. The Atomic interface extends that work; it does
not replace or obscure the original authorship.

## Atomic adaptation

The typed Atomic launcher adapter, managed process lifecycle, fork-specific starter
profiles, migration layer, tests, and Atomic UI panels were added for:

- <https://github.com/bankenichi/atomic-llama-cpp-turboquant>

The adaptation invokes `scripts/atomic-launcher.ps1` from that parent repository.
It depends on, but does not copy, the parent fork's inference implementations. The
parent fork records its llama.cpp, AtomicBot, PrismML, TurboQuant, and other source
lineage in its own `NOTICE.md` and development documentation.

Current CLI spelling and capability discovery follow the selected descendant of:

- <https://github.com/ggml-org/llama.cpp>

## Preservation

When moving or reusing the UI:

- preserve this notice and the repository Git history;
- distinguish the original generic UI from later Atomic-specific adaptations;
- retain source links when porting nontrivial behavior;
- do not imply that UI code authors wrote the inference implementations it
  configures.

This repository did not contain a standalone `LICENSE` file when the Atomic
adaptation was made. This notice records provenance and is not a substitute for a
license grant.
