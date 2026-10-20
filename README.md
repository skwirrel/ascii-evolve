# ascii-evolve

Turn an image into hand-drawn-looking ASCII line art by optimisation.

Most image-to-ASCII tools map brightness to characters, which gives you a
wall of `#` and `=`. This one extracts the *lines* of the image and then
searches for the grid of stroke characters (`/ \ | _ ~ ( )` and friends)
whose rendered shape best matches them, so the result looks like someone
drew it with a keyboard rather than photocopied it.

```
   ,/~~~___                     ____________
   |` `\\_`\\____~~~~~~___~~~~~~''```___~/)/
   |     `\\_```                 _,~/'` _/'
   |       `\\                 ,/'     )/
   |,        `\_              |/     ,/'
   ||          \|            :|      ||
   |\__        _)             \\_    ||
  |/ `\~~___~~/'               `\\_  /'
 ,/                               `|/`
 |`                                |,
|/                                 |\
|`                                _|`
|           \~)~~,__       __~~|/~|/
\|           \| '' |\    ,|_'__|` (_
 `\           `\~~~~~|   |/~~~'    `\_
  )|                 |, ,|    _/     `\_
  '|     ,_          )| ||  _//        `\_
  '|     `\\_         |~/' ,/            \\
  '|        `\\__  _~~~\__/'              '\
  '|           `\~~~_~~~/                  '\
  '|                                        '|
   |                                    |,   )|
   |                                    ||    |
   |,                                   ||    ||
   ||                                   ||    )|
   '|                                   |'     |
    |,                                  |      |
    '|                                 |/     :|
     |,      ,                         |`     ||
     '|      \|                       |/      |'
      )|      \|                      |`     ,|
       |       \\_                   ,|      |'
       |,       `\\___    __         |/     |/
       ||         ||`~~~~~'||        '`    ,/
       )|         )|       ||             ,/
       :|         '|       ||            ,/
       :|          |       ||          _/'
       '|          |       |/        ,/'
       //          |      ,/         ||
      ||           |      |`         )|
      || ,,       ,|      \,          |
       `~|   ,_ __/`       \_   ,_ _|_/
         '~~~/'~''          `\~~/``~'
```

*"sitting cat outline" from Openclipart, 48 columns. Each example in
[`examples/`](examples/) is given at 48, 32 and 20 columns.*

```
                         :~___/~,
               ,~___            \,
     ________  (___\\           '\________
   ,/___~~___\\_  \|         ___~~|_______~\_
   ,/'      `\\_\_ \|  ___~~~'` _//|    ``\\_\_
 ,/`           `\'\_)~~'`     ,/'  \|       \\)\
|/              `\           ,/     \|       '\
|`      ,~~~~~~~~/\~_____    |`      |~,      ||
|      '\_|__       /'  `\   |      '\~/      ||
)|        ``~~~~____|    |`  \|               |'
 \(             /'``\~~~/'    \_             //
  `\__       _,/`              `\_        __/'
    ``~~~~~~~'                   `\~~~~~~~'
```

*"Bicycle" from Openclipart, 48 columns.*

```
          _  _                       ______
        _/~~~_\__,                 _/' |\\\_
     _//'  '/\\\\|_               ||_ ____'||
    ,/`    /\//  \||              |,/(_)\)|)|
   ,| ||  ______ '|\,            (\|`||__||:/|
   )| \_~//_|| || )/_             \|'/''`` /_/
  __|/\_\|//'`\/|,'|/_             | ,~~_ _ |__
 '|`\| `)|_   ,||/ |/||           ||'|~_)|' ``~\\__
  `\_| |__|\~~~~' )/ /`          ~~~~~~~~~~~~~~~'`
    `| `  ``      `,/'
     |   _~~__     \||
    _|\ /_~__\|_,: .(_____
    ||`'|'`___||`   ```~\~\___
   _)|__|_____|___|_______~~~'`
  '~'```````````````````
```

*"Rawr Dinosaur outline" from Openclipart at 32 and 20 columns.*

## Install

```
pip install -r requirements.txt
```

Needs a monospace TrueType font. DejaVu Sans Mono, Liberation Mono, Menlo
and Consolas are found automatically; pass `--font` for anything else.

## Use

A line drawing (black strokes on white), which is what the examples are:

```
python3 evolve.py sketch.png --lines --cols 48 --thickness 3 --ink 0.02 --cell 0.002
```

A filled shape such as a logo or silhouette, where the outline becomes the
drawing:

```
python3 evolve.py logo.png --cols 56 --out logo.txt --png compare.png
```

The result is printed and written to `--out`. With `--png` you also get the
edge map and the rendered result side by side, which is the quickest way to
see what the optimiser was aiming at.

## How it works

1. **Target.** With `--lines` the black strokes are skeletonised to
   one-pixel paths and thickened back to roughly the stroke width of the
   font. Otherwise the image is thresholded to a silhouette and its outline
   is used.
2. **Glyphs.** Every character in the alphabet is rasterised at cell size in
   the same font, so the comparison is between real pixels, not an
   approximation of what a `/` looks like.
3. **Score.** Both sides are Gaussian-blurred so a stroke a pixel or two off
   still earns credit. On top of the coverage difference, the blurred
   *structure tensor* of each side is compared, which encodes stroke
   direction and stops a `\` being chosen for a `/` edge. Ink is charged per
   pixel, and each occupied cell pays a flat cost, which keeps low-ink
   fillers like `_` and `'` from creeping in where a single `/` would do.
4. **Search.** A greedy per-cell pass, then coordinate-descent sweeps that
   re-evaluate every cell in the context of its neighbours, then a
   stochastic hill-climb. Each proposal is scored on a local window, so a
   48-column run takes well under a minute.

It began as "a genetic algorithm that evolves ASCII art" and in practice the
population and crossover added nothing the sweeps didn't do faster, so what
remains is plain hill-climbing. The name stuck.

## Options worth knowing

| Flag | Default | Effect |
|---|---|---|
| `--cols` | 56 | Width in characters. Height follows the image. A clean outline survives down to about 16 columns; busy subjects stop reading around 40. |
| `--chars` | `` .,'`-_:~/\|() `` | The alphabet. Removing a character you find jarring is the simplest way to change the look. |
| `--sigma` | 3 | Scoring blur in pixels. Larger is more tolerant of position and favours longer strokes. |
| `--orient` | 1.5 | Weight of the orientation term. 0 disables it. Higher starts adding `'` and `:` clutter. |
| `--ink` | 0.03 | Cost per inked pixel. |
| `--cell` | 0.005 | Flat cost per occupied cell. Doubling it starts eating real strokes. |
| `--thickness` | 2 | Target stroke width in pixels. 3 suits bold line drawings. |
| `--lines` | off | Treat the input as a line drawing. |
| `--smooth` | 0 | Blur the silhouette by this many pixels before taking edges, to drop fine detail. |
| `--hair-smooth`, `--hair-frac` | 0 | Stronger smoothing for the top fraction of the image, for subjects with a busy top and a calm bottom. A hack, but effective. |
| `--scales` | | Scale-space persistence weighting, e.g. `0:1,3:1,6:2,10:3`. Edges that survive coarse smoothing are weighted up. Helps when clutter is genuinely high-frequency. |
| `--sigma-schedule` | | Coarse-to-fine sweeps, e.g. `6,4,3`. |
| `--crowd` | 0 | Penalty per adjacent inked pair. Thins uniformly, so it tends to break strokes before it removes clutter; `--cell` usually does the job better. |

## Examples

Each SVG in `examples/` is rasterised with Inkscape and run at three widths:

```
inkscape examples/sitting-cat.svg --export-type=png --export-width=700 \
    --export-background=white --export-filename=examples/sitting-cat.png
python3 evolve.py examples/sitting-cat.png --lines --cols 48 --thickness 3 --ink 0.02 --cell 0.002
python3 evolve.py examples/sitting-cat.png --lines --cols 32 --thickness 3 --ink 0.02 --cell 0.002
python3 evolve.py examples/sitting-cat.png --lines --cols 20 --thickness 2 --ink 0.02 --cell 0.002
```

The dinosaur and bicycle use the same settings with a 600 pixel export.

All three drawings are from [Openclipart](https://openclipart.org/), whose
whole library is public domain (CC0). The SVG and the PNG the script was run
on are included for each.

| Example | Source | Author |
|---|---|---|
| `sitting-cat` | [sitting cat outline](https://openclipart.org/detail/28140/sitting-cat-outline) | themanwithoutsex |
| `dinosaur` | [Rawr Dinosaur outline](https://openclipart.org/detail/234370/rawr-dinosaur-outline) | Tavin |
| `bicycle` | [Bicycle](https://openclipart.org/detail/21320/bicycle) | PrinterKiller |

## Limits

The optimiser is faithful, not tasteful. It has no idea which lines matter,
so a busy region comes out busy unless you simplify the input first, and a
person drawing the same subject would leave more out. The best workflow is
to let the script lay down the geometry and then edit.

Small source images are a hard limit: once each character cell covers only a
couple of source pixels there is no more detail to find. Give it a few
hundred pixels across.

## Related work

- Xu, Zhang and Wong, *Structure-based ASCII Art*, SIGGRAPH 2010. The same
  goal with a proper shape-similarity metric and deformation; no public code.
- [DeepAA](https://github.com/OsciiArt/DeepAA): a convolutional network that
  picks glyphs for line drawings.
- [chafa](https://hpjansson.org/chafa/): fast per-cell glyph shape matching.
- Roger Alsing's evolved Mona Lisa and its descendants
  (`primitive`, `geometrize`): the same hill-climb-against-a-target idea
  with polygons instead of glyphs.

## Licence

MIT. See [LICENSE](LICENSE).
