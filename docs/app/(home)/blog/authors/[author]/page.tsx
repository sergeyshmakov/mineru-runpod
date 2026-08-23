import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { BlogList } from "@/components/blog-list";
import { JsonLd } from "@/components/json-ld";
import { authors, getAuthorBySlug, getPostsByAuthor } from "@/lib/blog";
import { pageMetadata } from "@/lib/metadata";
import { authorSchema } from "@/lib/schema";
import { siteDescription } from "@/lib/site";

type PageProperties = {
	params: Promise<{ author: string }>;
};

export default async function AuthorPage(props: PageProperties) {
	const { author } = await props.params;
	const entry = getAuthorBySlug(author);
	if (!entry) notFound();
	const [authorId, details] = entry;

	return (
		<main className="mx-auto w-full max-w-6xl flex-1 px-6 py-16 sm:py-20">
			<JsonLd
				schema={authorSchema(details.slug, details.name, details.url)}
			/>
			<p className="text-sm text-fd-muted-foreground">Blog author</p>
			<h1 className="mt-2 text-4xl font-semibold tracking-tight">
				{details.name}
			</h1>
			<div className="mt-10">
				<BlogList posts={getPostsByAuthor(authorId)} />
			</div>
		</main>
	);
}

export function generateStaticParams() {
	return Object.values(authors).map(({ slug }) => ({ author: slug }));
}

export async function generateMetadata(
	props: PageProperties,
): Promise<Metadata> {
	const { author } = await props.params;
	const entry = getAuthorBySlug(author);
	if (!entry) notFound();

	return pageMetadata({
		title: entry[1].name,
		description: siteDescription,
		path: `/blog/authors/${author}/`,
	});
}
