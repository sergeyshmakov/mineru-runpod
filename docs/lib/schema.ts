// JSON-LD graphs for the blog surfaces.
//
// Starlight emitted these for free; Fumadocs does not, and the shapes here
// reproduce what the Astro build published so the migration does not drop a
// structured-data surface. Docs pages never carried any and still don't.

import { type BlogPost, authors } from "@/lib/blog";
import { absoluteUrl, authorName, authorUrl } from "@/lib/site";

const BLOG_URL = absoluteUrl("/blog/").toString();
const BLOG_ID = `${BLOG_URL}#blog`;

type Graph = Record<string, unknown>;

const blogNode: Graph = {
	"@id": BLOG_ID,
	"@type": "Blog",
	name: "Blog",
	url: BLOG_URL,
};

function personNode(slug: string, name: string, url: string): Graph {
	return {
		"@id": `${absoluteUrl(`/blog/authors/${slug}/`).toString()}#author`,
		"@type": "Person",
		name,
		url,
	};
}

function graph(nodes: Graph[]) {
	return { "@context": "https://schema.org", "@graph": nodes };
}

export function postSchema(post: BlogPost) {
	const url = absoluteUrl(`${post.url}/`).toString();
	const author = authors[post.data.authors as keyof typeof authors];
	const person = personNode(
		author?.slug ?? "sergei-shmakov",
		author?.name ?? authorName,
		author?.url ?? authorUrl,
	);

	return graph([
		{
			"@type": "BlogPosting",
			datePublished: `${post.data.date}T00:00:00.000Z`,
			dateModified: `${post.data.lastUpdated ?? post.data.date}T00:00:00.000Z`,
			headline: post.data.title,
			inLanguage: "en",
			isPartOf: { "@id": BLOG_ID },
			mainEntityOfPage: url,
			url,
			author: [person],
			description: post.data.description,
			keywords: post.data.tags,
		},
		{
			"@type": "BreadcrumbList",
			itemListElement: [
				{
					"@type": "ListItem",
					position: 1,
					name: "Blog",
					item: BLOG_URL,
				},
				{
					"@type": "ListItem",
					position: 2,
					name: post.data.title,
				},
			],
		},
		blogNode,
	]);
}

export function blogIndexSchema() {
	return graph([
		{
			"@type": "CollectionPage",
			inLanguage: "en",
			name: "Blog",
			url: BLOG_URL,
			mainEntity: { "@id": BLOG_ID },
		},
		blogNode,
	]);
}

export function authorSchema(slug: string, name: string, url: string) {
	const pageUrl = absoluteUrl(`/blog/authors/${slug}/`).toString();
	const person = personNode(slug, name, url);

	return graph([
		{
			"@type": "CollectionPage",
			inLanguage: "en",
			name,
			url: pageUrl,
			isPartOf: { "@id": BLOG_ID },
			mainEntity: { "@id": person["@id"] },
		},
		blogNode,
		person,
	]);
}

export function tagSchema(slug: string, name: string) {
	const pageUrl = absoluteUrl(`/blog/tags/${slug}/`).toString();
	const tagId = `${pageUrl}#tag`;

	return graph([
		{
			"@type": "CollectionPage",
			inLanguage: "en",
			name,
			url: pageUrl,
			isPartOf: { "@id": BLOG_ID },
			mainEntity: { "@id": tagId },
		},
		blogNode,
		{
			"@id": tagId,
			"@type": "DefinedTerm",
			name,
			url: pageUrl,
		},
	]);
}
