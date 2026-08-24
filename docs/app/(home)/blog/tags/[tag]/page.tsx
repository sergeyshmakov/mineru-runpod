import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { BlogList } from "@/components/blog-list";
import { JsonLd } from "@/components/json-ld";
import { getPostsByTag, getTags } from "@/lib/blog";
import { pageMetadata } from "@/lib/metadata";
import { tagSchema } from "@/lib/schema";
import { siteDescription } from "@/lib/site";

type PageProperties = {
	params: Promise<{ tag: string }>;
};

export default async function TagPage(props: PageProperties) {
	const { tag } = await props.params;
	const entry = getTags().find((candidate) => candidate.slug === tag);
	if (!entry) notFound();

	return (
		<main className="mx-auto w-full max-w-6xl flex-1 px-6 py-16 sm:py-20">
			<JsonLd schema={tagSchema(entry.slug, entry.name)} />
			<p className="text-sm text-fd-muted-foreground">Blog tag</p>
			<h1 className="mt-2 text-4xl font-semibold tracking-tight">
				{entry.name}
			</h1>
			<div className="mt-10">
				<BlogList posts={getPostsByTag(tag)} />
			</div>
		</main>
	);
}

export function generateStaticParams() {
	return getTags().map(({ slug }) => ({ tag: slug }));
}

export async function generateMetadata(
	props: PageProperties,
): Promise<Metadata> {
	const { tag } = await props.params;
	const entry = getTags().find((candidate) => candidate.slug === tag);
	if (!entry) notFound();

	return pageMetadata({
		title: entry.name,
		description: siteDescription,
		path: `/blog/tags/${tag}/`,
	});
}
