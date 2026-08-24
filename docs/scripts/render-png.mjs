// Rasterise an SVG into a PNG the site or the Hub listing needs.
//
// Two things here have to be generated rather than authored: the RunPod Hub
// takes a raster for its listing icon, and social cards have to be a PNG because
// no crawler renders SVG. Generating both from SVG sources committed alongside
// them means the listing, the favicon and the share card cannot drift apart from
// each other or from the site.
//
// sharp is already a transitive dependency of the docs build, which is why this
// lives here rather than pulling a rasteriser into the Python side.
//
//   node scripts/render-png.mjs <input.svg> <output.png> <width> [height]
//
// With no height the SVG's own aspect ratio is kept.

import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";

const [, , input, output, rawWidth, rawHeight] = process.argv;

if (!input || !output || !rawWidth) {
	console.error(
		"usage: node scripts/render-png.mjs <input.svg> <output.png> <width> [height]",
	);
	process.exit(2);
}

function dimension(raw, label) {
	const value = Number.parseInt(raw, 10);
	if (!Number.isInteger(value) || value < 16 || value > 4096) {
		console.error(`refusing ${label} ${raw}: expected an integer from 16 to 4096`);
		process.exit(2);
	}
	return value;
}

const width = dimension(rawWidth, "width");
const height = rawHeight === undefined ? undefined : dimension(rawHeight, "height");

const svg = await readFile(path.resolve(input));

// The viewBox is authored in its own units, so sharp has to be told to
// rasterise at the target resolution rather than at the nominal one and upscale.
// `density` is relative to 72dpi against the SVG's intrinsic width; without it
// the output is a blurred small render stretched to size.
const intrinsic = await sharp(svg).metadata();
const density = Math.min(2400, (width / (intrinsic.width || width)) * 72);

const png = await sharp(svg, { density })
	.resize(width, height, {
		fit: height === undefined ? "cover" : "contain",
		background: { r: 0, g: 0, b: 0, alpha: 0 },
	})
	.png({ compressionLevel: 9 })
	.toBuffer();

await writeFile(path.resolve(output), png);

const rendered = await sharp(png).metadata();
console.log(`${output}: ${rendered.width}x${rendered.height}, ${png.length} bytes`);
