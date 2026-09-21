// One-off asset generator, not part of the build - re-run by hand whenever
// the mark (public/favicon.svg) or the OG card design (scripts/og-image.svg)
// changes. Rasterizes both source SVGs to the PNGs index.html references
// (og:image, favicon fallbacks, apple-touch-icon, manifest icons).
//
//   node scripts/generate-brand-assets.mjs
import sharp from "sharp";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const favicon = join(root, "public", "favicon.svg");
const ogSource = join(__dirname, "og-image.svg");

async function run() {
  await sharp(ogSource).resize(1200, 630).png().toFile(join(root, "public", "og-image.png"));

  const icons = [
    ["favicon-16.png", 16],
    ["favicon-32.png", 32],
    ["apple-touch-icon.png", 180],
    ["icon-512.png", 512],
  ];
  for (const [name, size] of icons) {
    await sharp(favicon).resize(size, size).png().toFile(join(root, "public", name));
  }

  console.log("Generated: og-image.png, " + icons.map(([n]) => n).join(", "));
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
