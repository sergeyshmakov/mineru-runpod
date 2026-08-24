import type { MetadataRoute } from "next";

import { authors, getPosts, getTags } from "@/lib/blog";
import { absoluteUrl } from "@/lib/site";
import { source } from "@/lib/source";

export const dynamic = "force-static";

function entry(path: string, priority: number): MetadataRoute.Sitemap[number] {
	return {
		url: absoluteUrl(path).toString(),
		changeFrequency: "monthly",
		priority,
	};
}

export default function sitemap(): MetadataRoute.Sitemap {
	return [
		entry("/", 1),
		...source.getPages().map((page) => entry(page.url, 0.7)),
		entry("/blog/", 0.9),
		...getPosts().map((post) => entry(post.url, 0.7)),
		...getTags().map((tag) => entry(`/blog/tags/${tag.slug}/`, 0.7)),
		...Object.values(authors).map((author) =>
			entry(`/blog/authors/${author.slug}/`, 0.7),
		),
	];
}
