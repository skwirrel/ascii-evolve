#!/usr/bin/env python3
"""Evolve an ASCII line drawing to match the edges of a target image.

Pipeline:
  1. Target -> binary silhouette -> edge map (thin outline, dilated to stroke
     width), or with --lines the skeleton of an existing line drawing.
  2. Rasterise every candidate glyph at cell size with a monospace font.
  3. Blur both sides so a stroke "nearly" in the right place still scores, and
     compare blurred structure tensors so stroke orientation counts too.
  4. Greedy per-cell initialisation, coordinate-descent sweeps (optionally
     coarse to fine), then a stochastic hill-climb.  Error = coverage term
     + orientation term + ink penalty + flat per-cell cost (+ optional
     crowding penalty).
"""
import argparse, random, sys, time
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter, binary_dilation, binary_erosion, label

FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
         "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationMono-Regular.ttf",
         "/Library/Fonts/Menlo.ttc", "C:/Windows/Fonts/consola.ttf"]
LINE_CHARS = " .,'`-_:~/\\|()"          # strokes only: no letters, no < > ^

def drop_small(mask, min_px):
    """Remove connected regions (True) smaller than min_px."""
    lab, n = label(mask)
    if n == 0:
        return mask
    sizes = np.bincount(lab.ravel())
    keep = sizes >= min_px
    keep[0] = False
    return keep[lab]

def build_target(path, cols, cw, ch, thickness, sigma, smooth=0.0, min_region=0,
                 hair_smooth=0.0, hair_frac=0.0, scales=None, lines=False):
    im = Image.open(path).convert("L")
    W = cols * cw
    H = int(round(im.height / im.width * W / ch)) * ch
    rows = H // ch
    im = im.resize((W, H), Image.LANCZOS)
    fill = np.asarray(im) < 200                      # ink = True
    if min_region > 0:                               # kill specks and slits
        fill = ~drop_small(~fill, min_region)         # fill small white gaps
        fill = drop_small(fill, min_region)           # drop small ink bits
    if smooth > 0 or hair_smooth > 0:                # drop fine detail
        f = fill.astype(np.float32)
        lo = gaussian_filter(f, smooth) if smooth > 0 else f
        if hair_smooth > 0:
            hi = gaussian_filter(f, hair_smooth)
            ramp = np.clip((np.arange(H) / H - hair_frac) / 0.08, 0, 1)[:, None]  # 0 in hair, 1 below
            lo = hi * (1 - ramp) + lo * ramp
        fill = lo > 0.5
    def edges_of(mask):
        if lines:                                    # input is already line art
            from skimage.morphology import skeletonize
            e = skeletonize(mask)
        else:
            e = mask ^ binary_erosion(mask, iterations=1)
        if thickness > 1:
            e = binary_dilation(e, iterations=thickness - 1)
        return e
    if scales:                                       # scale-space persistence
        # keep the fine edge positions; weight each by how many coarse
        # scales still have an edge within ~sm px of it
        fine = edges_of(fill)
        acc = np.zeros(fill.shape, np.float32); wsum = 0.0
        f = fill.astype(np.float32)
        for sm, w in scales:
            m = fill if sm <= 0 else gaussian_filter(f, sm) > 0.5
            e = edges_of(m)
            if sm > 0:
                e = binary_dilation(e, iterations=int(max(1, sm)))
            acc += w * e; wsum += w
        edge_soft = fine * (acc / wsum)              # 1.0 = persists at every scale
        edge = fine
    else:
        edge = edges_of(fill)
        edge_soft = edge.astype(np.float32)
    target = gaussian_filter(edge_soft, sigma)
    return target, rows, edge, edge_soft

def tensor(img, sigma, dsig=1.0):
    """Blurred structure tensor channels (Jxx, Jyy, Jxy) of an image."""
    gx = gaussian_filter(img, dsig, order=(0, 1))
    gy = gaussian_filter(img, dsig, order=(1, 0))
    return (gaussian_filter(gx * gx, sigma), gaussian_filter(gy * gy, sigma),
            gaussian_filter(gx * gy, sigma))

def build_glyphs(chars, cw, ch, font):
    glyphs = {}
    for c in chars:
        img = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(img).text((0, 0), c, font=font, fill=255)
        glyphs[c] = np.asarray(img, dtype=np.float32) / 255.0
    return glyphs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--cols", type=int, default=56)
    ap.add_argument("--font", default=None, help="path to a monospace TTF (default: first of the usual DejaVu/Liberation/Menlo/Consolas paths that exists)")
    ap.add_argument("--font-size", type=int, default=20)
    ap.add_argument("--sigma", type=float, default=3.0, help="blur in px")
    ap.add_argument("--thickness", type=int, default=2, help="edge stroke px")
    ap.add_argument("--ink", type=float, default=0.03, help="penalty per unit ink")
    ap.add_argument("--iters", type=int, default=2000, help="hill-climb proposals after the sweeps")
    ap.add_argument("--sweeps", type=int, default=2, help="coordinate-descent passes")
    ap.add_argument("--chars", default=LINE_CHARS)
    ap.add_argument("--smooth", type=float, default=0.0, help="blur mask px before edges")
    ap.add_argument("--hair-smooth", type=float, default=0.0, help="stronger blur above hair-frac")
    ap.add_argument("--hair-frac", type=float, default=0.38, help="fraction of height treated as hair")
    ap.add_argument("--min-region", type=int, default=0, help="drop regions under N px")
    ap.add_argument("--scales", default="", help="smooth:weight pairs, e.g. 0:1,3:1,6:2,10:3")
    ap.add_argument("--sigma-schedule", default="", help="coarse-to-fine blurs for sweeps, e.g. 6,4,3")
    ap.add_argument("--lines", action="store_true", help="input is a line drawing: skeletonise strokes instead of taking silhouette edges")
    ap.add_argument("--orient", type=float, default=1.5, help="weight of stroke-orientation (structure tensor) term")
    ap.add_argument("--cell", type=float, default=0.005, help="flat cost per occupied cell")
    ap.add_argument("--crowd", type=float, default=0.0, help="penalty per inked neighbour pair")
    ap.add_argument("--cover", type=float, default=1.0, help="extra weight on pixels near an edge")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="evolved.txt")
    ap.add_argument("--png", default=None, help="also save render + target side by side")
    a = ap.parse_args()
    random.seed(a.seed)

    import os
    font_path = a.font or next((f for f in FONTS if os.path.exists(f)), None)
    if not font_path:
        sys.exit("no monospace font found; pass --font /path/to/Mono.ttf")
    font = ImageFont.truetype(font_path, a.font_size)
    asc, desc = font.getmetrics()
    ch = asc + desc
    cw = font.getlength("M")
    cw = int(round(cw))
    target, rows, edge, edge_soft = build_target(a.image, a.cols, cw, ch, a.thickness, a.sigma, a.smooth, a.min_region, a.hair_smooth, a.hair_frac,
                                     [(float(x.split(":")[0]), float(x.split(":")[1])) for x in a.scales.split(",") if x], a.lines)
    H, W = target.shape
    weight = np.where(target > 0.05, a.cover, 1.0).astype(np.float32)
    T_, W_ = [target], [weight]
    J_ = [None]; K_ = [1.0]   # target tensor channels and their scale factor
    def set_target(sg):
        T_[0] = gaussian_filter(edge_soft, sg)
        W_[0] = np.where(T_[0] > 0.05, a.cover, 1.0).astype(np.float32)
        if a.orient > 0:
            J_[0] = tensor(edge_soft, sg)
            K_[0] = float(T_[0].sum() / (J_[0][0].sum() + J_[0][1].sum() + 1e-9))
    glyphs = build_glyphs(a.chars, cw, ch, font)
    chars = list(a.chars)
    ink = {c: float(glyphs[c].sum()) / (cw * ch) for c in chars}
    grid = [[" "] * a.cols for _ in range(rows)]
    canvas = np.zeros((H, W), np.float32)

    def paste(r, c, ch_):
        canvas[r*ch:(r+1)*ch, c*cw:(c+1)*cw] = glyphs[ch_]

    def window(r, c):
        pad = int(3 * a.sigma)
        y0, y1 = max(0, r*ch - pad), min(H, (r+1)*ch + pad)
        x0, x1 = max(0, c*cw - pad), min(W, (c+1)*cw + pad)
        return y0, y1, x0, x1

    NEIGH = [(0, -1, 1.0), (0, 1, 1.0), (-1, 0, 0.5), (1, 0, 0.5),
             (-1, -1, 0.5), (-1, 1, 0.5), (1, -1, 0.5), (1, 1, 0.5)]

    def crowding(r, c):
        """Weighted count of inked neighbours of cell (r,c)."""
        n = 0.0
        for dr, dc, w in NEIGH:
            rr, cc = r + dr, c + dc
            if 0 <= rr < rows and 0 <= cc < a.cols and grid[rr][cc] != " ":
                n += w
        return n

    def local_err(r, c, ch_):
        """Error over the neighbourhood of cell (r,c) if it held ch_."""
        y0, y1, x0, x1 = window(r, c)
        old = grid[r][c]
        paste(r, c, ch_)
        win = canvas[y0:y1, x0:x1]
        blurred = gaussian_filter(win, a.sigma)
        err = float((W_[0][y0:y1, x0:x1] * (blurred - T_[0][y0:y1, x0:x1]) ** 2).sum())
        if a.orient > 0:
            jxx, jyy, jxy = tensor(win, a.sigma)
            txx, tyy, txy = (j[y0:y1, x0:x1] for j in J_[0])
            k = K_[0]
            err += a.orient * float(((k*jxx - k*txx) ** 2 + (k*jyy - k*tyy) ** 2
                                     + 2 * (k*jxy - k*txy) ** 2).sum())
        paste(r, c, old)
        crowd = a.crowd * cw * ch * crowding(r, c) if ch_ != " " else 0.0
        flat = a.cell * cw * ch if ch_ != " " else 0.0
        return err + a.ink * ink[ch_] * cw * ch + crowd + flat

    def total_err():
        blurred = gaussian_filter(canvas, a.sigma)
        e = float((W_[0] * (blurred - T_[0]) ** 2).sum())
        e += a.ink * cw * ch * sum(ink[x] for row in grid for x in row)
        e += a.cell * cw * ch * sum(1 for row in grid for x in row if x != " ")
        e += a.crowd * cw * ch * 0.5 * sum(crowding(r, c) for r in range(rows)
                                           for c in range(a.cols) if grid[r][c] != " ")
        return e

    t0 = time.time()
    schedule = [float(x) for x in a.sigma_schedule.split(",") if x] or [a.sigma] * a.sweeps
    # --- greedy init / coordinate descent sweeps, coarse to fine ---
    for sweep, sg in enumerate(schedule):
        a.sigma = sg
        set_target(sg)
        changed = 0
        for r in range(rows):
            for c in range(a.cols):
                best, best_e = grid[r][c], local_err(r, c, grid[r][c])
                for x in chars:
                    e = local_err(r, c, x)
                    if e < best_e - 1e-6:
                        best, best_e = x, e
                if best != grid[r][c]:
                    grid[r][c] = best; paste(r, c, best); changed += 1
        print(f"sweep {sweep}: {changed} cells changed, err={total_err():.1f}, {time.time()-t0:.0f}s", file=sys.stderr)

    a.sigma = schedule[-1]; set_target(a.sigma)
    # --- stochastic hill climb ---
    accepted = 0
    for it in range(a.iters):
        r, c = random.randrange(rows), random.randrange(a.cols)
        x = random.choice(chars)
        if x == grid[r][c]:
            continue
        if local_err(r, c, x) < local_err(r, c, grid[r][c]) - 1e-6:
            grid[r][c] = x; paste(r, c, x); accepted += 1
        if (it + 1) % 10000 == 0:
            print(f"iter {it+1}: accepted {accepted}, err={total_err():.1f}, {time.time()-t0:.0f}s", file=sys.stderr)

    text = "\n".join("".join(row).rstrip() for row in grid)
    with open(a.out, "w") as f:
        f.write(text + "\n")
    print(text)

    if a.png:
        side = np.concatenate([edge_soft, canvas], axis=1)
        Image.fromarray((side * 255).astype(np.uint8)).save(a.png)

if __name__ == "__main__":
    main()
