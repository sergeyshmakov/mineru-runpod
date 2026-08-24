import { loader } from "fumadocs-core/source";
import { metaSchema, pageSchema } from "fumadocs-core/source/schema";
import { defineCollections, defineDocs } from "fumadocs-mdx/macro";
import { z } from "zod";

const documentation = defineDocs({
	dir: "content/docs",
	docs: {
		lastModified: true,
		schema: pageSchema,
	},
	meta: {
		schema: metaSchema,
	},
});

const blogPosts = defineCollections({
	type: "doc",
	dir: "content/blog",
	lastModified: true,
	postprocess: {
		// The RSS feed renders each post's MDAST into HTML for content:encoded.
		includeMDAST: true,
	},
	schema: pageSchema.extend({
		date: z.string().date(),
		lastUpdated: z.string().date().optional(),
		authors: z.string(),
		tags: z.array(z.string()),
	}),
});

export const source = loader({
	baseUrl: "/",
	source: documentation.toFumadocsSource(),
});

export const blog = loader({
	baseUrl: "/blog",
	source: blogPosts.toFumadocsSource(),
});
