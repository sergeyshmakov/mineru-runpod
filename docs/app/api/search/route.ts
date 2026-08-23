import { createSearchAPI } from "fumadocs-core/search/server";
import { blog, source } from "@/lib/source";

export const revalidate = false;

// Starlight's Pagefind indexed the blog alongside the docs, so both loaders
// feed one index here rather than using createFromSource on the docs alone.
const indexes = [...source.getPages(), ...blog.getPages()].map((page) => ({
	id: page.url,
	url: page.url,
	title: page.data.title,
	description: page.data.description,
	structuredData: page.data.structuredData,
}));

export const { staticGET: GET } = createSearchAPI("advanced", {
	indexes,
	language: "english",
});
