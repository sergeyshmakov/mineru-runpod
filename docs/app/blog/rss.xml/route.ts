import { toHtml } from "hast-util-to-html";
import { toHast } from "mdast-util-to-hast";
import { authors, getPosts } from "@/lib/blog";
import { absoluteUrl, siteDescription, siteName } from "@/lib/site";

export const revalidate = false;

function xml(value: string) {
	return value
		.replaceAll("&", "&amp;")
		.replaceAll("<", "&lt;")
		.replaceAll(">", "&gt;")
		.replaceAll('"', "&quot;")
		.replaceAll("'", "&apos;");
}

function cdata(value: string) {
	return value.replaceAll("]]>", "]]]]><![CDATA[>");
}

function absoluteLinks(html: string) {
	return html.replaceAll(
		/(href|src)="\/(?!\/)/g,
		`$1="${absoluteUrl("/").origin}/`,
	);
}

export async function GET() {
	const items = (
		await Promise.all(
			getPosts().map(async (post) => {
				const author = authors[post.data.authors as keyof typeof authors];
				const url = absoluteUrl(`${post.url}/`).toString();
				const hast = toHast(await post.data.getMDAST(), {
					allowDangerousHtml: true,
				});
				const body = hast
					? absoluteLinks(toHtml(hast, { allowDangerousHtml: true }))
					: "";
				const published = new Date(`${post.data.date}T00:00:00Z`).toUTCString();

				return [
					"<item>",
					`<title>${xml(post.data.title)}</title>`,
					`<link>${xml(url)}</link>`,
					`<guid isPermaLink="true">${xml(url)}</guid>`,
					`<description>${xml(post.data.description ?? "")}</description>`,
					`<pubDate>${published}</pubDate>`,
					author ? `<dc:creator>${xml(author.name)}</dc:creator>` : "",
					`<content:encoded><![CDATA[${cdata(body)}]]></content:encoded>`,
					"</item>",
				].join("");
			}),
		)
	).join("");

	const channelUrl = absoluteUrl("/blog/").toString();
	const feedUrl = absoluteUrl("/blog/rss.xml").toString();
	const body = [
		'<?xml version="1.0" encoding="UTF-8"?>',
		'<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:fh="http://purl.org/syndication/history/1.0" xmlns:dc="http://purl.org/dc/elements/1.1/">',
		"<channel>",
		`<title>${xml(`${siteName} | Blog`)}</title>`,
		`<description>${xml(siteDescription)}</description>`,
		`<link>${xml(channelUrl)}</link>`,
		"<language>en</language>",
		"<fh:complete/>",
		`<atom:link rel="self" href="${xml(feedUrl)}" type="application/rss+xml" />`,
		items,
		"</channel>",
		"</rss>",
	].join("");

	return new Response(body, {
		headers: {
			"Content-Type": "application/rss+xml; charset=utf-8",
		},
	});
}
