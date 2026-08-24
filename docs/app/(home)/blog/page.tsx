import type { Metadata } from "next";
import { BlogList } from "@/components/blog-list";
import { JsonLd } from "@/components/json-ld";
import { getPosts } from "@/lib/blog";
import { pageMetadata } from "@/lib/metadata";
import { blogIndexSchema } from "@/lib/schema";
import { siteDescription } from "@/lib/site";

export const metadata: Metadata = pageMetadata({
	title: "Blog",
	description: siteDescription,
	path: "/blog/",
});

export default function BlogPage() {
	return (
		<main className="mx-auto w-full max-w-6xl flex-1 px-6 py-16 sm:py-20">
			<JsonLd schema={blogIndexSchema()} />
			<h1 className="text-4xl font-semibold tracking-tight">Blog</h1>
			<p className="mt-4 max-w-3xl text-lg text-fd-muted-foreground">
				Measured notes on running MinerU document parsing on RunPod Serverless —
				cost, cold starts, output shapes, and observability.
			</p>
			<div className="mt-10">
				<BlogList posts={getPosts()} />
			</div>
		</main>
	);
}
