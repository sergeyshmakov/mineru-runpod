import type { Metadata } from "next";
import {
	absoluteUrl,
	ogImageAlt,
	ogImagePath,
	siteName,
} from "@/lib/site";

// A page-level `openGraph` or `alternates` object replaces the root layout's
// wholesale, so the shared image and the feed link have to be re-stated on every
// page. Build page metadata through here and they cannot be forgotten.
export const rssAlternates = {
	"application/rss+xml": [{ url: "/blog/rss.xml", title: "Blog" }],
};

export const ogImage = {
	url: absoluteUrl(ogImagePath).toString(),
	alt: ogImageAlt,
	width: 1200,
	height: 630,
};

type PageMetadata = {
	title: string;
	description: string;
	path: string;
	type?: "website" | "article";
	publishedTime?: string;
	modifiedTime?: string;
};

export function pageMetadata({
	title,
	description,
	path,
	type = "website",
	publishedTime,
	modifiedTime,
}: PageMetadata): Metadata {
	const canonical = absoluteUrl(path).toString();

	return {
		title,
		description,
		alternates: { canonical, types: rssAlternates },
		openGraph: {
			type,
			siteName,
			title,
			description,
			url: canonical,
			images: [ogImage],
			...(publishedTime ? { publishedTime } : {}),
			...(modifiedTime ? { modifiedTime } : {}),
		},
	};
}
