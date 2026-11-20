# Design selection experiment

Status: prototype, **not promoted** to the installed skill. No image-specific color values, filenames, hue quotas or neutral/accent slot counts enter selection. Mode is chosen by the caller.

Candidate generation currently uses Pillow median cut (128 content / 256 UI candidates), **not Celebi**. This isolates the selection experiment; replacing the quantizer is a separate comparison. Candidates are snapped to sampled sRGB colors.

Content selection greedily maximizes weighted perceptual coverage in Lab: 50% pixel population, 50% chroma/local-contrast/neighborhood-supported interest, normalized by continuous hue density. It penalizes near duplicates. UI uses a tighter distance scale and repeated-color support, with an automatic cap of 16. Neither is a semantic vision model. Eight content colors is a budget, not a promise that eight meaningful colors exist.

## Run

Use an isolated Python 3.13 environment with `experiments/requirements.txt`. Nothing changes the normal dependencies.

```sh
python experiments/evaluate.py --output-root /path/to/existing/output
python experiments/evaluate.py --output-root /path/to/existing/output --extra-image /path/to/local.png
python experiments/design_palette.py /path/to/local.png --mode content --output-root /path/to/existing/output
```

The evaluator compares equal-sized palettes and repeats extraction after an 80% Lanczos resize. Reported Delta E is Lab Euclidean distance with greedy one-to-one matching, **not optimal assignment**, and is a diagnostic rather than a quality score. These five images are a development set, not an independent validation set. Colors were assessed on every image, with the same parameters per mode.

## Observations

- Cat: yellow/red now coexist with beige, green and dark neutrals.
- Portrait: content colors and smaller green/yellow accents survive.
- Landscape: flower colors are still missed; some close green/blue samples remain.
- Illustration: main colors survive, but edge/intermediate colors occupy extra slots.
- UI: new extraction loses some small accent colors and overselects grays; existing UI mode is preferable.
- Resize stability is inadequate on several examples; do not claim universal quality from this set.

Next acceptance gates: retain small coherent accents across unrelated images; eliminate antialiasing-derived candidates; avoid repeated shades; stabilize selection under resize/compression. Use unseen examples before promoting a replacement. Keep current UI extraction until a separate flat-region/repeated-color detector beats it.

Photo of the cat and its previews are **not included in this repository**. They remain local evaluation artifacts.

| Case | Mean resize Delta E76 | Maximum |
| --- | ---: | ---: |
| landscape | 6.84 | 45.25 |
| portrait | 1.88 | 10.37 |
| illustration | 8.6 | 58.2 |
| interface | 2.79 | 23.58 |
| cat | 10.13 | 56.37 |
