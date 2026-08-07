import sitemap from "@astrojs/sitemap";
import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";
import starlightBlog from "starlight-blog";

const REPO_URL = "https://github.com/sergeyshmakov/mineru-runpod";

export default defineConfig({
	site: "https://mineru.shmakov.tools",
	base: "",
	integrations: [
		starlight({
			title: "mineru-runpod",
			description:
				"Deploy MinerU 3.4 on RunPod Serverless. The open-source endpoint scales to zero and returns Markdown, structured JSON, and extracted images.",
			favicon: "/favicon.png",
			customCss: ["./src/styles/custom.css"],
			social: [{ icon: "github", label: "GitHub", href: REPO_URL }],
			editLink: {
				baseUrl: `${REPO_URL}/edit/main/docs/`,
			},
			lastUpdated: true,
			tableOfContents: { minHeadingLevel: 2, maxHeadingLevel: 3 },
			expressiveCode: {
				themes: ["github-dark", "github-light"],
				styleOverrides: { borderRadius: "0.375rem" },
			},
			plugins: [
				starlightBlog({
					title: "Blog",
					postCount: 12,
					authors: {
						sergei: {
							name: "Sergei Shmakov",
							url: "https://github.com/sergeyshmakov",
							picture: "https://github.com/sergeyshmakov.png",
						},
					},
				}),
			],
			sidebar: [
				{
					label: "Getting Started",
					items: [
						"getting-started/overview",
						"getting-started/deploy",
						"getting-started/clients",
						"getting-started/migrate-from-mineru-api",
					],
				},
				{
					label: "Guides",
					items: [
						"guides/choosing-gpu",
						"guides/concurrency",
						"guides/input-formats",
						"guides/output-modes",
						"guides/scaling",
						"guides/observability",
						"guides/network-volumes",
						"guides/troubleshooting",
					],
				},
				{
					label: "Reference",
					items: ["reference/api"],
				},
			],
			head: [
				{
					tag: "style",
					attrs: { "data-rm-critical-bg": "" },
					content:
						"html,body{background-color:#090236;}html[data-theme='light'],html[data-theme='light'] body{background-color:#fff;}",
				},
				{
					tag: "meta",
					attrs: {
						property: "og:image",
						content: "https://mineru.shmakov.tools/og-default.png",
					},
				},
				{
					tag: "meta",
					attrs: {
						property: "og:image:alt",
						content: "MinerU document parsing deployed on RunPod Serverless",
					},
				},
				{
					tag: "meta",
					attrs: { property: "og:image:width", content: "1200" },
				},
				{
					tag: "meta",
					attrs: { property: "og:image:height", content: "630" },
				},
				{
					tag: "link",
					attrs: { rel: "sitemap", href: "/sitemap-index.xml" },
				},
			],
		}),
		sitemap(),
	],
});
