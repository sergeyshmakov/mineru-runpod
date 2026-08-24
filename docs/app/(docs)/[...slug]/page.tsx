import {
	DocsBody,
	DocsDescription,
	DocsPage,
	DocsTitle,
	PageLastUpdate,
	ViewOptionsPopover,
} from "fumadocs-ui/layouts/docs/page";
import { createRelativeLink } from "fumadocs-ui/mdx";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getMDXComponents } from "@/components/mdx";
import { pageMetadata } from "@/lib/metadata";
import { repositoryUrl } from "@/lib/site";
import { source } from "@/lib/source";

type PageProperties = {
	params: Promise<{ slug: string[] }>;
};

export default async function DocumentationPage(props: PageProperties) {
	const params = await props.params;
	const page = source.getPage(params.slug);
	if (!page) notFound();

	const MDX = page.data.body;
	const githubUrl = `${repositoryUrl}/edit/main/docs/content/docs/${page.path}`;

	return (
		<DocsPage toc={page.data.toc} full={page.data.full}>
			<DocsTitle>{page.data.title}</DocsTitle>
			<DocsDescription className="mb-0">
				{page.data.description}
			</DocsDescription>
			<div className="flex flex-row items-center gap-2 border-b pb-6">
				<ViewOptionsPopover githubUrl={githubUrl} />
			</div>
			<DocsBody>
				<MDX
					components={getMDXComponents({
						a: createRelativeLink(source, page),
					})}
				/>
			</DocsBody>
			{page.data.lastModified && (
				<PageLastUpdate date={page.data.lastModified} />
			)}
		</DocsPage>
	);
}

export function generateStaticParams() {
	return source.generateParams();
}

export async function generateMetadata(
	props: PageProperties,
): Promise<Metadata> {
	const params = await props.params;
	const page = source.getPage(params.slug);
	if (!page) notFound();

	return pageMetadata({
		title: page.data.title,
		description: page.data.description ?? "",
		path: page.url,
		type: "article",
	});
}
