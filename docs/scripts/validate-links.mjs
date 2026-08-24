import path from "node:path";
import { getTableOfContents } from "fumadocs-core/content/toc";
import { getSlugs } from "fumadocs-core/source";
import {
	printErrors,
	readFiles,
	scanURLs,
	validateFiles,
} from "next-validate-link";

const docsFiles = await readFiles("content/docs/**/*.{md,mdx}");
const blogFiles = await readFiles("content/blog/**/*.{md,mdx}");

const docsEntries = docsFiles.map((file) => ({
	value: getSlugs(
		path.relative("content/docs", file.path).split(path.sep).join("/"),
	),
	hashes: getTableOfContents(file.content).map((item) => item.url.slice(1)),
}));

const blogEntries = blogFiles.map((file) => ({
	value: getSlugs(
		path.relative("content/blog", file.path).split(path.sep).join("/"),
	)[0],
	hashes: getTableOfContents(file.content).map((item) => item.url.slice(1)),
}));

const scanned = await scanURLs({
	preset: "next",
	pages: [
		path.join("(home)", "page.tsx"),
		path.join("(home)", "blog", "page.tsx"),
		path.join("(home)", "blog", "[slug]", "page.tsx"),
		path.join("(home)", "blog", "authors", "[author]", "page.tsx"),
		path.join("(home)", "blog", "tags", "[tag]", "page.tsx"),
		path.join("(docs)", "[...slug]", "page.tsx"),
	],
	populate: {
		"(docs)/[...slug]": docsEntries,
		"(home)/blog/[slug]": blogEntries,
		"(home)/blog/authors/[author]": [{ value: "sergei-shmakov" }],
		"(home)/blog/tags/[tag]": [
			"document-parsing",
			"mineru",
			"observability",
			"runpod",
			"serverless",
			"troubleshooting",
		].map((value) => ({ value })),
	},
});

for (const [url, metadata] of scanned.urls) {
	if (url !== "/" && !url.endsWith("/") && !url.includes(".")) {
		scanned.urls.set(`${url}/`, metadata);
	}
}

printErrors(
	await validateFiles([...docsFiles, ...blogFiles], {
		scanned,
	}),
	true,
);
