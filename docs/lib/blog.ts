import { authorName, authorUrl } from "@/lib/site";
import { blog } from "@/lib/source";

export const authors = {
	sergei: {
		name: authorName,
		slug: "sergei-shmakov",
		url: authorUrl,
	},
} as const;

export type BlogPost = (typeof blog)["$inferPage"];

export function getPosts(): BlogPost[] {
	return blog
		.getPages()
		.toSorted((left, right) => right.data.date.localeCompare(left.data.date));
}

export function tagSlug(tag: string) {
	return tag
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, "-")
		.replace(/^-|-$/g, "");
}

export function getTags() {
	const tags = new Map<string, string>();
	for (const post of getPosts()) {
		for (const tag of post.data.tags) tags.set(tagSlug(tag), tag);
	}
	return [...tags]
		.map(([slug, name]) => ({ slug, name }))
		.toSorted((left, right) => left.slug.localeCompare(right.slug));
}

export function getPostsByTag(slug: string) {
	return getPosts().filter((post) =>
		post.data.tags.some((tag) => tagSlug(tag) === slug),
	);
}

export function getAuthorBySlug(slug: string) {
	return Object.entries(authors).find(([, author]) => author.slug === slug);
}

export function getPostsByAuthor(authorId: string) {
	return getPosts().filter((post) => post.data.authors === authorId);
}

export function postDate(post: BlogPost) {
	return new Date(`${post.data.date}T00:00:00Z`);
}

export function formatDate(date: string) {
	return new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", {
		dateStyle: "long",
		timeZone: "UTC",
	});
}
