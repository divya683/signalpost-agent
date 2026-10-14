# signalpost-lookup

Live Norwegian company lookup, straight from Brønnøysundregistrene's
official public API. Identity, latest financials, board/leadership, and
registered subunits, every fact tagged with the exact source URL and
retrieval time it came from.

Zero dependencies. Nothing installed beyond Node 18+.

## Use it

```bash
npx signalpost-lookup 923609016
```

Swap in any 9-digit Norwegian organisation number.

## Optional AI summary

Off by default. Supply your own Anthropic API key to get a one-paragraph
plain-English summary of the same cited facts (never adds new facts, never
replaces them):

```bash
npx signalpost-lookup 923609016 --llm-key sk-ant-...
# or
ANTHROPIC_API_KEY=sk-ant-... npx signalpost-lookup 923609016
```

## Part of a larger project

This CLI is a standalone reimplementation of one feature from
[signalpost-agent](https://github.com/divya683/signalpost-agent), a fuller
Norwegian company-research agent built for the Signalpost challenge. See
that repository for the full batch pipeline, external-footprint connectors,
and verified results.
