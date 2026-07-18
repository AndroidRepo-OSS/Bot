# Banner asset inventory

Bundled assets let `androidrepo_bot.media` render banners consistently and
fall back safely when remote NASA artwork is unavailable. Do not replace an
asset without updating its source, purpose, and license information here.

| File | Purpose | Source or license |
| --- | --- | --- |
| `android-head_flat.svg` | Original Android robot-head artwork | [Android brand guidelines](https://developer.android.com/distribute/marketing-tools/brand-guidelines) |
| `android-head_flat.png` | Raster copy consumed by Pillow | [Android brand guidelines](https://developer.android.com/distribute/marketing-tools/brand-guidelines) |
| `Figtree.ttf` | Variable font used by the renderer | SIL Open Font License |
| `Figtree-OFL.txt` | Complete Figtree license text | Bundled with the font |
| `black-hole-fallback.webp` | Offline background when remote artwork cannot be used | Generated with OpenAI for this repository |

## Attribution requirements

The Android robot is reproduced from work created and shared by Google and used
according to the Creative Commons 3.0 Attribution License terms referenced by
the Android brand guidelines. The renderer includes the required attribution
in every output image.

Figtree is distributed by Google Fonts under the SIL Open Font License. Keep
`Figtree-OFL.txt` with every redistributed copy of the font.

The fallback artwork contains no text or third-party logos. It is used when
NASA artwork is disabled, unavailable, invalid, or unsupported.
