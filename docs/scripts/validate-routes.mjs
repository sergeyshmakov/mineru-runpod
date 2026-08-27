import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";

const SITE = "https://mineru.shmakov.tools";
const OG_IMAGE = `${SITE}/og-default.png`;
const CF_BEACON = "https://static.cloudflareinsights.com/beacon.min.js";

// Every public route the Astro build published, so the migration cannot drop or
// invent one. Kept sorted; validated against out/sitemap.xml below.
const routes = [
	"/",
	"/blog/",
	"/blog/2026-05-19-launching-mineru-runpod/",
	"/blog/2026-05-20-runpod-20mb-response-cap-r2-bridge/",
	"/blog/2026-05-26-otel-mineru-runpod-axiom/",
	"/blog/2026-05-26-runpod-flashboot-mechanism-investigation/",
	"/blog/2026-06-03-clause-aligned-batching-large-pdf-mineru/",
	"/blog/2026-06-03-runpod-machine-does-not-have-the-resources-fix/",
	"/blog/2026-06-04-structuring-mineru-output-doc-tree/",
	"/blog/2026-06-08-self-host-mineru-api/",
	"/blog/authors/sergei-shmakov/",
	"/blog/tags/document-parsing/",
	"/blog/tags/mineru/",
	"/blog/tags/observability/",
	"/blog/tags/runpod/",
	"/blog/tags/serverless/",
	"/blog/tags/troubleshooting/",
	"/getting-started/clients/",
	"/getting-started/deploy/",
	"/getting-started/migrate-from-mineru-api/",
	"/getting-started/overview/",
	"/guides/choosing-gpu/",
	"/guides/concurrency/",
	"/guides/input-formats/",
	"/guides/network-volumes/",
	"/guides/observability/",
	"/guides/output-modes/",
	"/guides/scaling/",
	"/guides/troubleshooting/",
	"/reference/api/",
	"/reference/versioning/",
];

// Titles as the live site publishes them: page title plus the site suffix.
const titles = new Map(
	Object.entries({
		"/": "Deploy MinerU on RunPod Serverless",
		"/blog/": "Blog",
		"/blog/2026-05-19-launching-mineru-runpod/":
			"Serverless MinerU on RunPod: cost math",
		"/blog/2026-05-20-runpod-20mb-response-cap-r2-bridge/":
			"RunPod 20 MB cap: fix NoneType with R2",
		"/blog/2026-05-26-otel-mineru-runpod-axiom/":
			"OpenTelemetry: send MinerU logs to Axiom",
		"/blog/2026-05-26-runpod-flashboot-mechanism-investigation/":
			"RunPod FlashBoot: a four-request test",
		"/blog/2026-06-03-clause-aligned-batching-large-pdf-mineru/":
			"Batch a 5,039-page PDF with MinerU",
		"/blog/2026-06-03-runpod-machine-does-not-have-the-resources-fix/":
			"Fix RunPod's 'no resources' error",
		"/blog/2026-06-04-structuring-mineru-output-doc-tree/":
			"Structure MinerU output into a document tree",
		"/blog/2026-06-08-self-host-mineru-api/":
			"Self-host the MinerU API on RunPod",
		"/blog/authors/sergei-shmakov/": "Sergei Shmakov",
		"/blog/tags/document-parsing/": "Document parsing",
		"/blog/tags/mineru/": "MinerU",
		"/blog/tags/observability/": "Observability",
		"/blog/tags/runpod/": "RunPod",
		"/blog/tags/serverless/": "Serverless",
		"/blog/tags/troubleshooting/": "Troubleshooting",
		"/getting-started/clients/": "Clients",
		"/getting-started/deploy/": "Deploy",
		"/getting-started/migrate-from-mineru-api/": "Migrate from the MinerU API",
		"/getting-started/overview/": "Overview",
		"/guides/choosing-gpu/": "Choosing a GPU",
		"/guides/concurrency/": "Concurrency",
		"/guides/input-formats/": "Input formats",
		"/guides/network-volumes/": "Network volumes",
		"/guides/observability/": "OpenTelemetry",
		"/guides/output-modes/": "Output modes",
		"/guides/scaling/": "Scaling and tuning",
		"/guides/troubleshooting/": "Troubleshooting",
		"/reference/api/": "API reference",
		"/reference/versioning/": "Versioning",
	}).map(([route, title]) => [route, `${title} | mineru-runpod`]),
);

const postRoutes = routes.filter(
	(route) => route.startsWith("/blog/2") && route !== "/blog/",
);
const collectionRoutes = [
	"/blog/",
	"/blog/authors/sergei-shmakov/",
	...routes.filter((route) => route.startsWith("/blog/tags/")),
];

function fileForRoute(route) {
	if (route === "/") return path.join("out", "index.html");
	return path.join("out", ...route.split("/").filter(Boolean), "index.html");
}

function decode(value) {
	return value
		.replaceAll("&#x27;", "'")
		.replaceAll("&#39;", "'")
		.replaceAll("&quot;", '"')
		.replaceAll("&lt;", "<")
		.replaceAll("&gt;", ">")
		.replaceAll("&amp;", "&");
}

function match(html, expression, label, route) {
	const result = expression.exec(html)?.[1];
	if (!result) throw new Error(`${route}: missing ${label}`);
	return result;
}

function requires(html, needle, label, route) {
	if (!html.includes(needle)) throw new Error(`${route}: missing ${label}`);
}

for (const route of routes) {
	const file = fileForRoute(route);
	if (!existsSync(file)) throw new Error(`${route}: expected ${file}`);
	const html = await readFile(file, "utf8");

	const canonical = match(
		html,
		/<link rel="canonical" href="([^"]+)"/,
		"canonical URL",
		route,
	);
	if (canonical !== `${SITE}${route}`) {
		throw new Error(`${route}: canonical is ${canonical}`);
	}

	match(
		html,
		/<meta name="description" content="([^"]+)"/,
		"description",
		route,
	);

	const expectedTitle = titles.get(route);
	const title = decode(match(html, /<title>(.*?)<\/title>/, "title", route));
	if (title !== expectedTitle) {
		throw new Error(`${route}: title is ${title}; expected ${expectedTitle}`);
	}

	// Social cards: Starlight published these sitewide, so every page keeps them.
	requires(
		html,
		`<meta property="og:image" content="${OG_IMAGE}"`,
		"og:image",
		route,
	);
	requires(html, '<meta property="og:image:width" content="1200"', "og:image:width", route);
	requires(html, '<meta property="og:image:height" content="630"', "og:image:height", route);
	requires(html, 'property="og:image:alt"', "og:image:alt", route);
	requires(
		html,
		'<meta name="twitter:card" content="summary_large_image"',
		"twitter:card",
		route,
	);

	// A page-level twitter object replaces the root layout's, so an omission
	// shows up as every card carrying the site name instead of the page title.
	const cardTitle = decode(
		match(
			html,
			/<meta name="twitter:title" content="([^"]+)"/,
			"twitter:title",
			route,
		),
	);
	const pageTitle = expectedTitle.replace(" | mineru-runpod", "");
	if (cardTitle !== pageTitle) {
		throw new Error(
			`${route}: twitter:title is ${cardTitle}; expected ${pageTitle}`,
		);
	}

	// Cloudflare Web Analytics is injected by the app shell, not by a proxy.
	requires(html, CF_BEACON, "Cloudflare Web Analytics beacon", route);

	// The RSS feed is discoverable from every page, as it was under Starlight.
	requires(html, "/blog/rss.xml", "RSS alternate link", route);
}

// Structured data: blog surfaces only, matching what starlight-blog emitted.
for (const route of postRoutes) {
	const html = await readFile(fileForRoute(route), "utf8");
	requires(html, '"@type":"BlogPosting"', "BlogPosting JSON-LD", route);
	requires(html, '"@type":"BreadcrumbList"', "BreadcrumbList JSON-LD", route);
	requires(html, '"@type":"Blog"', "Blog JSON-LD node", route);
}

for (const route of collectionRoutes) {
	const html = await readFile(fileForRoute(route), "utf8");
	requires(html, '"@type":"CollectionPage"', "CollectionPage JSON-LD", route);
}

for (const route of routes.filter((r) => r.startsWith("/blog/tags/"))) {
	const html = await readFile(fileForRoute(route), "utf8");
	requires(html, '"@type":"DefinedTerm"', "DefinedTerm JSON-LD", route);
}

for (const route of ["/getting-started/overview/", "/reference/api/"]) {
	const html = await readFile(fileForRoute(route), "utf8");
	if (html.includes("application/ld+json")) {
		throw new Error(`${route}: docs pages carry no structured data`);
	}
}

// The single Mermaid diagram must be server-rendered SVG, not client script.
const mermaidRoute = "/guides/output-modes/";
const mermaidHtml = await readFile(fileForRoute(mermaidRoute), "utf8");
const markers = mermaidHtml.match(/data-mermaid-diagram="true"/g) ?? [];
const rendered =
	mermaidHtml.match(
		/data-mermaid-diagram="true"[^>]*><svg[\s\S]*?<\/svg><\/div>/g,
	) ?? [];
if (markers.length !== 1 || rendered.length !== 1) {
	throw new Error(
		`${mermaidRoute}: expected 1 server-rendered Mermaid diagram; found ${markers.length} markers and ${rendered.length} SVGs`,
	);
}

// The overview hotlinks an upstream benchmark image. next/image cannot size a
// remote file without fetching it, so this must stay a plain img element.
const overviewHtml = await readFile(
	fileForRoute("/getting-started/overview/"),
	"utf8",
);
const leaderboard = "https://hotelll.github.io/MinerU2.5-Pro/leaderboard.png";
if (!overviewHtml.includes(`src="${leaderboard}"`)) {
	throw new Error("/getting-started/overview/: missing the leaderboard image");
}
if (/<img[^>]*data-nimg/.test(overviewHtml)) {
	throw new Error(
		"/getting-started/overview/: external image must not go through next/image",
	);
}

// Tabs and callouts survived the MDX conversion.
const tabsHtml = await readFile(fileForRoute("/getting-started/clients/"), "utf8");
if (!/role="tab"/.test(tabsHtml)) {
	throw new Error("/getting-started/clients/: missing rendered tabs");
}

for (const file of [
	path.join("out", "404.html"),
	path.join("out", "favicon.svg"),
	path.join("out", "logo.svg"),
	path.join("out", "og-default.png"),
	path.join("out", "hero.svg"),
	path.join("out", "google9835a2061220351a.html"),
	path.join("out", "robots.txt"),
	path.join("out", "sitemap.xml"),
	path.join("out", "blog", "rss.xml"),
]) {
	if (!existsSync(file)) throw new Error(`missing static output: ${file}`);
}

// Next also emits /404/ and /_not-found/ as crawlable directories, which Astro
// did not. They stay out of the sitemap and must carry noindex.
for (const extra of ["404", "_not-found"]) {
	const file = path.join("out", extra, "index.html");
	if (!existsSync(file)) continue;
	const html = await readFile(file, "utf8");
	if (!html.includes('name="robots" content="noindex')) {
		throw new Error(`/${extra}/: must be noindex`);
	}
}

const robots = await readFile(path.join("out", "robots.txt"), "utf8");
if (!robots.includes(`Sitemap: ${SITE}/sitemap.xml`)) {
	throw new Error("robots.txt must advertise /sitemap.xml");
}

const sitemap = await readFile(path.join("out", "sitemap.xml"), "utf8");
const sitemapUrls = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)]
	.map(([, url]) => url)
	.sort();
const expectedSitemapUrls = routes.map((route) => `${SITE}${route}`).sort();
if (JSON.stringify(sitemapUrls) !== JSON.stringify(expectedSitemapUrls)) {
	throw new Error(
		`sitemap URLs differ from public routes:\n${JSON.stringify(sitemapUrls, null, 2)}`,
	);
}

const feed = await readFile(path.join("out", "blog", "rss.xml"), "utf8");
for (const needle of [
	`<link>${SITE}/blog/</link>`,
	`<atom:link rel="self" href="${SITE}/blog/rss.xml"`,
	"<dc:creator>Sergei Shmakov</dc:creator>",
	"<content:encoded>",
]) {
	if (!feed.includes(needle)) {
		throw new Error(`blog/rss.xml: missing ${needle}`);
	}
}
const feedItems = feed.match(/<item>/g) ?? [];
if (feedItems.length !== postRoutes.length) {
	throw new Error(
		`blog/rss.xml: ${feedItems.length} items for ${postRoutes.length} posts`,
	);
}

if (existsSync(path.join("out", "docs", "index.html"))) {
	throw new Error(
		"unexpected /docs/ route: documentation must remain at the domain root",
	);
}

if (existsSync(path.join("out", "blog", "2", "index.html"))) {
	throw new Error("unexpected /blog/2/ route: the blog index is not paginated");
}

console.log(
	`Validated ${routes.length} canonical public routes, structured data, and static assets.`,
);
