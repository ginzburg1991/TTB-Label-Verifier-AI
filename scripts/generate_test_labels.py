"""
Generate a realistic, varied set of sample label images for testing.

Why synthetic labels (and not scraped ones)?
  TTB's Public COLA Registry disallows automated access (robots.txt), and the
  real label artwork in it belongs to other companies, so it shouldn't be
  redistributed in a repo. Synthetic labels are reproducible, committable, and
  let us deliberately cover the cases that matter:

    - Multiple beverage types (distilled spirits, wine, malt beverage), each
      with its own mandatory fields and typography.
    - Compliance edge cases agents described: title-case warning heading,
      altered/missing warning, wrong ABV, brand casing/punctuation variants,
      proof-vs-ABV inconsistency.
    - "Bad photo" conditions Jenny flagged: rotation/angle, glare, low light,
      blur, and sensor noise -- to exercise OCR robustness and the
      image-quality flag.

Run:  python scripts/generate_test_labels.py
Output: sample_data/*.png  +  sample_data/sample_manifest.csv
        (manifest is also copied into frontend/ for the in-app download link)
"""

import csv
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sample_data"
FRONTEND = ROOT / "frontend"
OUT.mkdir(exist_ok=True)

CORRECT_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should "
    "not drink alcoholic beverages during pregnancy because of the risk of "
    "birth defects. (2) Consumption of alcoholic beverages impairs your "
    "ability to drive a car or operate machinery, and may cause health problems."
)
TITLECASE_WARNING = CORRECT_WARNING.replace("GOVERNMENT WARNING", "Government Warning")
ALTERED_WARNING = CORRECT_WARNING.replace("birth defects", "health issues")

W, H = 900, 1200

# Font resolution: try common paths per style, fall back to the default.
_FONT_PATHS = {
    ("sans", False): ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                       "/Library/Fonts/Arial.ttf", "C:\\Windows\\Fonts\\arial.ttf"],
    ("sans", True):  ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                       "/Library/Fonts/Arial Bold.ttf", "C:\\Windows\\Fonts\\arialbd.ttf"],
    ("serif", False):["/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                       "/Library/Fonts/Georgia.ttf", "C:\\Windows\\Fonts\\georgia.ttf"],
    ("serif", True): ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
                       "/Library/Fonts/Georgia Bold.ttf", "C:\\Windows\\Fonts\\georgiab.ttf"],
}


def font(size, family="sans", bold=False):
    for path in _FONT_PATHS.get((family, bold), []):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def wrap(draw, text, fnt, max_width):
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = (line + " " + w).strip()
        if draw.textlength(trial, font=fnt) <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def draw_warning(d, text, top, fnt, fill="#1a1a1a", heading_bold=True):
    """Render the warning with a bold (or regular) heading and regular body."""
    if not text:
        return
    head_font = font(fnt.size, bold=heading_bold)
    head, _, rest = text.partition(":")
    # First line: heading + start of body on the same line if it fits.
    panel_pad = 70
    x, y = panel_pad, top
    d.text((x, y), head + ":", font=head_font, fill=fill)
    head_w = d.textlength(head + ": ", font=head_font)
    body = rest.strip()
    body_lines = wrap(d, body, fnt, W - 2 * panel_pad - head_w)
    if body_lines:
        d.text((x + head_w, y), body_lines[0], font=fnt, fill=fill)
        y += fnt.size + 8
        remaining = " ".join(body_lines[1:])
        for line in wrap(d, remaining, fnt, W - 2 * panel_pad):
            d.text((x, y), line, font=fnt, fill=fill)
            y += fnt.size + 8


def render(spec):
    bg = spec.get("bg", "#f3efe4")
    ink = spec.get("ink", "#2a211a")
    sub = spec.get("sub", "#4a3d30")
    fam = spec.get("family", "sans")

    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, W - 20, H - 20], outline=spec.get("border", "#3a2f25"), width=4)

    cx, y = W // 2, 90
    d.text((cx, y), spec["brand"], font=font(56, fam, bold=True), fill=ink, anchor="mt")
    y += 92

    f_sub = font(30, fam)
    for line in wrap(d, spec["cls"], f_sub, W - 160):
        d.text((cx, y), line, font=f_sub, fill=sub, anchor="mt"); y += 42
    if spec.get("composition"):
        for line in wrap(d, spec["composition"], font(24, fam), W - 200):
            d.text((cx, y), line, font=font(24, fam), fill=sub, anchor="mt"); y += 32
    y += 28

    d.line([cx - 170, y, cx + 170, y], fill=spec.get("rule", "#7a6a55"), width=2)
    y += 46

    f_info = font(32, fam, bold=True)
    d.text((cx, y), spec["abv_line"], font=f_info, fill=ink, anchor="mt"); y += 52
    d.text((cx, y), spec["net"], font=f_info, fill=ink, anchor="mt"); y += 70

    f_addr = font(23, fam)
    for line in wrap(d, spec["address"], f_addr, W - 200):
        d.text((cx, y), line, font=f_addr, fill=sub, anchor="mt"); y += 32
    if spec.get("extra"):
        y += 6
        for line in wrap(d, spec["extra"], f_addr, W - 200):
            d.text((cx, y), line, font=f_addr, fill=sub, anchor="mt"); y += 32

    warning = spec["warning"]
    if warning:
        panel_top = H - 360
        d.rectangle([50, panel_top, W - 50, H - 60], fill="#ffffff",
                    outline="#b8a98e", width=2)
        draw_warning(d, warning, panel_top + 24, font(22, fam),
                     heading_bold=spec.get("heading_bold", True))
    return img


# ---------- photo-degradation effects (Pillow only) ----------

def add_glare(img, cx_frac, cy_frac, radius, strength):
    """Soft bright spot, as if light is reflecting off a bottle."""
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)
    cx, cy = int(img.width * cx_frac), int(img.height * cy_frac)
    md.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=strength)
    mask = mask.filter(ImageFilter.GaussianBlur(radius * 0.6))
    white = Image.new("RGB", img.size, (255, 255, 255))
    return Image.composite(white, img, mask)


def add_noise(img, sigma):
    noise = Image.effect_noise(img.size, sigma).convert("RGB")
    return Image.blend(img, noise, 0.18)


def degrade(img, ops):
    if "brightness" in ops:
        img = ImageEnhance.Brightness(img).enhance(ops["brightness"])
    if "contrast" in ops:
        img = ImageEnhance.Contrast(img).enhance(ops["contrast"])
    if "glare" in ops:
        img = add_glare(img, *ops["glare"])
    if "blur" in ops:
        img = img.filter(ImageFilter.GaussianBlur(ops["blur"]))
    if "noise" in ops:
        img = add_noise(img, ops["noise"])
    if "rotate" in ops:
        img = img.rotate(ops["rotate"], expand=True, fillcolor=(40, 40, 44),
                         resample=Image.BICUBIC)
    return img


# ---------- the test set ----------
# Each entry: render spec + filed application values + expected outcome note.
SAMPLES = [
    dict(file="01_spirits_correct.png",
         spec=dict(brand="OLD TOM DISTILLERY", cls="Kentucky Straight Bourbon Whiskey",
                   abv_line="45% Alc./Vol. (90 Proof)", net="750 mL",
                   address="Bottled by Old Tom Distillery, Bardstown, KY",
                   warning=CORRECT_WARNING, family="serif", bg="#f4ecd8"),
         filed=dict(brand_name="OLD TOM DISTILLERY", class_type="Kentucky Straight Bourbon Whiskey",
                    alcohol_content="45% Alc./Vol.", net_contents="750 mL", origin="Kentucky"),
         note="Clean pass; label says 'KY', filed says 'Kentucky' (abbreviation match)"),

    dict(file="02_spirits_titlecase_warning.png",
         spec=dict(brand="SILVER CREEK", cls="Tennessee Whiskey",
                   abv_line="40% Alc./Vol. (80 Proof)", net="750 mL",
                   address="Distilled & bottled in Lynchburg, TN",
                   warning=TITLECASE_WARNING, bg="#ece4d2"),
         filed=dict(brand_name="SILVER CREEK", class_type="Tennessee Whiskey",
                    alcohol_content="40% Alc./Vol.", net_contents="750 mL", origin="Tennessee"),
         note="Warning heading not in caps -> attention"),

    dict(file="03_spirits_wrong_abv.png",
         spec=dict(brand="HIGHLAND PEAK", cls="Single Malt Scotch Whisky",
                   abv_line="40% Alc./Vol. (80 Proof)", net="700 mL",
                   address="Product of Scotland", warning=CORRECT_WARNING,
                   family="serif", bg="#e7e0cf"),
         filed=dict(brand_name="HIGHLAND PEAK", class_type="Single Malt Scotch Whisky",
                    alcohol_content="43% Alc./Vol.", net_contents="700 mL",
                    origin="Product of Scotland"),
         note="Label ABV 40% vs filed 43% -> attention"),

    dict(file="04_spirits_brand_variant.png",
         spec=dict(brand="STONE'S THROW", cls="Small Batch Gin",
                   abv_line="47% Alc./Vol. (94 Proof)", net="750 mL",
                   address="Hand crafted in Portland, OR", warning=CORRECT_WARNING,
                   bg="#eef0ea"),
         filed=dict(brand_name="Stone's Throw", class_type="Small Batch Gin",
                    alcohol_content="47% Alc./Vol.", net_contents="750 mL", origin="Oregon"),
         note="Brand casing/punctuation variant -> should still match"),

    dict(file="05_rum_missing_warning.png",
         spec=dict(brand="RIVERBEND", cls="Spiced Rum",
                   composition="Rum with natural flavors added",
                   abv_line="35% Alc./Vol. (70 Proof)", net="750 mL",
                   address="Bottled by Riverbend Spirits, Miami, FL", warning="",
                   bg="#efe6d6"),
         filed=dict(brand_name="RIVERBEND", class_type="Spiced Rum",
                    alcohol_content="35% Alc./Vol.", net_contents="750 mL", origin="Florida"),
         note="No warning on label -> attention"),

    dict(file="06_spirits_proof_inconsistent.png",
         spec=dict(brand="COPPER FOX", cls="Straight Rye Whiskey",
                   abv_line="45% Alc./Vol. (80 Proof)", net="750 mL",
                   address="Sperryville, VA", warning=CORRECT_WARNING, family="serif",
                   bg="#f0e8d6"),
         filed=dict(brand_name="COPPER FOX", class_type="Straight Rye Whiskey",
                    alcohol_content="45% Alc./Vol.", net_contents="750 mL", origin="Virginia"),
         note="45% ABV but 80 proof (should be 90) -> review"),

    dict(file="07_wine_glare.png",
         spec=dict(brand="VALLEY FOG", cls="Pinot Noir",
                   abv_line="13.5% Alc./Vol.", net="750 mL",
                   address="Vinted & bottled by Valley Fog Cellars, Sonoma, CA",
                   extra="Contains Sulfites", warning=CORRECT_WARNING,
                   family="serif", bg="#f6f1e7"),
         filed=dict(brand_name="VALLEY FOG", class_type="Pinot Noir",
                    alcohol_content="13.5% Alc./Vol.", net_contents="750 mL", origin="California"),
         degrade=dict(glare=(0.68, 0.30, 190, 130)),
         note="Wine with a glare/reflection -> reads correctly (OCR robustness)"),

    dict(file="08_wine_lowlight_blur.png",
         spec=dict(brand="CEDAR & SALT", cls="Chardonnay",
                   abv_line="14% Alc./Vol.", net="750 mL",
                   address="Produced & bottled by Cedar & Salt, Walla Walla, WA",
                   extra="Contains Sulfites", warning=CORRECT_WARNING,
                   family="serif", bg="#eef0ea"),
         filed=dict(brand_name="CEDAR AND SALT", class_type="Chardonnay",
                    alcohol_content="14% Alc./Vol.", net_contents="750 mL", origin="Washington"),
         degrade=dict(brightness=0.62, blur=1.1),
         note="Low light + blur; brand filed as 'AND' vs '&' -> tests fuzzy match"),

    dict(file="09_beer_correct_noise.png",
         spec=dict(brand="IRON LANTERN", cls="India Pale Ale",
                   abv_line="6.8% Alc./Vol.", net="12 FL OZ",
                   address="Brewed & bottled by Iron Lantern Brewing, Asheville, NC",
                   warning=CORRECT_WARNING, bg="#e9e2d0"),
         filed=dict(brand_name="IRON LANTERN", class_type="India Pale Ale",
                    alcohol_content="6.8% Alc./Vol.", net_contents="12 fl oz", origin="North Carolina"),
         degrade=dict(rotate=2, noise=12),
         note="Malt beverage, slight rotation + sensor noise -> reads correctly"),

    dict(file="10_spirits_blurry_readable.png",
         spec=dict(brand="MOONLIT", cls="Vodka",
                   abv_line="40% Alc./Vol. (80 Proof)", net="750 mL",
                   address="Distilled from grain, Austin, TX", warning=CORRECT_WARNING,
                   bg="#eceae6"),
         filed=dict(brand_name="MOONLIT", class_type="Vodka",
                    alcohol_content="40% Alc./Vol.", net_contents="750 mL", origin="Texas"),
         degrade=dict(blur=2.6, brightness=0.55),
         note="Blurry/dark but now readable after enhancement; minor OCR slips the reviewer can confirm"),

    dict(file="11_tequila_imported.png",
         spec=dict(brand="CASA AZULEJO", cls="100% de Agave Tequila Reposado",
                   abv_line="40% Alc./Vol. (80 Proof)", net="750 mL",
                   address="Hecho en Mexico / Product of Mexico",
                   warning=CORRECT_WARNING, family="serif", bg="#eef0ea"),
         filed=dict(brand_name="CASA AZULEJO", class_type="100% de Agave Tequila Reposado",
                    alcohol_content="40% Alc./Vol.", net_contents="750 mL",
                    origin="Product of Mexico"),
         note="Imported product: a single COUNTRY origin ('Product of Mexico'), no US state -> clean"),

    dict(file="12_spirits_warning_not_bold.png",
         spec=dict(brand="GRAY HARBOR", cls="Straight Bourbon Whiskey",
                   abv_line="46% Alc./Vol. (92 Proof)", net="750 mL",
                   address="Bottled in Olympia, WA", warning=CORRECT_WARNING,
                   heading_bold=False, bg="#efe7d6"),
         filed=dict(brand_name="GRAY HARBOR", class_type="Straight Bourbon Whiskey",
                    alcohol_content="46% Alc./Vol.", net_contents="750 mL",
                    origin="Washington"),
         note="Warning is ALL CAPS but NOT bold -> attention (bold check catches it)"),

    dict(file="13_spirits_too_degraded.png",
         spec=dict(brand="NORTHWIND", cls="London Dry Gin",
                   abv_line="44% Alc./Vol. (88 Proof)", net="750 mL",
                   address="Bottled in Bend, OR", warning=CORRECT_WARNING, bg="#ece9e3"),
         filed=dict(brand_name="NORTHWIND", class_type="London Dry Gin",
                    alcohol_content="44% Alc./Vol.", net_contents="750 mL", origin="Oregon"),
         degrade=dict(blur=5.0, brightness=0.45),
         note="Too degraded even after enhancement -> trips low-quality flag (reviewer can confirm)"),

    dict(file="14_wine_blurry_wrong_abv.png",
         spec=dict(brand="HOLLOW OAK", cls="Cabernet Sauvignon",
                   abv_line="13.5% Alc./Vol.", net="750 mL",
                   address="Vinted & bottled in Paso Robles, CA", extra="Contains Sulfites",
                   warning=CORRECT_WARNING, family="serif", bg="#f4efe6"),
         filed=dict(brand_name="HOLLOW OAK", class_type="Cabernet Sauvignon",
                    alcohol_content="14.5% Alc./Vol.", net_contents="750 mL", origin="California"),
         degrade=dict(blur=1.5, brightness=0.7),
         note="Bad photo + WRONG info: label ABV 13.5% but filed 14.5% -> catches the error"),

    dict(file="15_beer_glare_wrong_brand.png",
         spec=dict(brand="COPPER KETTLE", cls="Amber Ale", abv_line="5.5% Alc./Vol.",
                   net="12 FL OZ", address="Brewed & bottled in Boise, ID",
                   warning=CORRECT_WARNING, bg="#ece2cf"),
         filed=dict(brand_name="IRON ANCHOR", class_type="Amber Ale",
                    alcohol_content="5.5% Alc./Vol.", net_contents="12 fl oz", origin="Idaho"),
         degrade=dict(glare=(0.62, 0.4, 210, 150), noise=10),
         note="Bad photo + WRONG info: label brand 'COPPER KETTLE' vs filed 'IRON ANCHOR' -> catches mismatch"),
]

COLUMNS = ["label_id", "image_filename", "brand_name", "class_type",
           "alcohol_content", "net_contents", "origin", "expected_outcome"]


def main():
    print("Generating sample labels in", OUT)
    rows = []
    for i, s in enumerate(SAMPLES, 1):
        img = render(s["spec"])
        if s.get("degrade"):
            img = degrade(img, s["degrade"])
        img.save(OUT / s["file"])
        print(f"  wrote {s['file']:38} ({s['note']})")
        f = s["filed"]
        rows.append({
            "label_id": f"APP-{i:03d}",
            "image_filename": s["file"],
            "brand_name": f.get("brand_name", ""),
            "class_type": f.get("class_type", ""),
            "alcohol_content": f.get("alcohol_content", ""),
            "net_contents": f.get("net_contents", ""),
            "origin": f.get("origin", ""),
            "expected_outcome": s["note"],
        })

    manifest = OUT / "sample_manifest.csv"
    with open(manifest, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print("  wrote sample_manifest.csv")

    if FRONTEND.exists():
        (FRONTEND / "sample_manifest.csv").write_text(manifest.read_text())
        print("  copied manifest into frontend/")

    print("\nDone. Single check: sample_data/01_spirits_correct.png")
    print("Batch check: upload sample_manifest.csv + all the images.")
    print("Note: the batch manifest's 'expected_outcome' column is just a hint for")
    print("you; the app ignores unknown columns.")


if __name__ == "__main__":
    main()
